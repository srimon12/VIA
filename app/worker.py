# file: app/worker.py
import asyncio
import logging
from fastapi import FastAPI

log = logging.getLogger("api.worker")

async def run_rhythm_analysis_periodically(app: FastAPI):
    """
    Runs the Tier-1 rhythm analysis in a continuous loop.
    This acts as the system's automated "Radar".
    """
    ANALYSIS_INTERVAL_SEC = 60
    
    log.info(f"Starting background worker. Analysis will run every {ANALYSIS_INTERVAL_SEC} seconds.")
    rhythm_service = app.state.rhythm_analysis_service
    
    while True:
        try:
            log.info(f"Worker: Analyzing last {ANALYSIS_INTERVAL_SEC} seconds of data...")
            # Analyze a clean, non-overlapping window of data.
            anomalies = await rhythm_service.find_rhythm_anomalies(window_sec=ANALYSIS_INTERVAL_SEC)
            
            novel_count = len(anomalies.get("novel_anomalies", []))
            freq_count = len(anomalies.get("frequency_anomalies", []))
            
            if novel_count > 0 or freq_count > 0:
                log.warning(f"Worker: Found {novel_count} novel and {freq_count} frequency anomalies. Promotion to Tier-2 is automatic.")
            else:
                log.info("Worker: No new anomalies detected in this window.")

        except Exception as e:
            log.error(f"Worker: An error occurred during periodic analysis: {e}", exc_info=True)
        
        # Wait for the next interval.
        await asyncio.sleep(ANALYSIS_INTERVAL_SEC)