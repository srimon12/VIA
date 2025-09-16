# file: app/api/v1/endpoints/analysis.py
from fastapi import APIRouter, Depends, Request
from app.schemas.models import RhythmQuery, AnomalyQuery, TriageQuery
from app.services.rhythm_analysis_service import RhythmAnalysisService
from app.services.forensic_analysis_service import ForensicAnalysisService
from typing import Any, Dict

router = APIRouter()

# --- FIX: Define explicit getters to resolve dependencies reliably ---
def get_rhythm_service(req: Request) -> RhythmAnalysisService:
    return req.app.state.rhythm_analysis_service

def get_forensic_service(req: Request) -> ForensicAnalysisService:
    return req.app.state.forensic_analysis_service

@router.post("/tier1/rhythm_anomalies")
async def get_rhythm_anomalies(
    query: RhythmQuery,
    rhythm_service: RhythmAnalysisService = Depends(get_rhythm_service), # FIX: Use explicit getter
) -> Dict[str, Any]:
    """Manual endpoint for debugging Tier 1. The primary detection is now done by the background worker."""
    anomalies_result = await rhythm_service.find_rhythm_anomalies(query.window_sec)
    return {
        "novel_anomalies": anomalies_result.get("novel_anomalies", []),
        "frequency_anomalies": anomalies_result.get("frequency_anomalies", []),
    }

@router.post("/tier2/clusters")
async def find_tier2_clusters(
    query: AnomalyQuery, 
    forensic_service: ForensicAnalysisService = Depends(get_forensic_service) # FIX: Use explicit getter
) -> Dict[str, Any]:
    clusters = await forensic_service.find_tier2_clusters(
        start_ts=query.start_ts, end_ts=query.end_ts, text_filter=query.text_filter
    )
    return {"clusters": clusters}

@router.post("/tier2/triage")
async def triage_similar_events(
    query: TriageQuery, 
    forensic_service: ForensicAnalysisService = Depends(get_forensic_service) # FIX: Use explicit getter
) -> Dict[str, Any]:
    results = await forensic_service.triage_similar_events(
        positive_ids=query.positive_ids,
        negative_ids=query.negative_ids,
        start_ts=query.start_ts,
        end_ts=query.end_ts,
    )
    return {"triage_results": results}