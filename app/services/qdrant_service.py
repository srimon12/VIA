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
            vectors_config=models.VectorParams(
                size=384,
                distance=models.Distance.COSINE,
                on_disk=True,
                hnsw_config=models.HnswConfigDiff(on_disk=True, m=16, ef_construct=100),
            ),
            quantization_config=models.ScalarQuantization(
                scalar=models.ScalarQuantizationConfig(
                    type=models.ScalarType.INT8, quantile=0.99, always_ram=True
                )
            ),
        )

    def _ensure_daily_tier2_collection(self, collection_name: str):
        try:
            self.client.get_collection(collection_name=collection_name)
        except Exception:
            log.warning(f"Creating daily Tier 2 collection: {collection_name}")
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config={
                    "log_dense_vector": models.VectorParams(
                        size=384,  # Assuming bge-small-en-v1.5 dim
                        distance=models.Distance.COSINE,
                        on_disk=True,  # On-disk storage for scale
                        hnsw_config=models.HnswConfigDiff(  # HNSW optimizations
                            m=16,
                            ef_construct=100,
                            full_scan_threshold=10000,
                            on_disk=True,  # HNSW on-disk
                        ),  # that's 2MB per point when on disk
                    )
                },
                quantization_config=models.ScalarQuantization(  # Scalar quantization for mem efficiency
                    scalar=models.ScalarQuantizationConfig(
                        type=models.ScalarType.INT8,
                        quantile=0.99,
                        always_ram=True  # Reuse for perf
                    ),
                ),
                shard_number=2,  # Basic sharding for demo
                shard_key_selector=models.ShardKeySelector(  # Multi-tenancy via service
                    shard_keys=["service"]  # Shard by payload 'service' key
                ),
            )
            # Create full-text index for hybrid (prep for Step 2)
            self.client.create_payload_index(
                collection_name=collection_name,
                field_name="body",
                field_schema=models.TextIndexParams(
                    type=models.TextIndexType.TEXT,
                    tokenizer=models.TokenizerType.WORD,
                    min_token_len=2,
                    max_token_len=20,
                    lowercase=True,
                ),
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
    async def federated_recommend(self, prefix: str, start_ts: int, end_ts: int, recommend_request: models.RecommendRequest) -> List[models.ScoredPoint]:
        collections = self._get_collections_for_window(prefix, start_ts, end_ts)
        results = []
        for coll in collections:
            try:
                points = await self.client.recommend_async(
                    collection_name=coll,
                    request=recommend_request
                )
                results.extend(points)
            except Exception:
                continue
        # sort by score desc; truncate
        return sorted(results, key=lambda p: p.score, reverse=True)[:recommend_request.limit]
    async def federated_group_search(self, prefix: str, start_ts: int, end_ts: int, search_groups_request: models.SearchGroupsRequest) -> List[models.GroupId]:
        collections = self._get_collections_for_window(prefix, start_ts, end_ts)
        groups_all = []
        for coll in collections:
            try:
                resp = await self.client.search_groups_async(
                    collection_name=coll,
                    request=search_groups_request
                )
                groups_all.extend(resp.groups or [])
            except Exception:
                continue
        # Optional: merge by group.id if needed (best-score top hit kept)
        return groups_all