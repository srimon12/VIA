import asyncio
import logging
from collections import Counter
from typing import Any, Dict, List, Optional

from qdrant_client import models
from app.core.config import settings
from app.services.qdrant_service import QdrantService
from app.services.control_service import ControlService

log = logging.getLogger("api.services.forensic_analysis")

class ForensicAnalysisService:
    def __init__(self, qdrant_service: QdrantService, control_service: ControlService) -> None:
        self.qdrant_service = qdrant_service
        self.control_service = control_service
    async def find_tier2_clusters(self, start_ts: int, end_ts: int, text_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        must_conditions = []

        if start_ts is not None and end_ts is not None:
            must_conditions.append(
                models.FieldCondition(key="start_ts", range=models.Range(gte=start_ts, lte=end_ts))
            )
        
        query_vector_data = [0.0] * self.qdrant_service.tier2_dim() 
        
        if text_filter:
            must_conditions.append(models.FieldCondition(key="body", match=models.MatchText(text=text_filter)))
            query_vector_data = list(self.qdrant_service.tier2_dense_model.embed([text_filter]))[0]

        # FIX: Define query parameters directly, just like in the successful test script.
        query_vector = models.NamedVector(name="log_dense_vector", vector=query_vector_data)
        query_filter = models.Filter(must=must_conditions) if must_conditions else None

        if start_ts and end_ts:
            collections = self.qdrant_service._get_collections_for_window(settings.TIER_2_COLLECTION_PREFIX, start_ts, end_ts)
        else:
            all_collections = self.qdrant_service._sync_client.get_collections().collections
            collections = [c.name for c in all_collections if c.name.startswith(settings.TIER_2_COLLECTION_PREFIX)]
        
        if not collections:
             return []

        # FIX: Call the client with direct keyword arguments, not a request object.
        tasks = [self.qdrant_service.client.search_groups(
            collection_name=c,
            query_vector=query_vector,
            query_filter=query_filter,
            group_by="rhythm_hash",
            group_size=1,
            limit=100,
            with_payload=True
        ) for c in collections]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)

        groups = []
        for r in results:
            if not isinstance(r, Exception):
                groups.extend(r.groups)
        
        groups.sort(key=lambda g: g.hits[0].score, reverse=True)
        unpatched_groups = [
            g for g in groups if not self.control_service.is_suppressed_or_patched(g.id)
        ]

        return [{
            "cluster_id": g.id, 
            "incident_count": g.hits[0].payload.get('count', 1),
            "top_hit": {
                "id": g.hits[0].id,
                "payload": g.hits[0].payload
            }
        } for g in unpatched_groups if g.hits]
    async def triage_similar_events(self, positive_ids: List[str], negative_ids: List[str], start_ts: int, end_ts: int) -> List[Dict[str, Any]]:
        if not positive_ids:
            return []
        collections = self.qdrant_service._get_collections_for_window(settings.TIER_2_COLLECTION_PREFIX, start_ts, end_ts)
        tasks = [self.qdrant_service.client.recommend(
            collection_name=c,
            positive=positive_ids,
            negative=negative_ids,
            using="log_dense_vector",
            limit=50,
            with_payload=True
        ) for c in collections]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_hits = []
        for r in results:
            if not isinstance(r, Exception):
                all_hits.extend(r)

        all_hits.sort(key=lambda p: p.score, reverse=True)
        return [{"id": p.id, "score": p.score, "payload": p.payload} for p in all_hits[:50]]