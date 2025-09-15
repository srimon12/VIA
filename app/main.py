# file: app/main.py
# Action: Replace the entire file content with this.

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.api.v1.router import api_router
from app.services.qdrant_service import QdrantService
from app.db.registry import initialize_registry

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("api")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """On startup, initialize DB and Qdrant collections."""
    log.info("Application startup...")
    # Initialize SQLite DB for schemas and patches
    initialize_registry()
    
    # Initialize Qdrant collections via the service
    qdrant_service = QdrantService()
    qdrant_service.setup_collections()
    
    yield
    log.info("Application shutdown.")

app = FastAPI(
    title="Vector Incident Atlas (VIA)",
    description="An intelligent, two-tiered log anomaly detection and triage system.",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(api_router, prefix="/api/v1")

@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok"}