# file: app/main.py
import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.api.v1.router import api_router
from app.db.registry import initialize_registry
from app.services.qdrant_service import QdrantService
from app.services.ingestion_service import IngestionService
from app.services.control_service import ControlService
from app.services.schema_service import SchemaService
from app.services.promotion_service import PromotionService
from app.services.rhythm_analysis_service import RhythmAnalysisService
from app.services.forensic_analysis_service import ForensicAnalysisService
from app.worker import run_rhythm_analysis_periodically

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("api")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """On startup, initialize services and launch the background worker."""
    log.info("Application startup...")
    initialize_registry()
    
    # Create service singletons
    qdrant_service = QdrantService()
    control_service = ControlService()
    promotion_service = PromotionService(qdrant_service)
    
    await qdrant_service.setup_collections()

    # Make services available via app state
    app.state.qdrant_service = qdrant_service
    app.state.control_service = control_service
    app.state.promotion_service = promotion_service
    app.state.ingestion_service = IngestionService(qdrant_service)
    app.state.rhythm_analysis_service = RhythmAnalysisService(qdrant_service, control_service, promotion_service)
    app.state.forensic_analysis_service = ForensicAnalysisService(qdrant_service, control_service)
    app.state.schema_service = SchemaService()
    
    # --- Start the automated background worker ---
    worker_task = asyncio.create_task(run_rhythm_analysis_periodically(app))
    app.state.worker_task = worker_task
    
    yield
    
    log.info("Application shutdown...")
    # --- Gracefully shut down the worker ---
    log.info("Cancelling background worker...")
    app.state.worker_task.cancel()
    try:
        await app.state.worker_task
    except asyncio.CancelledError:
        log.info("Background worker cancelled successfully.")

app = FastAPI(
    title="VeriStamp Incident Atlas (VIA)",
    description="A real-time, two-tiered log anomaly detection and triage system showcasing advanced Qdrant features.",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(api_router, prefix="/api/v1")

@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok"}