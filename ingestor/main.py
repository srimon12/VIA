# file: ingestor/main.py

import argparse
import hashlib
import sqlite3
import logging
import re
import time
import uuid
import pathlib
from typing import List, Dict, Any

from qdrant_client import QdrantClient, models
from fastembed import TextEmbedding

# --- Configuration & Logging ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("ingestor")

# --- Define the Tier 2 collection name ---
TIER_2_COLLECTION_NAME = "via_forensic_index"

# --- BGL Parser (can be expanded later with the dynamic schema engine) ---
BGL_PATTERN = re.compile(r"^(?P<label>-|\d+)\s+(?P<unix_ts>\d+)\s+.*\s+(?P<node>\S+)\s+.*\s+(?P<level>\w+)\s+(?P<msg>.*)$")

def parse_log_line(line: str) -> Dict[str, Any]:
    """Parses a single log line into a structured dictionary."""
    match = BGL_PATTERN.match(line.strip())
    if match:
        data = match.groupdict()
        return {"ts": int(data["unix_ts"]), "service": data["node"], "level": data["level"], "body": data["msg"]}
    return {"ts": int(time.time()), "service": "unknown", "level": "INFO", "body": line}

# --- Core Ingestion Logic (Refactored into Functions) ---
def process_log_batch(logs: List[Dict[str, Any]], window_size: int = 3) -> List[Dict[str, Any]]:
    """Processes a batch of raw log dicts, windows them, and prepares them for embedding."""
    # This is a simplified windowing for streaming. More advanced logic could be used.
    windows = ["\n".join(log['body'] for log in logs[i:i + window_size]) for i in range(0, len(logs), window_size)]
    
    processed_points = []
    for w in windows:
        first_log_meta = parse_log_line(w.splitlines()[0])
        processed_points.append({
            "text": w,
            "hash": hashlib.sha256(w.encode()).hexdigest(),
            "payload": {
                "ts": first_log_meta["ts"],
                "service": first_log_meta["service"],
                "level": first_log_meta["level"],
                "msg": w[:500]
            }
        })
    return processed_points

def embed_and_upsert_batch(
    client: QdrantClient,
    embed_model: TextEmbedding,
    points: List[Dict[str, Any]],
    collection_name: str
):
    """Embeds and upserts a batch of processed points to a Qdrant collection."""
    if not points:
        return 0

    texts_to_embed = [p["text"] for p in points]
    # NOTE: We'll add hybrid search back in a later PR. Sticking to dense for now.
    embeddings = list(embed_model.embed(texts_to_embed))

    qdrant_points = [
        models.PointStruct(
            id=str(uuid.uuid4()),
            vector=v,
            payload={**p["payload"], "hash": p["hash"]} # Add hash to payload
        )
        for p, v in zip(points, embeddings)
    ]

    client.upsert(collection_name, qdrant_points, wait=True)
    log.info(f"Successfully upserted {len(qdrant_points)} points to '{collection_name}'")
    return len(qdrant_points)


# --- Main block for CLI-based batch ingestion (retains original functionality) ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch ingest log files into VIA Tier 2.")
    parser.add_argument("--file", required=True, type=pathlib.Path, help="Path to the log file.")
    args = parser.parse_args()

    client = QdrantClient(host="localhost", port=6333)
    embed_model = TextEmbedding("BAAI/bge-small-en-v1.5")
    
    # Ensure Tier 2 collection exists
    client.recreate_collection(
        collection_name=TIER_2_COLLECTION_NAME,
        vectors_config=models.VectorParams(size=384, distance=models.Distance.COSINE),
        # Quantization can be re-enabled here if needed
    )

    log_lines = [{"body": line} for line in args.file.read_text(encoding="utf-8").splitlines()]
    processed_points = process_log_batch(log_lines)
    
    # Add deduplication logic here if running as a script
    # For simplicity in this refactor, we are skipping the ledger for now.
    
    embed_and_upsert_batch(client, embed_model, processed_points, TIER_2_COLLECTION_NAME)