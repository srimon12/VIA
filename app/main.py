from fastapi import FastAPI, Depends, HTTPException, Header
from qdrant_client import QdrantClient, models
from pydantic import BaseModel
import time
import logging

app = FastAPI()
logger = logging.getLogger(__name__)


client = QdrantClient(host="localhost", port=6333)

class AtlasQuery(BaseModel):
    window_sec: int = 3600

class SimilarQuery(BaseModel):
    positive_ids: list[str]
    window_sec: int = 3600

class Citations(BaseModel):
    citations: list[dict]

@app.post("/anomalies")
async def anomalies(q: AtlasQuery):
    now = int(time.time())
    filter_ = models.Filter(must=[models.FieldCondition(key="ts", range=models.Range(gte=now - q.window_sec))])
    try:
        points = client.scroll("logs_atlas", scroll_filter=filter_, limit=1000)[0]
    except Exception as e:
        logger.error({"action": "anomalies", "error": str(e)})
        return {"outliers": [], "citations": []}
    if not points:
        logger.info({"action": "anomalies", "outliers": 0})
        return {"outliers": [], "citations": []}
    outliers = []
    for p in points:
        try:
            recs = client.recommend("logs_atlas", positive=[p.id], query_filter=filter_, limit=20)
            mean_score = sum(r.score for r in recs) / len(recs) if recs else 0
            if mean_score > 0.7:
                outliers.append({"id": p.id, "payload": p.payload, "score": mean_score})        
        except Exception as e:
            logger.warning({"action": "anomalies", "error": str(e), "point_id": p.id})
            continue
    logger.info({"action": "anomalies", "outliers": len(outliers)})
    citations = [{"id": o["id"], "ts": o["payload"]["ts"], "hash": o["payload"]["hash"]} for o in outliers]
    return {"outliers": outliers, "citations": citations}

# In app/main.py

# In app/main.py

@app.post("/similar")
async def similar(q: SimilarQuery):
    now = int(time.time())
    past_filter = models.Filter(must=[
        models.FieldCondition(key="ts", range=models.Range(lt=now - q.window_sec))
    ])
    try:
        groups = client.recommend_groups(
            collection_name="logs_atlas",
            positive=q.positive_ids,
            query_filter=past_filter,
            group_by="service",
            limit=3,
            group_size=5
        )
    except Exception as e:
        logger.error({"action": "similar", "error": str(e)})
        return {"groups": [], "citations": []}

    # FIX #1: Changed g.points to g.hits
    result_groups = [
        {
            "group": g.id, 
            "items": [{"id": p.id, "score": p.score, "payload": p.payload} for p in g.hits]
        } 
        for g in groups.groups
    ]
    
    # FIX #2: Changed g.points to g.hits
    citations = [
        {"id": p.id, "ts": p.payload["ts"], "hash": p.payload["hash"]} 
        for g in groups.groups for p in g.hits
    ]

    logger.info({"action": "similar", "groups": len(result_groups)})
    return {"groups": result_groups, "citations": citations}
@app.get("/health")
async def health():
    try:
        has_collection = client.has_collection("logs_atlas")
        return {"status": "ok", "qdrant": has_collection}
    except Exception as e:
        return {"status": "error", "qdrant": False, "error": str(e)}