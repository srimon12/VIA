from app.services.qdrant_service import QdrantService
from app.services.control_service import ControlService

from app.core.config import settings
from qdrant_client import models

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

    async def find_rhythm_anomalies(self, window_sec: int) -> List[Dict[str, Any]]:
        now = int(time.time())
        current_window_start = now - window_sec
        historical_window_start = now - (24 * 3600)

        # Get unique hashes from the two time windows in parallel
        known_hashes_task = self.qdrant_service.get_unique_hashes_from_tier1(historical_window_start, current_window_start)
        recent_points = await self.qdrant_service.get_points_from_tier1(current_window_start, now)
        known_hashes = await known_hashes_task

        novel_anomalies = []
        # Use a set to only promote each novel hash once per run
        seen_novel_hashes = set()
        for point in recent_points:
            rhythm_hash = point.payload["rhythm_hash"]
            if rhythm_hash not in known_hashes and rhythm_hash not in seen_novel_hashes:
                if not self.control_service.is_suppressed_or_patched(rhythm_hash):
                    novel_anomalies.append(point.payload)
                    seen_novel_hashes.add(rhythm_hash)
            
        if novel_anomalies: 
            log.info(f"Detected {len(novel_anomalies)} novel rhythm anomalies. Promoting to Tier 2.")
            self._promote_to_tier2(novel_anomalies)
            
        return novel_anomalies
    
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


    async def find_tier2_similar(self, positive_ids: List[str], start_ts: int, end_ts: int) -> List[Dict[str, Any]]:
        """
        Finds similar past event_clusters from Tier 2, grouped by service,
        using a federated query.
        """
        prefix = settings.TIER_2_COLLECTION_PREFIX
        
        # To find similar items, we first need the vector of the positive_id
        # For simplicity, we'll use the first ID as the anchor.
        # A more advanced version could average the vectors of all positive_ids.
        
        # Determine the collection for the first positive ID to retrieve its vector
        anchor_point_id = positive_ids[0]
        try:
            # Note: We don't know the exact date of the ID, so a robust way is needed.
            # For this implementation, we assume we can find it.
            # A better way would be to store the collection name in the payload or use aliasing.
            # For now, let's assume we can get the vector.
            # This is a simplification for the current stage.
            pass # We will create a simplified recommend request for now
        except Exception as e:
            log.error(f"Could not retrieve anchor point for similarity search: {e}")
            return []

        recommend_request = models.RecommendGroupsRequest(
            positive=positive_ids,
            group_by="service",
            limit=3, # Groups
            group_size=3 # Items per group
        )
        
        groups = await self.qdrant_service.federated_recommend_groups(
            prefix=prefix,
            start_ts=start_ts,
            end_ts=end_ts,
            recommend_request=recommend_request
        )

        result_groups = [
            {
                "group_by_key": group.id,
                "hits": [
                    {"id": hit.id, "score": hit.score, "payload": hit.payload}
                    for hit in group.hits
                ]
            } for group in groups
        ]
        return result_groups
