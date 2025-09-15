# file: app/api/v1/endpoints/control.py
# Action: Create this new file.

from fastapi import APIRouter, Depends

from app.schemas.models import SuppressRequest, PatchRequest
from app.services.control_service import ControlService

router = APIRouter()

@router.post("/suppress")
async def suppress_rhythm_anomaly(
    request: SuppressRequest,
    control_service: ControlService = Depends()
):
    control_service.suppress_anomaly(request.rhythm_hash, request.duration_sec)
    return {"status": "ok", "message": f"Hash {request.rhythm_hash} suppressed."}

@router.post("/patch")
async def patch_rhythm_anomaly(
    request: PatchRequest,
    control_service: ControlService = Depends()
):
    # The context logs would be used to generate an eval, for now we just patch
    reason = f"Patched by user via API"
    control_service.patch_anomaly(request.rhythm_hash, reason)
    return {"status": "ok", "message": f"Hash {request.rhythm_hash} patched."}