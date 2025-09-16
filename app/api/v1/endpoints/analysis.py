from fastapi import APIRouter, Depends, Request
from app.schemas.models import RhythmQuery, AnomalyQuery, TriageQuery
from app.services.analysis_service import AnalysisService

router = APIRouter()

def get_analysis_service(req: Request) -> AnalysisService:
    return req.app.state.analysis_service

@router.post("/tier1/rhythm_anomalies")
async def get_rhythm_anomalies(
    query: RhythmQuery,
    analysis_service: AnalysisService = Depends(get_analysis_service),
):
    anomalies_result = await analysis_service.find_rhythm_anomalies(query.window_sec)
    return {
        "novel_anomalies": anomalies_result["novel_anomalies"],
        "frequency_anomalies": anomalies_result["frequency_anomalies"],
    }

@router.post("/tier2/clusters")
async def find_tier2_clusters(
    query: AnomalyQuery,
    analysis_service: AnalysisService = Depends(get_analysis_service),
):
    clusters = await analysis_service.find_tier2_clusters(
        start_ts=query.start_ts, end_ts=query.end_ts, text_filter=query.text_filter
    )
    return {"clusters": clusters}

@router.post("/tier2/triage")
async def triage_similar_events(
    query: TriageQuery,
    analysis_service: AnalysisService = Depends(get_analysis_service),
):
    results = await analysis_service.triage_similar_events(
        positive_ids=query.positive_ids,
        negative_ids=query.negative_ids,
        start_ts=query.start_ts,
        end_ts=query.end_ts,
    )
    return {"triage_results": results}
