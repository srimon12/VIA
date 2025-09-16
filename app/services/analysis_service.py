# file: app/services/analysis_service.py
# Action: Replace the entire file with this content.

import asyncio
import logging
import re
import time
from collections import Counter
from typing import Any, Dict, List, Optional, DefaultDict

from qdrant_client import models

from app.core.config import settings
from app.services.control_service import ControlService
from app.services.qdrant_service import QdrantService

log = logging.getLogger("api.services.analysis")

class AnalysisService:
    def __init__(self, qdrant_service: QdrantService, control_service: ControlService) -> None:
        self.qdrant_service = qdrant_service
        self.control_service = control_service

# file: app/services/analysis_service.py

    async def _promote_to_tier2(self, anomalies: List[Dict[str, Any]]):
        """
        FIX: This function now correctly transforms Tier-1 anomaly payloads
        into the structured Tier-2 event format before ingestion.
        """
        if not anomalies:
            return

        # Group raw anomalies by rhythm_hash to create event clusters
        clusters: Dict[str, List[Dict[str, Any]]] = {}
        for anomaly in anomalies:
            rhash = anomaly["rhythm_hash"]
            clusters.setdefault(rhash, []).append(anomaly)

        events_to_ingest: List[Dict[str, Any]] = []
        for rhash, logs in clusters.items():
            sorted_logs = sorted(logs, key=lambda x: x["ts"])
            start_ts = sorted_logs[0]["ts"]
            end_ts = sorted_logs[-1]["ts"]
            
            # Use the body of the first log for embedding and indexing
            text_for_embedding = sorted_logs[0].get("body", "")

            # Build the final Tier-2 event payload
            event_payload = {
                "entity_type": "event_cluster",
                "rhythm_hash": rhash,
                "start_ts": start_ts,
                "end_ts": end_ts,
                "count": len(logs),
                "service": sorted_logs[0].get("service", "unknown"),
                "severity": sorted_logs[0].get("severity", "INFO"),
                "body": text_for_embedding,
                "sample_logs": [log["full_log_json"] for log in sorted_logs[:5]],
            }
            
            # This is the structure ingest_to_tier2 expects
            events_to_ingest.append({
                "text_for_embedding": text_for_embedding,
                "payload": event_payload
            })

        await self.qdrant_service.ingest_to_tier2(events_to_ingest)

    async def find_rhythm_anomalies(self, window_sec: int) -> Dict[str, List[Dict[str, Any]]]:
        now = int(time.time())
        cur_start = now - window_sec
        hist_end = cur_start
        hist_start = hist_end - 24 * 3600

        recent_points = await self.qdrant_service.get_points_from_tier1(cur_start, now)
        
        hist_filter = models.Filter(must=[models.FieldCondition(key="ts", range=models.Range(gte=hist_start, lte=hist_end))])
        hist_count_res = await self.qdrant_service.client.count(collection_name=settings.TIER_1_COLLECTION_PREFIX, count_filter=hist_filter, exact=False)
        hist_sample_points, _ = await self.qdrant_service.client.scroll(collection_name=settings.TIER_1_COLLECTION_PREFIX, scroll_filter=hist_filter, limit=10_000, with_payload=True)

        recent_hashes = [p.payload["rhythm_hash"] for p in recent_points]
        known_hashes = {p.payload["rhythm_hash"] for p in hist_sample_points}
        recent_counts = Counter(recent_hashes)
        by_hash = {p.payload["rhythm_hash"]: p.payload for p in recent_points}

        novel_anomalies, freq_anomalies = [], []

        for r_hash, r_count in recent_counts.items():
            if self.control_service.is_suppressed_or_patched(r_hash):
                continue
            
            payload = dict(by_hash[r_hash])
            if r_hash not in known_hashes:
                payload["anomaly_type"] = "novelty"
                novel_anomalies.append(payload)
            else:
                sample_hits = sum(1 for p in hist_sample_points if p.payload["rhythm_hash"] == r_hash)
                est_hist_total = (sample_hits / len(hist_sample_points)) * hist_count_res.count if hist_sample_points else 0.0
                est_hist_per_window = (est_hist_total / (24 * 3600)) * window_sec
                
                if r_count > 5 and r_count > est_hist_per_window * 5.0:
                    payload["anomaly_type"] = "frequency"
                    payload["frequency_details"] = {"current_count": r_count, "historical_avg": round(est_hist_per_window, 2)}
                    freq_anomalies.append(payload)

        all_anoms = novel_anomalies + freq_anomalies
        if all_anoms:
            await self._promote_to_tier2(all_anoms)

        return {"novel_anomalies": novel_anomalies, "frequency_anomalies": freq_anomalies}

    async def find_tier2_anomalies(self, start_ts: int, end_ts: int, text_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        query_text = text_filter or "error log anomaly"
        
        dense_vec = self.qdrant_service.tier2_dense_model.embed([query_text])[0].tolist()
        sparse_raw = self.qdrant_service.tier2_sparse_model.embed([query_text])[0]
        sparse_vec = models.SparseVector(indices=sparse_raw.indices, values=sparse_raw.values)

        must = [models.FieldCondition(key="start_ts", range=models.Range(gte=start_ts, lte=end_ts))]
        if text_filter:
            must.append(models.FieldCondition(key="body", match=models.MatchText(query=text_filter)))
        
        dense_req = models.SearchRequest(vector=models.NamedVector(name="log_dense_vector", vector=dense_vec), filter=models.Filter(must=must), limit=50, with_payload=True)
        sparse_req = models.SearchRequest(vector=models.NamedSparseVector(name="bm25_vector", vector=sparse_vec), filter=models.Filter(must=must), limit=50, with_payload=True)

        collections = self.qdrant_service._get_collections_for_window(settings.TIER_2_COLLECTION_PREFIX, start_ts, end_ts)
        tasks = [self.qdrant_service.client.search_batch(collection_name=c, requests=[dense_req, sparse_req]) for c in collections]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_dense, all_sparse = [], []
        for r in results:
            if not isinstance(r, Exception) and len(r) == 2:
                all_dense.extend(r[0])
                all_sparse.extend(r[1])

        scores: Dict[str, float] = Counter()
        id2hit = {h.id: h for h in all_dense + all_sparse}
        for i, h in enumerate(all_dense): scores[h.id] += 1.0 / (60 + i + 1)
        for i, h in enumerate(all_sparse): scores[h.id] += 1.0 / (60 + i + 1)
        
        top_ids = sorted(scores, key=scores.get, reverse=True)[:50]
        return [id2hit[_id].payload for _id in top_ids if _id in id2hit]

    async def find_tier2_clusters(self, start_ts: int, end_ts: int, text_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        must = [models.FieldCondition(key="start_ts", range=models.Range(gte=start_ts, lte=end_ts))]
        if text_filter:
            must.append(models.FieldCondition(key="body", match=models.MatchText(query=text_filter)))

        req = models.SearchGroupsRequest(
            vector=models.NamedVector(
                name="log_dense_vector",
                vector=[0.0] * self.qdrant_service.tier2_dim()
            ),
            filter=models.Filter(must=must),
            group_by="rhythm_hash", group_size=1, limit=100, with_payload=True
        )

        collections = self.qdrant_service._get_collections_for_window(settings.TIER_2_COLLECTION_PREFIX, start_ts, end_ts)
        tasks = [self.qdrant_service.client.search_groups(collection_name=c, request=req) for c in collections]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        groups = []
        for r in results:
            if not isinstance(r, Exception):
                groups.extend(r.groups)
        
        return [{"cluster_id": g.id, "incident_count": len(g.hits), "top_hit": g.hits[0].payload} for g in groups if g.hits]

    async def triage_similar_events(self, positive_ids: List[str], negative_ids: List[str], start_ts: int, end_ts: int) -> List[Dict[str, Any]]:
        if not positive_ids:
            return []
        req = models.RecommendRequest(positive=positive_ids, negative=negative_ids, using="log_dense_vector", limit=50, with_payload=True)

        collections = self.qdrant_service._get_collections_for_window(settings.TIER_2_COLLECTION_PREFIX, start_ts, end_ts)
        tasks = [self.qdrant_service.client.recommend(collection_name=c, request=req) for c in collections]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_hits = []
        for r in results:
            if not isinstance(r, Exception):
                all_hits.extend(r)
        
        all_hits.sort(key=lambda p: p.score, reverse=True)
        return [{"id": p.id, "score": p.score, "payload": p.payload} for p in all_hits[:req.limit]]