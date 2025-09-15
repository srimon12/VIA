# file: app/api/v1/router.py
# Action: Replace file content.

from fastapi import APIRouter
from app.api.v1.endpoints import ingest, analysis, schema, control

api_router = APIRouter()
api_router.include_router(ingest.router, prefix="/ingest", tags=["Ingestion"])
api_router.include_router(analysis.router, prefix="/analysis", tags=["Analysis"])
api_router.include_router(schema.router, prefix="/schemas", tags=["Schema Management"])
api_router.include_router(control.router, prefix="/control", tags=["Control Loop"])