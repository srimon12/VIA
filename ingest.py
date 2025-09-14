import argparse
import hashlib
import sqlite3
import logging
import re
import time
import uuid
import pathlib
from qdrant_client import QdrantClient, models
from fastembed import TextEmbedding

# --- Production-minded logging setup ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("ingest")

# --- Optimized Parser for Canonical BGL Format ---
BGL_PATTERN = re.compile(
    r"^(?P<label>-|\d+)\s+(?P<unix_ts>\d+)\s+(?P<date>\S+)\s+(?P<node>\S+)\s+"
    r"(?P<time>\S+)\s+(?P<device>\S+)\s+"
    r"(?P<component>RAS)\s+(?P<sub_component>\w+)\s+(?P<level>\w+)\s+(?P<msg>.*)$"
)

def parse_line(line: str) -> dict:
    """Parses a single line using the canonical BGL regex."""
    match = BGL_PATTERN.match(line.strip())
    if match:
        data = match.groupdict()
        return {
            "ts": int(data["unix_ts"]),
            "service": data["node"],
            "level": data["level"],
        }
    return {"ts": int(time.time()), "service": "unknown", "level": "INFO"}

def main():
    parser = argparse.ArgumentParser(description="Ingest log files into Qdrant for VIA.")
    parser.add_argument("--file", required=True, type=pathlib.Path, help="Path to the log file.")
    parser.add_argument("--collection", default="logs_atlas", help="Name of the Qdrant collection.")
    parser.add_argument("--window", type=int, default=3, help="Number of lines to group into a single document.")
    args = parser.parse_args()

    if not args.file.exists():
        log.error(f"File not found: {args.file}")
        return

    # --- Initialize clients and DB ---
    client = QdrantClient(host="localhost", port=6333)
    embed_model = TextEmbedding("BAAI/bge-small-en-v1.5")
    ledger_path = pathlib.Path("ingest_ledger.db")
    conn = sqlite3.connect(ledger_path)
    conn.execute("CREATE TABLE IF NOT EXISTS hashes (hash TEXT PRIMARY KEY)")

    # --- Ensure Qdrant Collection Exists ---
    try:
        client.get_collection(collection_name=args.collection)
    except Exception:
        log.info(f"Creating Qdrant collection: {args.collection}")
        client.recreate_collection(
            collection_name=args.collection,
            vectors_config=models.VectorParams(size=384, distance=models.Distance.COSINE),
            quantization_config=models.ScalarQuantization(
                scalar=models.ScalarQuantizationConfig(type=models.ScalarType.INT8, quantile=0.99, always_ram=True)
            ),
        )

    # --- Read, Window, and Dedup ---
    log.info(f"Processing file: {args.file}")
    lines = args.file.read_text(encoding="utf-8").splitlines()
    windows = ["\n".join(lines[i:i+args.window]) for i in range(0, len(lines), args.window) if i+args.window <= len(lines)]

    new_windows = []
    seen_in_batch = set()
    cursor = conn.cursor()
    for w in windows:
        h = hashlib.sha256(w.encode()).hexdigest()
        if h in seen_in_batch or cursor.execute("SELECT 1 FROM hashes WHERE hash=?", (h,)).fetchone():
            continue
        new_windows.append({"text": w, "hash": h})
        seen_in_batch.add(h)

    if not new_windows:
        log.info("No new log windows to ingest.")
        return
    log.info(f"Found {len(new_windows)} new windows to process.")

    # --- Parse Metadata ---
    parsed_points = []
    parse_ok = parse_fail = 0
    for w_data in new_windows:
        first_line = w_data["text"].splitlines()[0]
        meta = parse_line(first_line)
        if meta["service"] == "unknown":
            parse_fail += 1
        else:
            parse_ok += 1
        parsed_points.append({
            "text": w_data["text"],
            "payload": {
                "ts": meta["ts"],
                "service": meta["service"],
                "level": meta["level"],
                "hash": w_data["hash"],
                "msg": w_data["text"][:500],
            }
        })

    # --- Embed and Upsert in Batches ---
    log.info("Embedding new windows...")
    texts_to_embed = [p["text"] for p in parsed_points]
    embeddings = list(embed_model.embed(texts_to_embed))

    qdrant_points = [
        models.PointStruct(id=str(uuid.uuid4()), vector=v, payload=p["payload"])
        for p, v in zip(parsed_points, embeddings)
    ]

    log.info(f"Upserting {len(qdrant_points)} points to Qdrant...")
    client.upsert(args.collection, qdrant_points, wait=True)

    # --- Update Ledger on Success ---
    hashes_to_insert = [(p["payload"]["hash"],) for p in parsed_points]
    conn.executemany("INSERT INTO hashes (hash) VALUES (?)", hashes_to_insert)
    conn.commit()
    conn.close()

    log.info({
        "status": "complete",
        "points_ingested": len(qdrant_points),
        "parse_success": parse_ok,
        "parse_fail": parse_fail
    })

if __name__ == "__main__":
    main()