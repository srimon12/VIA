# file: otel_mock/main.py
import asyncio
import logging
import os
import random
import time
import json
from contextlib import asynccontextmanager
from typing import List, Dict, Any, AsyncGenerator

import httpx
from fastapi import FastAPI
from dotenv import load_dotenv

from generate_logs import ServiceSimulator # We'll use the generator directly

# --- Configuration ---
load_dotenv()
INGESTOR_URL = os.getenv("INGESTOR_URL", "http://localhost:8000/api/v1/ingest/stream")
LOGS_PER_SECOND = int(os.getenv("LOGS_PER_SECOND", 50))
MAX_BATCH_SIZE = int(os.getenv("MAX_BATCH_SIZE", 100))
MAX_BATCH_INTERVAL_SEC = float(os.getenv("MAX_BATCH_INTERVAL_SEC", 1.0))
ERROR_INJECTION_RATE = float(os.getenv("ERROR_INJECTION_RATE", 0.001)) # Inject 1 error per 1000 logs

# --- Production-minded logging ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("otel_mock")


async def log_generator() -> AsyncGenerator[Dict[str, Any], None]:
    """An asynchronous generator that yields simulated log records indefinitely."""
    simulator = ServiceSimulator()
    while True:
        trace_id = f"{int(time.time()*1e6):x}" # Simple hex timestamp trace_id
        span_id = f"{random.randint(0, 2**64-1):x}"
        
        # --- Simulate real-time jitter ---
        # Sleep for a duration that averages to our target LOGS_PER_SECOND
        await asyncio.sleep(1.0 / LOGS_PER_SECOND * (0.5 + random.random()))
        
        # --- Occasionally inject malformed data ---
        if random.random() < ERROR_INJECTION_RATE:
            yield {"malformed_data": "this is not a valid OTel log"}
            continue

        log_record = simulator.generate_normal_log(trace_id, span_id)
        yield log_record


async def stream_logs(client: httpx.AsyncClient):
    """
    Gathers logs from the generator and sends them in dynamic batches.
    A batch is sent when it reaches MAX_BATCH_SIZE or when MAX_BATCH_INTERVAL_SEC has passed.
    """
    log.info(f"Starting dynamic log stream to '{INGESTOR_URL}'")
    batch: List[Dict[str, Any]] = []
    last_send_time = time.time()

    async for log_record in log_generator():
        batch.append(log_record)
        
        time_since_last_send = time.time() - last_send_time
        
        # Check if we should send the batch
        if len(batch) >= MAX_BATCH_SIZE or time_since_last_send >= MAX_BATCH_INTERVAL_SEC:
            if not batch:
                continue

            try:
                response = await client.post(INGESTOR_URL, json=batch)
                
                # Check for client-side (4xx) or server-side (5xx) errors
                if 400 <= response.status_code < 600:
                    log.error(f"Ingestor returned an error! Status: {response.status_code}, Response: {response.text[:200]}")
                else:
                    log.info(f"Successfully streamed {len(batch)} log records.")
            
            except httpx.RequestError as e:
                log.error(f"Failed to stream logs to ingestor: {e}")
            
            finally:
                # Reset the batch and timer regardless of success or failure
                batch = []
                last_send_time = time.time()

# --- FastAPI Application with Lifespan Management ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # On startup, create the HTTP client and start the background streaming task
    client = httpx.AsyncClient(timeout=10.0)
    task = asyncio.create_task(stream_logs(client))
    yield
    # On shutdown, cancel the task and close the client
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        log.info("Log streaming task cancelled successfully.")
    await client.aclose()
    log.info("Log streaming task shut down gracefully.")


app = FastAPI(
    title="VIA - OTel Mock Streamer",
    description="A realistic, asynchronous log firehose for testing the VIA ingestion pipeline.",
    lifespan=lifespan
)

@app.get("/health")
async def health():
    return {
        "status": "ok", 
        "streaming_to": INGESTOR_URL,
        "config": {
            "logs_per_second_target": LOGS_PER_SECOND,
            "max_batch_size": MAX_BATCH_SIZE,
            "max_batch_interval_sec": MAX_BATCH_INTERVAL_SEC
        }
    }