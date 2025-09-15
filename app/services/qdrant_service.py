# file: app/services/qdrant_service.py

import logging
import uuid
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any

from qdrant_client import QdrantClient, models
from fastembed import TextEmbedding

from app.core.config import settings


log = logging.getLogger("api.services.qdrant")


class QdrantService:
    def __init__(self):
        self.client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT, prefer_grpc=True)
        self.tier1_embed_model = TextEmbedding(settings.TIER_1_EMBED_MODEL)
        self.tier2_embed_model = TextEmbedding(settings.TIER_2_EMBED_MODEL)

    def _get_daily_collection_name(self, prefix: str, ts: int) -> str:
        dt = datetime.fromtimestamp(ts)
        return f"{prefix}_{dt.strftime('%Y_%m_%d')}"

    def _get_collections_for_window(self, prefix: str, start_ts: int, end_ts: int) -> List[str]:
        """Calculates the list of daily collections within a time window."""
        start_date = datetime.fromtimestamp(start_ts).date()
        end_date = datetime.fromtimestamp(end_ts).date()
        delta = end_date - start_date
        return [
            f"{prefix}_{(start_date + timedelta(days=i)).strftime('%Y_%m_%d')}"
            for i in range(delta.days + 1)
        ]

    def setup_collections(self):
        log.info(f"Recreating Tier 1 collection: {settings.TIER_1_COLLECTION_PREFIX}")       
        self.client.recreate_collection(
            collection_name=settings.TIER_1_COLLECTION_PREFIX,
            vectors_config=models.VectorParams(size=384, distance=models.Distance.COSINE),
        )

    def _ensure_daily_tier2_collection(self, collection_name: str):
        try:
            self.client.get_collection(collection_name=collection_name)
        except Exception:
            log.warning(f"Creating daily Tier 2 collection: {collection_name}")
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config={
                    "log_dense_vector": models.VectorParams(size=384, distance=models.Distance.COSINE)
                },
                # Add sparse vector config here in the future
            )

    def embed_and_upsert_tier1(self, points: List[Dict[str, Any]]) -> int:
        if not points: return 0
        templates_to_embed = [p['template'] for p in points]
        embeddings = self.tier1_embed_model.embed(templates_to_embed)
        qdrant_points = [
            models.PointStruct(id=str(uuid.uuid4()), vector=vector.tolist(), payload=point["payload"])
            for point, vector in zip(points, embeddings)
        ]
        self.client.upsert(collection_name=settings.TIER_1_COLLECTION_PREFIX, points=qdrant_points)
        return len(qdrant_points)

    def ingest_to_tier2(self, events: List[Dict[str, Any]]) -> int:
        """Ingests promoted events into the correct daily Tier 2 collection."""
        if not events: return 0
        
        # Group events by day to perform efficient batch upserts
        events_by_collection: Dict[str, List[Dict[str, Any]]] = {}
        for event in events:
            collection_name = self._get_daily_collection_name(settings.TIER_2_COLLECTION_PREFIX, event['payload']['start_ts'])
            if collection_name not in events_by_collection:
                events_by_collection[collection_name] = []
            events_by_collection[collection_name].append(event)
        
        for collection_name, daily_events in events_by_collection.items():
            self._ensure_daily_tier2_collection(collection_name)
            texts_to_embed = [e['text_for_embedding'] for e in daily_events]
            embeddings = self.tier2_embed_model.embed(texts_to_embed)
            
            qdrant_points = [
                models.PointStruct(
                    id=str(uuid.uuid4()),
                    vector={"log_dense_vector": vector.tolist()},
                    payload=event["payload"]
                ) for event, vector in zip(daily_events, embeddings)
            ]
            self.client.upsert(collection_name=collection_name, points=qdrant_points)
            log.info(f"Promoted and ingested {len(qdrant_points)} events to Tier 2 collection '{collection_name}'")
        return len(events)

    async def get_points_from_tier1(self, start_ts: int, end_ts: int) -> List[models.Record]:
        points, _ = await self.client.scroll(
            collection_name=settings.TIER_1_COLLECTION_PREFIX,
            scroll_filter=models.Filter(must=[models.FieldCondition(key="ts", range=models.Range(gte=start_ts, lte=end_ts))]),
            limit=100_000, with_payload=True
        )
        return points

    async def federated_search(self, prefix: str, start_ts: int, end_ts: int, search_request: models.SearchRequest) -> List[models.ScoredPoint]:
        """Performs a search across multiple daily collections in parallel."""
        target_collections = self._get_collections_for_window(prefix, start_ts, end_ts)
        
        search_tasks = [
            self.client.search(collection_name=name, search_request=search_request)
            for name in target_collections
        ]
        
        results_from_collections = await asyncio.gather(*search_tasks, return_exceptions=True)
        
        all_hits = []
        for result in results_from_collections:
            if not isinstance(result, Exception):
                all_hits.extend(result)
        
        # Re-rank all results by score
        return sorted(all_hits, key=lambda x: x.score, reverse=True)

    async def federated_recommend_groups(self, prefix: str, start_ts: int, end_ts: int, recommend_request: models.RecommendGroupsRequest) -> List[models.Recommendations]:
        """Performs a recommend_groups query across multiple daily collections in parallel."""
        target_collections = self._get_collections_for_window(prefix, start_ts, end_ts)
        
        # We need to query one collection first to see if it returns any groups.
        # A simple parallel approach can be complex to merge.
        # For a robust implementation, we iterate until we find enough groups.
        
        all_groups = []
        for collection_name in reversed(target_collections): # Start from the most recent day
            try:
                result = await self.client.recommend_groups(
                    collection_name=collection_name,
                    recommend_request=recommend_request
                )
                if result and result.groups:
                    all_groups.extend(result.groups)
                
                # Stop if we have enough groups to satisfy the request limit
                if len(all_groups) >= recommend_request.limit:
                    break
            except Exception as e:
                log.warning(f"Could not perform recommend_groups on '{collection_name}': {e}")
                continue
        
        # The result is a list of groups, which can be returned directly.
        # De-duplication of groups can be added here if necessary.
        return all_groups[:recommend_request.limit]