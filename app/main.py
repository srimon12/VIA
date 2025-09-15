# file: app/main.py

from fastapi import FastAPI
from qdrant_client import QdrantClient, models
from pydantic import BaseModel, Field
import time
import logging
from typing import List, Dict, Any
from contextlib import asynccontextmanager # --- NEW ---

# --- Import refactored ingestion logic ---
from ingestor.main import process_log_batch, embed_and_upsert_batch, TIER_2_COLLECTION_NAME
from fastembed import TextEmbedding

# --- Initialize clients and models centrally ---
qdrant_client = QdrantClient(host="localhost", port=6333)
embed_model = TextEmbedding("BAAI/bge-small-en-v1.5")

# --- NEW: Lifespan manager to ensure collection exists on startup ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    On application startup, check if the Tier 2 collection exists and create it if not.
    """
    log.info("Application startup...")
    try:
        qdrant_client.get_collection(collection_name=TIER_2_COLLECTION_NAME)
        log.info(f"Collection '{TIER_2_COLLECTION_NAME}' already exists.")
    except Exception:
        log.warning(f"Collection '{TIER_2_COLLECTION_NAME}' not found. Creating it now.")
        qdrant_client.create_collection(
            collection_name=TIER_2_COLLECTION_NAME,
            vectors_config=models.VectorParams(size=384, distance=models.Distance.COSINE),
        )
        log.info(f"Successfully created collection '{TIER_2_COLLECTION_NAME}'.")
    yield
    # --- Application shutdown logic would go here ---
    log.info("Application shutdown.")

# --- MODIFIED: Pass the lifespan manager to the FastAPI app ---
app = FastAPI(lifespan=lifespan)
log = logging.getLogger("api") # Using a named logger is better practice


# --- OTel Models (Copied from otel_mock for data contract) ---
class OTelLogAttribute(BaseModel):
    key: str
    value: str

class OTelLogRecord(BaseModel):
    TimeUnixNano: int
    SeverityText: str = "INFO"
    Body: str
    Attributes: List[OTelLogAttribute] = []


# --- NEW: Streaming Ingestion Endpoint ---
@app.post("/ingest/stream")
async def ingest_stream(logs: List[OTelLogRecord]):
    """Receives a batch of OTel logs and ingests them into the Tier 2 index."""
    start_time = time.perf_counter()
    
    # Convert OTel format to the simple dict our processor expects
    log_dicts = [{"body": log.Body, "ts": log.TimeUnixNano // 1_000_000_000} for log in logs]
    
    # Process, embed, and upsert
    processed_points = process_log_batch(log_dicts)
    points_ingested = embed_and_upsert_batch(qdrant_client, embed_model, processed_points, TIER_2_COLLECTION_NAME)
    
    latency_ms = (time.perf_counter() - start_time) * 1000
    log.info(f"Ingested stream of {len(logs)} logs in {latency_ms:.2f}ms. Points created: {points_ingested}")
    return {"status": "ok", "received": len(logs), "ingested_points": points_ingested}


# --- Pydantic models for queries (unchanged) ---
class AtlasQuery(BaseModel):
    window_sec: int = 3600

class SimilarQuery(BaseModel):
    positive_ids: list[str]
    window_sec: int = 3600

# --- MODIFIED: Query Endpoints now use the new collection name ---
@app.post("/anomalies")
async def anomalies(q: AtlasQuery):
    start = time.perf_counter()
    now = int(time.time())
    filter_ = models.Filter(must=[models.FieldCondition(key="ts", range=models.Range(gte=now - q.window_sec))])
    
    points = qdrant_client.scroll(TIER_2_COLLECTION_NAME, scroll_filter=filter_, limit=1000)[0]
    
    if not points:
        return {"outliers": [], "latency_ms": int((time.perf_counter() - start) * 1000)}

    outliers = []
    for p in points:
        recs = qdrant_client.recommend(TIER_2_COLLECTION_NAME, positive=[p.id], query_filter=filter_, limit=20)
        mean_score = sum(r.score for r in recs) / len(recs) if recs else 0
        anomaly_score = 1 - mean_score
        if anomaly_score > 0.1:
            outliers.append({"id": p.id, "payload": p.payload, "score": anomaly_score})

    latency_ms = int((time.perf_counter() - start) * 1000)
    return {"outliers": outliers, "latency_ms": latency_ms}


@app.post("/similar")
async def similar(q: SimilarQuery):
    start = time.perf_counter()
    now = int(time.time())
    past_filter = models.Filter(must=[models.FieldCondition(key="ts", range=models.Range(lt=now - q.window_sec))])
    
    groups = qdrant_client.recommend_groups(
        collection_name=TIER_2_COLLECTION_NAME,
        positive=q.positive_ids,
        query_filter=past_filter,
        group_by="service",
        limit=3,
        group_size=5
    )
    result_groups = [{"group": g.id, "items": [{"id": p.id, "score": p.score, "payload": p.payload} for p in g.hits]} for g in groups.groups]
    latency_ms = int((time.perf_counter() - start) * 1000)
    return {"groups": result_groups, "latency_ms": latency_ms}

@app.get("/health")
async def health():
    try:
        collection_info = qdrant_client.get_collection(collection_name=TIER_2_COLLECTION_NAME)
        return {"status": "ok", "tier_2_collection_exists": True, "points": collection_info.points_count}
    except Exception:
        return {"status": "error", "tier_2_collection_exists": False}