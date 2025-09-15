# In app/api/v1/endpoints/ingest.py

from fastapi import APIRouter, Depends
from typing import List

from app.schemas.models import OTelLogRecord
from app.services.qdrant_service import QdrantService
from app.services.ingestion_service import IngestionService

router = APIRouter()

# --- CORRECTED Dependency Injection ---

def get_qdrant_service():
    return QdrantService()

def get_ingestion_service(
    qdrant_service: QdrantService = Depends(get_qdrant_service)
) -> IngestionService:
    return IngestionService(qdrant_service=qdrant_service)


@router.post("/stream")
async def ingest_stream(
    logs: List[OTelLogRecord],
    ingestion_service: IngestionService = Depends(get_ingestion_service)
):
    points_ingested = ingestion_service.ingest_log_batch(logs)
    return {"status": "ok", "tier1_ingested": points_ingested}