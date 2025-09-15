# file: app/api/v1/endpoints/analysis.py
# Action: Replace the entire file with this final version.

from fastapi import APIRouter, Depends
from typing import List

from app.schemas.models import RhythmQuery, AnomalyQuery, SimilarQuery # --- MODIFIED ---
from app.services.analysis_service import AnalysisService
from app.services.qdrant_service import QdrantService
from app.services.control_service import ControlService

router = APIRouter()

# --- Dependency Injection ---
def get_qdrant_service(): return QdrantService()
def get_control_service(): return ControlService()

def get_analysis_service(
    qdrant_service: QdrantService = Depends(get_qdrant_service),
    control_service: ControlService = Depends(get_control_service)
):
    return AnalysisService(qdrant_service, control_service)

# --- API Endpoints ---
@router.post("/tier1/rhythm_anomalies", tags=["Tier 1 Analysis"])
async def get_rhythm_anomalies(
    query: RhythmQuery,
    analysis_service: AnalysisService = Depends(get_analysis_service)
):
    anomalies = await analysis_service.find_rhythm_anomalies(query.window_sec)
    return {"novel_anomalies_found": len(anomalies), "promoted_events": anomalies}

@router.post("/tier2/anomalies", tags=["Tier 2 Analysis"])
async def get_tier2_anomalies(
    query: AnomalyQuery,
    analysis_service: AnalysisService = Depends(get_analysis_service)
):
    clusters = await analysis_service.find_tier2_anomalies(query.start_ts, query.end_ts)
    return {"event_clusters": clusters}

# --- NEW: Fully Implemented /tier2/similar Endpoint ---
@router.post("/tier2/similar", tags=["Tier 2 Analysis"])
async def get_tier2_similar(
    query: SimilarQuery,
    analysis_service: AnalysisService = Depends(get_analysis_service)
):
    """
    Finds similar past event clusters from Tier 2, grouped by service,
    querying across multiple daily collections.
    """
    similar_groups = await analysis_service.find_tier2_similar(
        positive_ids=query.positive_ids,
        start_ts=query.start_ts,
        end_ts=query.end_ts
    )
    return {"similar_groups": similar_groups}