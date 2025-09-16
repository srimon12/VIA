from fastapi import APIRouter, Depends, Request
from typing import List, Dict, Any
from app.services.ingestion_service import IngestionService

router = APIRouter()

def get_ingestion_service(req: Request) -> IngestionService:
    return req.app.state.ingestion_service

@router.post("/stream", response_model=None)
async def ingest_stream(
    logs: List[Dict[str, Any]],
    ingestion_service: IngestionService = Depends(get_ingestion_service),
):
    points_ingested = await ingestion_service.ingest_log_batch(logs)
    return {"status": "ok", "tier1_ingested": points_ingested}
