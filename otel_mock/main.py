# file: otel_mock/main.py

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import List

import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import json
from datetime import datetime

# --- Configuration ---
load_dotenv()
BGL_LOG_PATH = os.getenv("BGL_LOG_PATH", "logs/telemetry_logs.jsonl")  # Updated default to JSONL
INGESTOR_URL = os.getenv("INGESTOR_URL", "http://localhost:8000/api/v1/ingest/stream")
STREAM_INTERVAL_SEC = int(os.getenv("STREAM_INTERVAL_SEC", 2))
STREAM_BATCH_SIZE = int(os.getenv("STREAM_BATCH_SIZE", 50))

# --- Production-minded logging ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("otel_mock")

# --- OTel Pydantic Models (Simplified but Realistic) ---
class OTelLogAttribute(BaseModel):
    key: str
    value: str

class OTelLogRecord(BaseModel):
    TimeUnixNano: int = Field(default_factory=lambda: int(time.time() * 1e9))
    SeverityText: str = "INFO"
    Body: str
    Attributes: List[OTelLogAttribute] = []

def parse_json_to_otel(line: str) -> OTelLogRecord | None:
    """Parses a JSONL OTel log line into a structured OTelLogRecord."""
    try:
        data = json.loads(line.strip())
        log_rec = data["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
        ts = int(log_rec.get("timeUnixNano", int(datetime.now().timestamp() * 1e9)))
        body = log_rec["body"].get("stringValue", "") if isinstance(log_rec["body"], dict) else str(log_rec["body"])
        attrs = [
            OTelLogAttribute(key=a["key"], value=a["value"].get("stringValue", ""))
            for a in log_rec.get("attributes", [])
        ]
        return OTelLogRecord(
            TimeUnixNano=ts,
            SeverityText=log_rec.get("severityText", "INFO"),
            Body=body,
            Attributes=attrs
        )
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        log.error(f"Parse error: {e}")
        return None

# --- Background Streaming Task ---
async def stream_logs(client: httpx.AsyncClient):
    """Continuously reads from the log file and streams batches to the ingestor."""
    log.info(f"Starting log stream from '{BGL_LOG_PATH}' to '{INGESTOR_URL}'")
    
    try:
        with open(BGL_LOG_PATH, "r", encoding="utf-8") as f:
            while True:
                batch = []
                for _ in range(STREAM_BATCH_SIZE):
                    line = f.readline()
                    if not line:  # Loop back to the start if end of file is reached
                        log.info("End of log file reached, restarting stream from beginning.")
                        f.seek(0)
                        line = f.readline()
                    
                    otel_record = parse_json_to_otel(line)
                    if otel_record:
                        batch.append(otel_record.model_dump())
                
                if batch:
                    try:
                        response = await client.post(INGESTOR_URL, json=batch)
                        response.raise_for_status()
                        log.info(f"Successfully streamed {len(batch)} log records.")
                    except httpx.RequestError as e:
                        log.error(f"Failed to stream logs to ingestor: {e}")
                
                await asyncio.sleep(STREAM_INTERVAL_SEC)
    except FileNotFoundError:
        log.error(f"Log file not found at '{BGL_LOG_PATH}'. The streaming task will not run.")


# --- FastAPI Application with Lifespan Management ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # On startup, create the HTTP client and start the background streaming task
    client = httpx.AsyncClient(timeout=10.0)
    task = asyncio.create_task(stream_logs(client))
    yield
    # On shutdown, cancel the task and close the client
    task.cancel()
    await client.aclose()
    log.info("Log streaming task shut down gracefully.")


app = FastAPI(lifespan=lifespan)

@app.get("/health")
async def health():
    return {"status": "ok", "streaming_to": INGESTOR_URL}