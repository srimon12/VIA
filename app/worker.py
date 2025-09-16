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
    log.info("Starting background worker for continuous rhythm analysis...")
    rhythm_service = app.state.rhythm_analysis_service
    
    while True:
        try:
            log.info("Worker: Running periodic Tier-1 analysis...")
            # Analyze the last 5 minutes of data
            anomalies = await rhythm_service.find_rhythm_anomalies(window_sec=100)
            novel_count = len(anomalies.get("novel_anomalies", []))
            freq_count = len(anomalies.get("frequency_anomalies", []))
            
            if novel_count > 0 or freq_count > 0:
                log.warning(f"Worker: Found {novel_count} novel and {freq_count} frequency anomalies. Promotion to Tier-2 is automatic.")
            else:
                log.info("Worker: No new anomalies detected in this window.")

        except Exception as e:
            log.error(f"Worker: An error occurred during periodic analysis: {e}", exc_info=True)
        
        # Wait for 60 seconds before the next run
        await asyncio.sleep(60)