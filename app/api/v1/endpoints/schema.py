# file: app/api/v1/endpoints/schema.py
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from app.schemas.models import DetectSchemaRequest, LogSchema
from app.services.schema_service import SchemaService
from typing import List

router = APIRouter()
log = logging.getLogger("api.endpoints.schema")

# --- FIX: Define explicit getter to resolve dependency reliably ---
def get_schema_service(req: Request) -> SchemaService:
    return req.app.state.schema_service

@router.post("/detect", response_model=LogSchema)
async def detect_schema_endpoint(
    request: DetectSchemaRequest,
    service: SchemaService = Depends(get_schema_service), # FIX: Use explicit getter
):
    try:
        suggested_schema = service.detect_schema(request.sample_logs)
        if not suggested_schema or not suggested_schema.fields:
            raise HTTPException(status_code=400, detail="Could not detect a valid schema from the provided logs.")
        
        suggested_schema.source_name = request.source_name
        return suggested_schema
    except Exception as e:
        log.error(f"Schema detection failed: {e}")
        raise HTTPException(status_code=500, detail="An internal error occurred during schema detection.")

@router.post("/", response_model=LogSchema)
async def create_or_update_schema(
    schema: LogSchema,
    service: SchemaService = Depends(get_schema_service), # FIX: Use explicit getter
):
    try:
        saved_schema = service.save_schema(schema)
        return saved_schema
    except Exception as e:
        log.error(f"Failed to save schema for '{schema.source_name}': {e}")
        raise HTTPException(status_code=500, detail="Failed to save schema.")

@router.get("/{source_name}", response_model=LogSchema)
async def get_schema(
    source_name: str,
    service: SchemaService = Depends(get_schema_service), # FIX: Use explicit getter
):
    schema = service.get_schema(source_name)
    if not schema:
        raise HTTPException(status_code=404, detail=f"Schema for source '{source_name}' not found.")
    return schema
@router.get("/", response_model=List[str])
async def list_schemas_endpoint(
    service: SchemaService = Depends(get_schema_service),
):
    """Returns a list of all saved schema source names."""
    return service.list_schemas()