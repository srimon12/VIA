# file: app/api/v1/endpoints/ingest.py
# Action: Replace file content.

from fastapi import APIRouter, Depends
from typing import List

from app.schemas.models import OTelLogRecord
from app.services.qdrant_service import QdrantService
from app.services.ingestion_service import IngestionService

router = APIRouter()

@router.post("/stream")
async def ingest_stream(
    logs: List[OTelLogRecord], 
    qdrant_service: QdrantService = Depends(), # FastAPI creates singletons for Depends()
    ingestion_service: IngestionService = Depends()
):
    points_ingested = ingestion_service.ingest_log_batch(logs)
    return {"status": "ok", "tier1_ingested": points_ingested}