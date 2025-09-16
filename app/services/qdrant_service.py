# In file: app/services/qdrant_service.py
import logging
import uuid
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Iterable
import time
from qdrant_client import models, QdrantClient
from fastembed import TextEmbedding, SparseTextEmbedding

from app.core.config import settings
from app.services.qdrant_wrapper import QdrantClientWrapper

log = logging.getLogger("api.services.qdrant")

class QdrantService:
    def __init__(self) -> None:
        sync_client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT, prefer_grpc=True)
        self._sync_client = sync_client
        self.client = QdrantClientWrapper(sync_client)

        self.tier2_dense_model = TextEmbedding(settings.TIER_2_EMBED_MODEL)
        self.tier2_sparse_model = SparseTextEmbedding("Qdrant/bm25")
        
        self._tier1_dim = 64
        self._tier2_dim = len(list(self.tier2_dense_model.embed(["probe"]))[0])

    def tier1_dim(self) -> int:
        return self._tier1_dim

    def tier2_dim(self) -> int:
        return self._tier2_dim

    def _get_daily_collection_name(self, prefix: str, ts: int) -> str:
        dt = datetime.fromtimestamp(ts)
        return f"{prefix}_{dt.strftime('%Y_%m_%d')}"

    def _get_collections_for_window(self, prefix: str, start_ts: int, end_ts: int) -> Iterable[str]:
        s = datetime.fromtimestamp(start_ts).date()
        e = datetime.fromtimestamp(end_ts).date()
        for i in range((e - s).days + 1):
            yield f"{prefix}_{(s + timedelta(days=i)).strftime('%Y_%m_%d')}"

    async def setup_collections(self) -> None:
        log.info("Recreating Tier 1 collection with Binary Quantization: %s", settings.TIER_1_COLLECTION_PREFIX)
        
        await self.client.recreate_collection(
            collection_name=settings.TIER_1_COLLECTION_PREFIX,
            vectors_config=models.VectorParams(
                size=self.tier1_dim(), 
                distance=models.Distance.DOT
            ),
            # FIX: Pass the BinaryQuantization object directly, without the QuantizationConfig wrapper.
            quantization_config=models.BinaryQuantization(
                binary=models.BinaryQuantizationConfig(
                    always_ram=True
                )
            )
        )
        
        log.info("Creating payload index for 'ts' on Tier 1 collection...")
        await self.client.create_payload_index(
            collection_name=settings.TIER_1_COLLECTION_PREFIX,
            field_name="ts",
            field_schema=models.PayloadSchemaType.INTEGER,
            wait=True
        )

        today_ts = int(time.time())
        tier2_name = self._get_daily_collection_name(settings.TIER_2_COLLECTION_PREFIX, today_ts)
        self._ensure_daily_tier2_collection_sync(tier2_name)

    def _ensure_daily_tier2_collection_sync(self, collection_name: str) -> None:
        if self._sync_client.collection_exists(collection_name=collection_name):
            return
        log.warning("Creating daily Tier 2 collection: %s", collection_name)
        self._sync_client.create_collection(
            collection_name=collection_name,
            vectors_config={"log_dense_vector": models.VectorParams(size=self.tier2_dim(), distance=models.Distance.COSINE, on_disk=True)},
            sparse_vectors_config={"bm25_vector": models.SparseVectorParams(modifier=models.Modifier.IDF)},
            replication_factor=settings.QDRANT_REPLICATION_FACTOR,
            shard_number=settings.QDRANT_SHARD_NUMBER,
            # FIX: Tier 2 uses ScalarQuantization for its dense vectors.
            quantization_config=models.ScalarQuantization(
                scalar=models.ScalarQuantizationConfig(
                    type=models.ScalarType.INT8, 
                    quantile=0.99, 
                    always_ram=True
                )
            ),
        )
        self._sync_client.create_payload_index(collection_name=collection_name, field_name="start_ts", field_schema=models.PayloadSchemaType.INTEGER, wait=True)
        self._sync_client.create_payload_index(collection_name=collection_name, field_name="service", field_schema=models.PayloadSchemaType.KEYWORD, wait=True)
        self._sync_client.create_payload_index(collection_name=collection_name, field_name="rhythm_hash", field_schema=models.PayloadSchemaType.KEYWORD, wait=True)
        self._sync_client.create_payload_index(collection_name=collection_name, field_name="body", field_schema=models.TextIndexParams(type=models.TextIndexType.TEXT, tokenizer=models.TokenizerType.WORD, lowercase=True), wait=True)

    async def upsert_tier1_points(self, points: List[Dict[str, Any]]) -> int:
        if not points:
            return 0
        
        qpoints = [
            models.PointStruct(
                id=str(uuid.uuid4()), 
                payload=pt["payload"],
                vector=pt["vector"]
            )
            for pt in points
        ]
        await self.client.upsert(collection_name=settings.TIER_1_COLLECTION_PREFIX, points=qpoints, wait=False)
        return len(qpoints)

    async def ingest_to_tier2(self, events: List[Dict[str, Any]]) -> int:
        if not events:
            return 0
        buckets: Dict[str, List[Dict[str, Any]]] = {}
        for ev in events:
            cname = self._get_daily_collection_name(settings.TIER_2_COLLECTION_PREFIX, ev["payload"]["start_ts"])
            buckets.setdefault(cname, []).append(ev)
        ingested_count = 0
        for cname, daily_events in buckets.items():
            self._ensure_daily_tier2_collection_sync(cname)
            texts = [e["text_for_embedding"] for e in daily_events]
            dense_task = asyncio.to_thread(self.tier2_dense_model.embed, texts)
            sparse_task = asyncio.to_thread(self.tier2_sparse_model.embed, texts)
            dense_embs, sparse_embs = await asyncio.gather(dense_task, sparse_task)
            qpoints = [
                models.PointStruct(
                    id=str(uuid.uuid4()),
                    vector={"log_dense_vector": dvec.tolist(), "bm25_vector": models.SparseVector(indices=svec.indices.tolist(), values=svec.values.tolist())},
                    payload=ev["payload"],
                ) for ev, dvec, svec in zip(daily_events, dense_embs, sparse_embs)
            ]
            await self.client.upsert(collection_name=cname, points=qpoints, wait=False)
            ingested_count += len(daily_events)
        return ingested_count

    async def get_points_from_tier1(self, start_ts: int, end_ts: int) -> List[models.Record]:
        points, _ = await self.client.scroll(
            collection_name=settings.TIER_1_COLLECTION_PREFIX,
            scroll_filter=models.Filter(must=[models.FieldCondition(key="ts", range=models.Range(gte=start_ts, lte=end_ts))]),
            limit=100_000,
            with_payload=True,
            with_vectors=True # Also fetch the vector for analysis
        )
        return points

    async def get_historical_baseline(self, window_start_ts: int, sample_size: int = 10_000) -> List[models.Record]:
        hist_filter = models.Filter(must=[models.FieldCondition(key="ts", range=models.Range(lt=window_start_ts))])
        points, _ = await self.client.scroll(
            collection_name=settings.TIER_1_COLLECTION_PREFIX,
            scroll_filter=hist_filter,
            limit=sample_size,
            with_payload=True,
            with_vectors=True, # Also fetch the vector for analysis
            order_by=models.OrderBy(key="ts", direction=models.Direction.DESC)
        )
        return points