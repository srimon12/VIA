# 🛰️ Vector Incident Atlas (VIA)

Vector Incident Atlas (VIA) is a real-time, on-premise log intelligence platform. It acts as a semantic radar for your entire log stream, automatically detecting behavioral anomalies and providing the context needed to resolve incidents faster.

Instead of reactive keyword searching, VIA uses a Two-Tiered Detection architecture to understand the "rhythm" of your system. It identifies novel and frequency-based anomalies in real-time, promotes them to a permanent "knowledge graph," and learns from operator feedback, becoming an adaptive immune system for your operations.

## Core Features

### Two-Tiered Anomaly Detection:
- **Tier 1 (Rhythm Monitor)**: A high-throughput, in-memory monitor that analyzes the behavioral patterns of all logs (including INFO/DEBUG) using "Rhythm Hashing" to detect novel anomalies.
- **Tier 2 (Forensic Index)**: A permanent, time-partitioned knowledge graph where high-signal events from Tier 1 are promoted for deep, federated analysis and historical correlation.

### Adaptive Control Loop:
A complete feedback system that allows operators to "Snooze" alerts for temporary relief or "Mark as Normal" to permanently patch the detection engine, creating a robust evaluation harness.

### Streaming-First Architecture:
Designed to ingest data from real-time sources like OpenTelemetry (OTel) streams, with a modular, multi-service backend built on FastAPI.

### Scalable by Design:
Leverages time-partitioned collections in Qdrant, managed by a federated query layer in the API, allowing the system to scale to terabytes of daily log volume.

### Dynamic Schema Engine:
An API for analyzing raw log files, suggesting a parsing schema, and allowing users to configure new data sources on the fly.

## Architecture Overview

VIA is composed of three main services designed to run locally or in a containerized environment.

### Diagram-in-Words: Data Flow
```
+----------------+   +-------------------+   +----------------------------+
| OTel Mock API  |-->|    VIA Backend    |-->| Tier 1: Rhythm Monitor     |
| (Streaming)    |   | (FastAPI Service) |   | (Qdrant, Ephemeral)        |
+----------------+   +-------------------+   +----------------------------+
                               |                      | (Anomalous Events)
   (API Calls) <---------------+                      v
                               |          +----------------------------+
                               +--------->| Tier 2: Forensic Index     |
                                          | (Qdrant, Daily Collections)|
                                          +----------------------------+
```

- **OTel Mock Service**: Simulates a real-time stream of enterprise logs in a structured OTel format.
- **VIA Backend**: The core FastAPI application, now refactored into a modular, multi-service architecture. It handles ingestion, analysis, and the control loop.
- **Qdrant**: The vector database, used to power both the ephemeral Tier 1 monitor and the permanent, time-partitioned Tier 2 knowledge graph.

## Getting Started

### 1. Prerequisites
- Python 3.12+
- Docker and Docker Compose

### 2. Configuration
Create a `.env` file in the root of the project. You can copy the contents from `.env.example` if it exists, or use the following:

```bash
# .env
BGL_LOG_PATH="loghub/BGL/BGL_2k.log"
INGESTOR_URL="http://localhost:8000/api/v1/ingest/stream"
STREAM_INTERVAL_SEC=2
STREAM_BATCH_SIZE=50
```

### 3. Installation
Install the required Python dependencies.

```bash
pip install -r requirements.txt
```

### 4. Running the System Locally
You will need three separate terminal windows to run the full system.

#### Terminal 1: Start Qdrant
```bash
docker-compose up
```
This starts Qdrant and makes it available at http://localhost:6333.

#### Terminal 2: Start the OTel Mock Streamer
This service will begin streaming log data to the main API.
```bash
uvicorn otel_mock.main:app --host 127.0.0.1 --port 8002 --reload
```

#### Terminal 3: Start the Main VIA API Backend
This runs the core application. On startup, it will initialize the necessary databases and Qdrant collections.
```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

The API is now live and available at http://localhost:8000.

### 5. Testing the End-to-End Flow
With all services running, you can use curl to interact with the API.

#### Step A: Check the Health
```bash
curl http://localhost:8000/health
```

#### Step B: Analyze Tier 1 for Novel Anomalies
After letting the streamer run for about 30-60 seconds, check for rhythm anomalies. This call will detect novel patterns and automatically promote them to Tier 2.
```bash
curl -X POST http://localhost:8000/api/v1/analysis/tier1/rhythm_anomalies \
-H "Content-Type: application/json" \
-d '{"window_sec": 300}'
```

#### Step C: Query Tier 2 for Promoted Events
Check the permanent forensic index for the events that were just promoted from Tier 1.
```bash
# Get the current Unix timestamp
# (On Linux/macOS: `date +%s`, on Windows you may need to get it manually)
END_TS=$(date +%s)
START_TS=$((END_TS - 3600)) # Look back 1 hour

curl -X POST http://localhost:8000/api/v1/analysis/tier2/anomalies \
-H "Content-Type: application/json" \
-d "{\"start_ts\": $START_TS, \"end_ts\": $END_TS}"
```

#### Step D: Test the Control Loop
If Step B found an anomaly, take its rhythm_hash and use the control endpoint to suppress it.
```bash
# Replace 'your_hash_here' with an actual hash from the Tier 1 response
RHYTHM_HASH="your_hash_here"

curl -X POST http://localhost:8000/api/v1/control/suppress \
-H "Content-Type: application/json" \
-d "{\"rhythm_hash\": \"$RHYTHM_HASH\"}"
```

If you run the Tier 1 analysis again (Step B), this anomaly should no longer appear.

## API Endpoints Overview

All endpoints are prefixed with `/api/v1`.

### Ingestion:
- `POST /ingest/stream` - Endpoint for the OTel streamer to send log batches.

### Analysis:
- `POST /analysis/tier1/rhythm_anomalies` - Detects novel patterns in Tier 1 and promotes them.
- `POST /analysis/tier2/anomalies` - Retrieves promoted event clusters from Tier 2.
- `POST /analysis/tier2/similar` - Finds similar past events from the Tier 2 knowledge graph.

### Control Loop:
- `POST /control/suppress` - Temporarily snoozes a rhythm_hash.
- `POST /control/patch` - Permanently marks a rhythm_hash as normal.

### Schema Management:
- `POST /schemas/detect` - Suggests a schema from a sample of raw logs.
- `POST /schemas` - Saves a schema configuration.
- `GET /schemas/{source_name}` - Retrieves a saved schema.

## Technology Stack
- **Backend**: FastAPI, Python 3.12+
- **Vector Database**: Qdrant
- **Embeddings**: fastembed with ONNX models
- **Data Schemas**: Pydantic
- **Registries**: SQLite
- **Local Services**: Docker Compose, Uvicorn

## Roadmap
- [ ] Build a production-grade Vite/React frontend for visualization and interaction.
- [ ] Expand the "Rhythm Hashing" engine to include frequency-based anomalies.
- [ ] Add real-world ingestion sources (e.g., Kafka consumer, direct OTel collector integration).
- [ ] Integrate with ChatOps tools (Slack) for proactive alerting.

## License

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

This project is licensed under the [GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.en.html) - see the [LICENSE](./LICENSE) file for details.
