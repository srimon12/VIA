from app.services.qdrant_service import QdrantService
from app.services.control_service import ControlService

from app.core.config import settings
from qdrant_client import models
import logging
from typing import List, Dict, Any, Optional
import time
from collections import Counter
import asyncio
log = logging.getLogger("api.services.analysis")

class AnalysisService:
    def __init__(self, qdrant_service: QdrantService, control_service: ControlService) -> None:
        self.qdrant_service = qdrant_service
        self.control_service = control_service

    def _promote_to_tier2(self, anomalies: List[Dict[str, Any]]) -> None:
        """Transforms novel Tier 1 anomalies into Tier 2 event_cluster entities."""
        if not anomalies: 
            return
        
        # Group logs by rhythm_hash to create event clusters
        clusters: Dict[str, List[Dict[str, Any]]] = {}
        for anomaly in anomalies:
            rhash = anomaly['rhythm_hash']
            if rhash not in clusters: 
                clusters[rhash] = []
            clusters[rhash].append(anomaly)
    
        events_to_ingest = []
        for rhash, logs in clusters.items():
            sorted_logs = sorted(logs, key=lambda x: x['ts'])
            start_ts = sorted_logs[0]['ts']
            end_ts = sorted_logs[-1]['ts']
            
            # Text for embedding is a summary of the templates/messages
            text_for_embedding = self.qdrant_service._get_template(sorted_logs[0]['full_log_json']['Body'])
            
            event_payload = {
                "entity_type": "event_cluster",
                "rhythm_hash": rhash,
                "start_ts": start_ts,
                "end_ts": end_ts,
                "count": len(logs),
                "service": sorted_logs[0]['service'],
                "severity": sorted_logs[0]['severity'], 
                "sample_logs": [log['full_log_json'] for log in sorted_logs[:5]] # Sample up to 5 logs
            }
            events_to_ingest.append({
                "text_for_embedding": text_for_embedding,
                "payload": event_payload
            })

        self.qdrant_service.ingest_to_tier2(events_to_ingest)

    async def find_rhythm_anomalies(self, window_sec: int) -> Dict[str, List[Dict[str, Any]]]:
        now = int(time.time())
        current_window_start = now - window_sec
        # Historical window is the 24 hours prior to the current window
        historical_window_end = current_window_start
        historical_window_start = historical_window_end - (24 * 3600)

        # 1. Get all recent points and historical hashes
        recent_points_task = self.qdrant_service.get_points_from_tier1(current_window_start, now)
        historical_points_task = self.qdrant_service.get_points_from_tier1(historical_window_start, historical_window_end)
        
        recent_points, historical_points = await asyncio.gather(recent_points_task, historical_points_task)

        # 2. Count hash occurrences in both windows
        recent_hashes = [p.payload["rhythm_hash"] for p in recent_points]
        historical_hashes = [p.payload["rhythm_hash"] for p in historical_points]
        
        recent_counts = Counter(recent_hashes)
        historical_counts = Counter(historical_hashes)
        
        known_hashes = set(historical_counts.keys())

        # 3. Identify Novelty and Frequency Anomalies
        novel_anomalies = []
        frequency_anomalies = []
        
        # Use a dict to map hash to its point payload for easy lookup
        points_by_hash = {p.payload["rhythm_hash"]: p.payload for p in recent_points}

        for r_hash, r_count in recent_counts.items():
            if self.control_service.is_suppressed_or_patched(r_hash):
                continue

            # --- Novelty Detection ---
            if r_hash not in known_hashes:
                anomaly_payload = points_by_hash[r_hash]
                anomaly_payload["anomaly_type"] = "novelty"
                novel_anomalies.append(anomaly_payload)
            
            # --- Frequency Spike Detection ---
            else:
                # A "day" has 144 ten-minute windows (24 * 6)
                # We normalize the historical count to match the current window size
                historical_avg_count = historical_counts.get(r_hash, 0) / (24 * 3600 / window_sec)
                
                # Define spike thresholds
                MIN_COUNT_FOR_SPIKE = 10
                SPIKE_MULTIPLIER = 5.0
                
                is_significant_spike = (
                    r_count > MIN_COUNT_FOR_SPIKE and
                    r_count > (historical_avg_count * SPIKE_MULTIPLIER)
                )

                if is_significant_spike:
                    anomaly_payload = points_by_hash[r_hash]
                    anomaly_payload["anomaly_type"] = "frequency"
                    anomaly_payload["frequency_details"] = {
                        "current_count": r_count,
                        "historical_avg": round(historical_avg_count, 2)
                    }
                    frequency_anomalies.append(anomaly_payload)

        # 4. Promote all detected anomalies to Tier 2
        all_anomalies = novel_anomalies + frequency_anomalies
        if all_anomalies:
            log.info(f"Detected {len(novel_anomalies)} novel and {len(frequency_anomalies)} frequency anomalies. Promoting.")
            self._promote_to_tier2(all_anomalies)
            
        return {"novel_anomalies": novel_anomalies, "frequency_anomalies": frequency_anomalies}

    
    async def find_tier2_anomalies(self, start_ts: int, end_ts: int) -> List[Dict[str, Any]]:
        """Performs federated anomaly scoring on Tier 2 event clusters."""
        # This is a placeholder for a more advanced Tier 2 anomaly logic.
        # For now, we just retrieve all event clusters in the time window.
        prefix = settings.TIER_2_COLLECTION_PREFIX
        collections = self.qdrant_service._get_collections_for_window(prefix, start_ts, end_ts)
        
        all_clusters = []
        for coll in collections:
            points, _ = await self.qdrant_service.client.scroll(
                collection_name=coll,
                scroll_filter=models.Filter(must=[models.FieldCondition(key="start_ts", range=models.Range(gte=start_ts, lte=end_ts))]),
                limit=1000, with_payload=True
            )
            all_clusters.extend([p.payload for p in points])
            
        return sorted(all_clusters, key=lambda x: x['start_ts'], reverse=True)

    async def find_tier2_clusters(self, start_ts: int, end_ts: int, text_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Finds unique incident clusters by grouping on rhythm_hash."""
        
        # 1. Reuse the same filter logic from hybrid search
        must_conditions = [
            models.FieldCondition(key="start_ts", range=models.Range(gte=start_ts, lte=end_ts))
        ]
        if text_filter:
            must_conditions.append(
                models.FieldCondition(key="body", match=models.MatchText(query=text_filter))
            )
            search_vector = self.qdrant_service.tier2_embed_model.embed([text_filter])[0].tolist()
        else:
            search_vector = self.qdrant_service.tier2_embed_model.embed(["error log anomaly"])[0].tolist()

        # 2. Create the SearchGroupsRequest
        search_groups_request = models.SearchGroupsRequest(
            vector=models.NamedVector(name="log_dense_vector", vector=search_vector),
            filter=models.Filter(must=must_conditions),
            group_by="rhythm_hash", # The field to group by
            group_size=1,            # We only need one example from each group
            limit=100,               # Return up to 100 unique clusters
            with_payload=True
        )

        # 3. Execute the federated group search
        prefix = settings.TIER_2_COLLECTION_PREFIX
        groups = await self.qdrant_service.federated_group_search(
            prefix=prefix,
            start_ts=start_ts,
            end_ts=end_ts,
            search_groups_request=search_groups_request
        )

        # 4. Format the result for a clean API response
        return [
            {"cluster_id": group.id, "incident_count": group.hits_count, "top_hit": group.hits[0].payload}
            for group in groups
        ]
    
    async def triage_similar_events(
        self,
        positive_ids: List[str],
        negative_ids: List[str],
        start_ts: int,
        end_ts: int
    ) -> List[Dict[str, Any]]:
        """Constructs and executes a federated triage recommend request."""
        
        if not positive_ids:
            return []

        recommend_request = models.RecommendRequest(
            positive=positive_ids,
            negative=negative_ids,
            using="log_dense_vector", # Specify which vector to use
            limit=50,
            with_payload=True
        )

        prefix = settings.TIER_2_COLLECTION_PREFIX
        results = await self.qdrant_service.federated_recommend(
            prefix=prefix,
            start_ts=start_ts,
            end_ts=end_ts,
            recommend_request=recommend_request
        )

        return [{"id": p.id, "score": p.score, "payload": p.payload} for p in results]