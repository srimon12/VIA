# file: app/api/v1/endpoints/control.py
from fastapi import APIRouter, Depends, Request
from app.schemas.models import SuppressRequest, PatchRequest
from app.services.control_service import ControlService
from typing import Any, Dict

router = APIRouter()

# --- Add this getter function ---
def get_control_service(req: Request) -> ControlService:
    return req.app.state.control_service

@router.post("/suppress")
async def suppress_rhythm_anomaly(
    request: SuppressRequest,
    control_service: ControlService = Depends(get_control_service), # Use the getter
) -> Dict[str, Any]:
    control_service.suppress_anomaly(request.rhythm_hash, request.duration_sec)
    return {"status": "ok", "message": f"Hash {request.rhythm_hash} suppressed."}

@router.post("/patch")
async def patch_rhythm_anomaly(
    request: PatchRequest,
    control_service: ControlService = Depends(get_control_service), # Use the getter
) -> Dict[str, Any]:
    control_service.patch_anomaly(
        rhythm_hash=request.rhythm_hash,
        reason="Patched by user via API",
        context_logs=request.context_logs,
    )
    return {"status": "ok", "message": f"Hash {request.rhythm_hash} patched and eval case generated."}
@router.get("/rules")
async def get_all_active_rules(
    control_service: ControlService = Depends(get_control_service),
) -> Dict[str, Any]:
    return control_service.get_all_rules()

@router.delete("/patch/{rhythm_hash}")
async def delete_patch_rule(
    rhythm_hash: str,
    control_service: ControlService = Depends(get_control_service),
) -> Dict[str, Any]:
    control_service.delete_patch(rhythm_hash)
    return {"status": "ok", "message": f"Patch for {rhythm_hash} has been deactivated."}

@router.delete("/suppress/{rhythm_hash}")
async def delete_suppression_rule(
    rhythm_hash: str,
    control_service: ControlService = Depends(get_control_service),
) -> Dict[str, Any]:
    control_service.delete_suppression(rhythm_hash)
    return {"status": "ok", "message": f"Suppression for {rhythm_hash} has been removed."}