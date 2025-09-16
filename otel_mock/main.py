# In file: otel_mock/main.py

import asyncio
import logging
import os
import random
import time
from contextlib import asynccontextmanager
from typing import Dict, Any, AsyncGenerator

import httpx
from fastapi import FastAPI
from dotenv import load_dotenv

from generate_logs import ServiceSimulator

# --- Configuration ---
load_dotenv()
INGESTOR_URL = os.getenv("INGESTOR_URL", "http://localhost:8000/api/v1/ingest/stream")
LOGS_PER_SECOND = int(os.getenv("LOGS_PER_SECOND", 100)) # Increased for more rapid testing
MAX_BATCH_SIZE = int(os.getenv("MAX_BATCH_SIZE", 100))
MAX_BATCH_INTERVAL_SEC = float(os.getenv("MAX_BATCH_INTERVAL_SEC", 0.5))

# --- Anomaly Injection Probabilities ---
# AFTER: Anomalies are now ~10x more frequent for demo purposes.
NOVEL_ANOMALY_PROB = 0.002         # ~1 in 500 logs
FREQUENCY_SPIKE_PROB = 0.01          # ~1 in 100 logs
STACK_TRACE_PROB = 0.005          # ~1 in 200 logs     
LATENCY_ANOMALY_PROB = 0.02        

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("otel_mock")


async def log_generator() -> AsyncGenerator[Dict[str, Any], None]:
    """
    Runs a continuous, probabilistic simulation to randomly inject a variety
    of anomalies into a high-throughput log stream.
    """
    simulator = ServiceSimulator()
    log.info(f"--- Starting randomized anomaly firehose. ---")

    while True:
        # Control the overall log rate
        await asyncio.sleep(1.0 / LOGS_PER_SECOND)
        
        trace_id = f"{int(time.time()*1e6):x}"
        span_id = f"{int(time.time()*1e6):x}"
        
        p = random.random()

        # --- Use probabilities to decide which type of log to generate ---
        if p < NOVEL_ANOMALY_PROB:
            log.warning(">>> Injecting NOVEL ANOMALY...")
            log_record = simulator.generate_novel_error_log(trace_id, span_id)
        
        elif p < NOVEL_ANOMALY_PROB + STACK_TRACE_PROB:
            log.warning(">>> Injecting STACK TRACE ANOMALY...")
            log_record = simulator.generate_stack_trace_log(trace_id, span_id)

        elif p < NOVEL_ANOMALY_PROB + STACK_TRACE_PROB + FREQUENCY_SPIKE_PROB:
            log.warning(">>> Injecting FREQUENCY SPIKE ANOMALY (503 Error)...")
            log_record = simulator.generate_frequency_spike_log(trace_id, span_id)
            
        else:
            # For normal logs, separately decide if they should show high latency
            is_degraded = random.random() < LATENCY_ANOMALY_PROB
            if is_degraded:
                log.info("... injecting high latency into normal log ...")
            log_record = simulator.generate_normal_log(trace_id, span_id, is_degraded=is_degraded)
        
        yield log_record


async def stream_logs(client: httpx.AsyncClient):
    """Gathers logs from the generator and sends them in dynamic batches."""
    log.info(f"Starting dynamic log stream to '{INGESTOR_URL}'")
    batch = []
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
                log.info(f"Sent batch of {len(batch)} logs to VIA.")
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
    title="VIA - OTel Chaos Streamer",
    description="A high-throughput log firehose that randomly injects novel, frequency, and latency anomalies for real-time testing.",
    lifespan=lifespan
)

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "streaming_to": INGESTOR_URL,
        "simulation_mode": "Randomized Chaos Injection"
    }