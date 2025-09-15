# file: app/api/v1/endpoints/analysis.py

from fastapi import APIRouter, Depends
from typing import List, Dict, Any, Optional

from app.schemas.models import RhythmQuery, AnomalyQuery, TriageQuery
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
    # The service now returns a dictionary with both anomaly types
    anomalies_result = await analysis_service.find_rhythm_anomalies(query.window_sec)
    return {
        "novel_anomalies_found": len(anomalies_result["novel_anomalies"]),
        "frequency_anomalies_found": len(anomalies_result["frequency_anomalies"]),
        "promoted_events": anomalies_result # Return the full dict
    }

@router.post("/tier2/anomalies", tags=["Tier 2 Analysis"])
async def find_tier2_anomalies(
    query: AnomalyQuery,  # <-- Correctly use the Pydantic model
    analysis_service: AnalysisService = Depends(get_analysis_service)
):
    """
    Performs a federated search on Tier 2 for event clusters, supporting
    a time window and an optional full-text filter for hybrid search.
    """
    # Correctly call the service method with unpacked query parameters
    results = await analysis_service.find_tier2_anomalies(
        start_ts=query.start_ts,
        end_ts=query.end_ts,
        text_filter=query.text_filter
    )
    return {"event_clusters": results}
# --- NEW: Fully Implemented /tier2/similar Endpoint ---
@router.post("/tier2/clusters", tags=["Tier 2 Analysis"])
async def find_tier2_clusters(
    query: AnomalyQuery,
    analysis_service: AnalysisService = Depends(get_analysis_service)
):
    """
    Groups events in Tier 2 into unique incident clusters based on their
    rhythm_hash. Provides a de-duplicated view of anomalies.
    """
    clusters = await analysis_service.find_tier2_clusters(
        start_ts=query.start_ts,
        end_ts=query.end_ts,
        text_filter=query.text_filter
    )
    return {"incident_clusters": clusters}
@router.post("/tier2/triage", tags=["Tier 2 Analysis"])
async def triage_similar_events(
    query: TriageQuery,
    analysis_service: AnalysisService = Depends(get_analysis_service)
):
    """
    Performs an advanced triage search using positive and negative
    example event IDs to find similar events.
    """
    results = await analysis_service.triage_similar_events(
        positive_ids=query.positive_ids,
        negative_ids=query.negative_ids,
        start_ts=query.start_ts,
        end_ts=query.end_ts
    )
    return {"triage_results": results}