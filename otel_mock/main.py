# file: otel_mock/main.py

import asyncio
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from typing import List

import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# --- Configuration ---
load_dotenv()
BGL_LOG_PATH = os.getenv("BGL_LOG_PATH", "loghub/BGL/BGL_2k.log")
INGESTOR_URL = os.getenv("INGESTOR_URL", "http://localhost:8000/ingest/stream")
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

# --- BGL Log Parser ---
BGL_PATTERN = re.compile(
    r"^(?P<label>-|\d+)\s+(?P<unix_ts>\d+)\s+(?P<date>\S+)\s+(?P<node>\S+)\s+"
    r"(?P<time>\S+)\s+(?P<device>\S+)\s+"
    r"(?P<component>RAS)\s+(?P<sub_component>\w+)\s+(?P<level>\w+)\s+(?P<msg>.*)$"
)

def parse_bgl_to_otel(line: str) -> OTelLogRecord | None:
    """Parses a BGL log line and converts it into a structured OTelLogRecord."""
    match = BGL_PATTERN.match(line.strip())
    if not match:
        return None
    
    data = match.groupdict()
    return OTelLogRecord(
        TimeUnixNano=int(data["unix_ts"]) * 1_000_000_000, # Convert sec to ns
        SeverityText=data["level"],
        Body=data["msg"],
        Attributes=[
            OTelLogAttribute(key="service.name", value=data["node"]),
            OTelLogAttribute(key="log.label", value=data["label"]),
            OTelLogAttribute(key="log.component", value=data["component"]),
            OTelLogAttribute(key="log.sub_component", value=data["sub_component"]),
        ]
    )

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
                    
                    otel_record = parse_bgl_to_otel(line)
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