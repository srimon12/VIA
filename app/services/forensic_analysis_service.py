import asyncio
import logging
from collections import Counter
from typing import Any, Dict, List, Optional

from qdrant_client import models
from app.core.config import settings
from app.services.qdrant_service import QdrantService

log = logging.getLogger("api.services.forensic_analysis")

class ForensicAnalysisService:
    def __init__(self, qdrant_service: QdrantService) -> None:
        self.qdrant_service = qdrant_service

    async def find_tier2_clusters(self, start_ts: int, end_ts: int, text_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        must_conditions = [] # Start with an empty list

        # FIX: Only add the time filter if start_ts and end_ts are provided
        if start_ts is not None and end_ts is not None:
            must_conditions.extend([
                models.FieldCondition(key="start_ts", range=models.Range(lte=end_ts)),
                models.FieldCondition(key="end_ts", range=models.Range(gte=start_ts)),
            ])
        
        query_vector = [0.0] * self.qdrant_service.tier2_dim() 
        
        if text_filter:
            must_conditions.append(models.FieldCondition(key="body", match=models.MatchText(text=text_filter)))
            query_vector = list(self.qdrant_service.tier2_dense_model.embed([text_filter]))[0]

        req = models.SearchGroupsRequest(
            vector=models.NamedVector(name="log_dense_vector", vector=query_vector),
            filter=models.Filter(must=must_conditions) if must_conditions else None, # Use filter only if conditions exist
            group_by="rhythm_hash",
            group_size=1,
            limit=100,
            with_payload=True
        )

        # FIX: Determine which collections to search
        if start_ts and end_ts:
            collections = self.qdrant_service._get_collections_for_window(settings.TIER_2_COLLECTION_PREFIX, start_ts, end_ts)
        else:
            # If no time window, search ALL existing tier 2 collections (Note: can be slow over time)
            all_collections = self.qdrant_service._sync_client.get_collections().collections
            collections = [c.name for c in all_collections if c.name.startswith(settings.TIER_2_COLLECTION_PREFIX)]
        
        if not collections:
             return []

        tasks = [self.qdrant_service.client.search_groups(collection_name=c, request=req) for c in collections]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        groups = []
        for r in results:
            if not isinstance(r, Exception):
                groups.extend(r.groups)
        
        groups.sort(key=lambda g: g.hits[0].score, reverse=True)

        return [{"cluster_id": g.id, "incident_count": len(g.hits), "top_hit": g.hits[0].payload} for g in groups if g.hits]

    async def triage_similar_events(self, positive_ids: List[str], negative_ids: List[str], start_ts: int, end_ts: int) -> List[Dict[str, Any]]:
        if not positive_ids:
            return []

        # Filter is implicitly handled by querying only the relevant daily collections
        req = models.RecommendRequest(
            positive=positive_ids,
            negative=negative_ids,
            using="log_dense_vector",
            limit=50,
            with_payload=True
        )

        collections = self.qdrant_service._get_collections_for_window(settings.TIER_2_COLLECTION_PREFIX, start_ts, end_ts)
        tasks = [self.qdrant_service.client.recommend(collection_name=c, request=req) for c in collections]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_hits = []
        for r in results:
            if not isinstance(r, Exception):
                all_hits.extend(r)

        all_hits.sort(key=lambda p: p.score, reverse=True)
        return [{"id": p.id, "score": p.score, "payload": p.payload} for p in all_hits[:req.limit]]