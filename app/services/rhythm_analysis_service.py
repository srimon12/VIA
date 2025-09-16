# file: app/services/rhythm_analysis_service.py
import logging
import time
from collections import Counter
from typing import Any, Dict, List

from qdrant_client import models
from app.core.config import settings
from app.services.control_service import ControlService
from app.services.qdrant_service import QdrantService
from app.services.promotion_service import PromotionService

log = logging.getLogger("api.services.rhythm_analysis")

# --- Constants for better readability and tuning ---
HISTORICAL_SAMPLE_SIZE = 10_000
FREQUENCY_THRESHOLD_COUNT = 5
FREQUENCY_THRESHOLD_FACTOR = 5.0

class RhythmAnalysisService:
    def __init__(
        self,
        qdrant_service: QdrantService,
        control_service: ControlService,
        promotion_service: PromotionService,
    ) -> None:
        self.qdrant_service = qdrant_service
        self.control_service = control_service
        self.promotion_service = promotion_service

    async def find_rhythm_anomalies(self, window_sec: int) -> Dict[str, List[Dict[str, Any]]]:
        now = int(time.time())
        current_window_start = now - window_sec

        # 1. Fetch points from the current analysis window. This is correct.
        recent_points = await self.qdrant_service.get_points_from_tier1(current_window_start, now)
        if not recent_points:
            return {"novel_anomalies": [], "frequency_anomalies": []}

        # 2. Fetch historical points for baseline. This logic is also sound.
        hist_sample_points = await self.qdrant_service.get_historical_baseline(current_window_start)

        recent_hashes = [p.payload["rhythm_hash"] for p in recent_points]
        known_hashes = {p.payload["rhythm_hash"] for p in hist_sample_points}
        recent_counts = Counter(recent_hashes)
        by_hash = {p.payload["rhythm_hash"]: p.payload for p in recent_points}

        novel_anomalies = []

        for r_hash, r_count in recent_counts.items():
            if self.control_service.is_suppressed_or_patched(r_hash):
                continue  
            
            payload = dict(by_hash[r_hash])
            
            if r_hash not in known_hashes:
                payload["anomaly_type"] = "novelty"
                novel_anomalies.append(payload)
            else:
                pass
        if novel_anomalies:
            await self.promotion_service.promote_anomalies(novel_anomalies)

        return {"novel_anomalies": novel_anomalies, "frequency_anomalies": []}