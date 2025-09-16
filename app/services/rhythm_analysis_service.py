# file: app/services/rhythm_analysis_service.py
import logging
import time
from collections import Counter
from typing import Any, Dict, List
import statistics

from qdrant_client import models
from app.services.control_service import ControlService
from app.services.qdrant_service import QdrantService
from app.services.promotion_service import PromotionService

log = logging.getLogger("api.services.rhythm_analysis")

# --- Constants for Production-Grade Tuning ---
HISTORICAL_SAMPLE_SIZE = 10_000
NOVELTY_MIN_COUNT = 2
FREQUENCY_MIN_COUNT = 3
FREQUENCY_STD_DEV_FACTOR = 2.5 # A more sensitive factor for a better baseline

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

    def _calculate_historical_stats(self, points: List[models.Record], current_window_sec: int) -> Dict[str, Dict[str, float]]:
        """
        Calculates historical mean and standard deviation, NORMALIZED to the
        duration of the current analysis window for a fair comparison.
        """
        if not points or len(points) < 2:
            return {}
        
        # 1. Determine the actual time duration of the historical sample.
        # Points are ordered newest to oldest, so points[0] is newest.
        newest_ts = points[0].payload['ts']
        oldest_ts = points[-1].payload['ts']
        historical_duration_sec = max(1, newest_ts - oldest_ts)

        # 2. Calculate a scaling factor to make the time windows comparable.
        # This is the core of the "real-world" approach.
        scaling_factor = current_window_sec / historical_duration_sec

        stats = {}
        counts = Counter(p.payload["rhythm_hash"] for p in points)
        
        for r_hash, total_count in counts.items():
            # 3. Normalize the historical count to the current window's duration.
            normalized_mean = total_count * scaling_factor
            
            # 4. Use a robust standard deviation. For low-frequency events, a simple
            # sqrt(mean) is unstable. We set a floor to prevent over-sensitivity.
            # This handles sparse, real-world data much more gracefully.
            std_dev = max(1.5, normalized_mean ** 0.5)
            
            stats[r_hash] = {"mean": normalized_mean, "std_dev": std_dev}
            
        return stats

    async def find_rhythm_anomalies(self, window_sec: int) -> Dict[str, List[Dict[str, Any]]]:
        now = int(time.time())
        current_window_start = now - window_sec

        recent_points = await self.qdrant_service.get_points_from_tier1(current_window_start, now)
        if not recent_points:
            return {"novel_anomalies": [], "frequency_anomalies": []}

        hist_sample_points = await self.qdrant_service.get_historical_baseline(current_window_start, HISTORICAL_SAMPLE_SIZE)
        
        historical_stats = self._calculate_historical_stats(hist_sample_points, window_sec)
        known_hashes = set(historical_stats.keys())
        
        recent_counts = Counter(p.payload["rhythm_hash"] for p in recent_points)
        by_hash = {p.payload["rhythm_hash"]: p.payload for p in recent_points}

        novel_anomalies = []
        frequency_anomalies = []

        for r_hash, r_count in recent_counts.items():
            if self.control_service.is_suppressed_or_patched(r_hash):
                continue
            
            payload = dict(by_hash[r_hash])

            if r_hash not in known_hashes:
                if r_count >= NOVELTY_MIN_COUNT:
                    payload["anomaly_type"] = "novelty"
                    payload["anomaly_context"] = f"New pattern seen {r_count} times."
                    novel_anomalies.append(payload)
            else:
                stats = historical_stats[r_hash]
                threshold = stats["mean"] + (stats["std_dev"] * FREQUENCY_STD_DEV_FACTOR)
                
                if r_count > threshold and r_count >= FREQUENCY_MIN_COUNT:
                    payload["anomaly_type"] = "frequency"
                    payload["anomaly_context"] = f"Count {r_count} breached threshold of {threshold:.1f} (normalized μ={stats['mean']:.1f}, σ={stats['std_dev']:.1f})"
                    frequency_anomalies.append(payload)
        
        all_anomalies = novel_anomalies + frequency_anomalies
        if all_anomalies:
            await self.promotion_service.promote_anomalies(all_anomalies)

        return {"novel_anomalies": novel_anomalies, "frequency_anomalies": frequency_anomalies}