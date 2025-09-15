# file: app/api/v1/endpoints/schema.py
# Action: Create this new file.

import logging
from fastapi import APIRouter, Depends, HTTPException
from typing import List

from app.schemas.models import DetectSchemaRequest, LogSchema
from app.services.anom_detection import AnomalyDetectionService

router = APIRouter()
log = logging.getLogger("api.endpoints.schema")

# Dependency for the service
def get_anomaly_service():
    # In a real app with state, this would be a singleton.
    # For now, this is fine.
    return AnomalyDetectionService()

@router.post("/detect", response_model=LogSchema)
async def detect_schema_endpoint(
    request: DetectSchemaRequest,
    service: AnomalyDetectionService = Depends(get_anomaly_service)
):
    """
    Analyzes a sample of log lines and suggests a parsing schema.
    """
    try:
        suggested_schema = service.detect_schema(request.sample_logs)
        if not suggested_schema or not suggested_schema.fields:
            raise HTTPException(status_code=400, detail="Could not detect a valid schema from the provided logs.")
        
        # We don't save it yet, just return the suggestion
        suggested_schema.source_name = request.source_name
        return suggested_schema
    except Exception as e:
        log.error(f"Schema detection failed: {e}")
        raise HTTPException(status_code=500, detail="An internal error occurred during schema detection.")

@router.post("/", response_model=LogSchema)
async def create_or_update_schema(
    schema: LogSchema,
    service: AnomalyDetectionService = Depends(get_anomaly_service)
):
    """
    Saves or updates a parsing schema for a given data source.
    """
    try:
        saved_schema = service.save_schema(schema)
        return saved_schema
    except Exception as e:
        log.error(f"Failed to save schema for '{schema.source_name}': {e}")
        raise HTTPException(status_code=500, detail="Failed to save schema.")

@router.get("/{source_name}", response_model=LogSchema)
async def get_schema(
    source_name: str,
    service: AnomalyDetectionService = Depends(get_anomaly_service)
):
    """
    Retrieves the saved parsing schema for a given data source.
    """
    schema = service.get_schema(source_name)
    if not schema:
        raise HTTPException(status_code=404, detail=f"Schema for source '{source_name}' not found.")
    return schema