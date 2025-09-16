# file: app/main.py
# Action: Replace the entire file content with this.

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.api.v1.router import api_router
from app.db.registry import initialize_registry
# Import all services to create singletons
from app.services.qdrant_service import QdrantService
from app.services.ingestion_service import IngestionService
from app.services.analysis_service import AnalysisService
from app.services.control_service import ControlService
from app.services.schema_service import SchemaService

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("api")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """On startup, initialize DB, Qdrant collections, and service singletons."""
    log.info("Application startup...")
    # Initialize SQLite DB for schemas and patches
    initialize_registry()
    
    # Create service singletons
    qdrant_service = QdrantService()
    control_service = ControlService()
    
    # Initialize dependencies that need setup on startup
    await qdrant_service.setup_collections()

    # Make services available via app state for dependency injection
    app.state.qdrant_service = qdrant_service
    app.state.control_service = control_service
    app.state.ingestion_service = IngestionService(qdrant_service)
    app.state.analysis_service = AnalysisService(qdrant_service, control_service)
    app.state.schema_service = SchemaService()
    
    yield
    log.info("Application shutdown.")

app = FastAPI(
    title="Vector Incident Atlas (VIA)",
    description="A real-time, two-tiered log anomaly detection and triage system showcasing advanced Qdrant features.",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(api_router, prefix="/api/v1")

@app.get("/health", tags=["Health"])
def health_check():
    """Basic health check endpoint."""
    return {"status": "ok"}

# --- Dependency Injection Overrides ---
# This allows FastAPI's `Depends()` to find our singleton services

def get_ingestion_service() -> IngestionService: return app.state.ingestion_service
def get_analysis_service() -> AnalysisService: return app.state.analysis_service
def get_control_service() -> ControlService: return app.state.control_service
def get_schema_service() -> SchemaService: return app.state.schema_service

app.dependency_overrides[IngestionService] = get_ingestion_service
app.dependency_overrides[AnalysisService] = get_analysis_service
app.dependency_overrides[ControlService] = get_control_service
app.dependency_overrides[SchemaService] = get_schema_service