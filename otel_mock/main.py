# In file: otel_mock/main.py

import asyncio
import logging
import os
import random
import time
from contextlib import asynccontextmanager
from typing import List, Dict, Any, AsyncGenerator

import httpx
from fastapi import FastAPI
from dotenv import load_dotenv

# We directly import and use the high-quality simulator you built
from generate_logs import ServiceSimulator

# --- Configuration ---
load_dotenv()
INGESTOR_URL = os.getenv("INGESTOR_URL", "http://localhost:8000/api/v1/ingest/stream")
LOGS_PER_SECOND = int(os.getenv("LOGS_PER_SECOND", 50))
MAX_BATCH_SIZE = int(os.getenv("MAX_BATCH_SIZE", 100))
MAX_BATCH_INTERVAL_SEC = float(os.getenv("MAX_BATCH_INTERVAL_SEC", 1.0))

# --- Anomaly Windows (from generate_logs.py) ---
# This defines the "script" for our live, looping simulation.
LATENCY_ANOMALY_WINDOW = (120, 140)  # 2m0s - 2m20s into the cycle
FREQUENCY_ANOMALY_WINDOW = (240, 260)  # 4m0s - 4m20s into the cycle
NOVEL_ERROR_WINDOW = (360, 362)      # 6m0s - 6m2s into the cycle
STACK_TRACE_WINDOW = (480, 482)      # 8m0s - 8m2s into the cycle
SIMULATION_CYCLE_SEC = 600           # The entire simulation repeats every 10 minutes

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("otel_mock")


async def log_generator() -> AsyncGenerator[Dict[str, Any], None]:
    """
    Runs a continuous, looping simulation using the sophisticated ServiceSimulator
    to generate high-quality logs and timed anomalies on the fly.
    """
    simulator = ServiceSimulator()
    start_time = time.time()
    log.info(f"--- Starting new 10-minute live simulation cycle. ---")

    while True:
        await asyncio.sleep(1.0 / LOGS_PER_SECOND)
        
        # --- Live Simulation Time Logic ---
        time_since_start = time.time() - start_time
        if time_since_start > SIMULATION_CYCLE_SEC:
            log.warning("--- Simulation cycle complete. Resetting for a new 10-minute demo loop. ---")
            start_time = time.time()
            time_since_start = 0.0

        trace_id = f"{int(time.time()*1e6):x}"
        span_id = f"{int(time.time()*1e6):x}"
        
        # --- Ported Anomaly Injection Logic from generate_logs.py ---
        # This uses your high-quality, timed anomaly script live.
        in_latency_window = LATENCY_ANOMALY_WINDOW[0] <= time_since_start < LATENCY_ANOMALY_WINDOW[1]
        in_frequency_window = FREQUENCY_ANOMALY_WINDOW[0] <= time_since_start < FREQUENCY_ANOMALY_WINDOW[1]
        in_novel_window = NOVEL_ERROR_WINDOW[0] <= time_since_start < NOVEL_ERROR_WINDOW[1]
        in_stack_window = STACK_TRACE_WINDOW[0] <= time_since_start < STACK_TRACE_WINDOW[1]

        # Every log is generated live with a current timestamp by the simulator
        if in_novel_window:
            log_record = simulator.generate_novel_error_log(trace_id, span_id)
        elif in_stack_window:
            log_record = simulator.generate_stack_trace_log(trace_id, span_id)
        elif in_frequency_window:
            log_record = simulator.generate_frequency_spike_log(trace_id, span_id)
        else:
            is_degraded = in_latency_window
            log_record = simulator.generate_normal_log(trace_id, span_id, is_degraded=is_degraded)
        
        yield log_record


async def stream_logs(client: httpx.AsyncClient):
    """Gathers logs from the generator and sends them in dynamic batches."""
    log.info(f"Starting dynamic log stream to '{INGESTOR_URL}'")
    batch: List[Dict[str, Any]] = []
    last_send_time = time.time()
    async for log_record in log_generator():
        batch.append(log_record)
        time_since_last_send = time.time() - last_send_time
        if len(batch) >= MAX_BATCH_SIZE or time_since_last_send >= MAX_BATCH_INTERVAL_SEC:
            if not batch: continue
            try:
                response = await client.post(INGESTOR_URL, json=batch)
                if 400 <= response.status_code < 600:
                    log.error(f"Ingestor returned an error! Status: {response.status_code}, Response: {response.text[:200]}")
            except httpx.RequestError as e:
                log.error(f"Failed to stream logs to ingestor: {e}")
            finally:
                batch = []
                last_send_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manages the startup and shutdown of the log streaming task."""
    client = httpx.AsyncClient(timeout=10.0)
    task = asyncio.create_task(stream_logs(client))
    yield
    task.cancel()
    try: await task
    except asyncio.CancelledError: log.info("Log streaming task cancelled successfully.")
    await client.aclose()
    log.info("Log streaming task shut down gracefully.")


app = FastAPI(
    title="VIA - OTel Live Simulation Streamer",
    description="A sophisticated, live log firehose that runs a continuous, looping 10-minute simulation with timed anomalies.",
    lifespan=lifespan
)

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "streaming_to": INGESTOR_URL,
        "simulation_mode": "Live Timed Anomaly Injection",
        "cycle_length_sec": SIMULATION_CYCLE_SEC
    }