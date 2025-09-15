# Vector Incident Atlas (VIA)

Semantic log anomaly radar for the Qdrant Hackathon.

Vector Incident Atlas (VIA) detects unusual patterns in system logs within a specified time window and retrieves similar past incidents grouped by service, using Qdrant’s vector search capabilities. Built for the "Think Outside the Bot" Hackathon, it avoids chatbot UIs, focusing on a dashboard for SREs/DevOps to triage issues quickly. Features include log ingestion, semantic anomaly detection (kNN-based scoring), and grouped recommendations, all running on-prem with scalar quantization for efficiency.

## Setup

1. **Generate Demo Data:**
   ```bash
   python generate_demo_logs.py
   ```
   Creates `logs/sample.log` with 540 lines: 20 ERRORs (last hour), 20 WARNs (~2 days ago), 500 normal logs (72h spread).

2. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
   Requires Python 3.12+ (see `.python-version`).

3. **Start Qdrant Locally:**
   ```bash
   docker-compose up -d
   ```
   Runs Qdrant on `localhost:6333` with 512MB limit and persistent storage.

4. **Ingest Logs:**
   ```bash
   python ingest.py --file logs/sample.log
   ```
   Windows: `python ingest.py --file logs\sample.log`.  
   Ingests ~180 points (540 lines windowed by 3) into Qdrant collection `logs_atlas` with scalar quantization (INT8, 4x memory savings). Deduplication uses SQLite ledger (`ingest_ledger.db`).

5. **Run API:**
   ```bash
   uvicorn app.main:app --reload
   ```
   Starts FastAPI on `http://localhost:8000`. Endpoints: `/anomalies` (detects outliers), `/similar` (finds past incidents), `/health`.

6. **Run UI:**
   ```bash
   python ui.py
   ```
   Windows: `uv run .\ui.py`.  
   Launches Gradio UI on `http://localhost:7860`. Set time window (e.g., 60 min), click "Detect Anomalies" to see ~20 ERRORs (scores >0.1), then "Find Similar Past Incidents" for grouped WARNs.

## Demo

- **Anomaly Detection:** Identifies semantic outliers in the last N minutes (e.g., ERROR spike in last hour). Table shows Score, Service, Level, Timestamp, Message with copy buttons.
- **Similar Incidents:** Retrieves past incidents (e.g., WARNs from ~2 days ago) grouped by service, aiding triage with historical context.
- **Qdrant Features:** Uses filters (time-based), recommend (anomaly scoring), recommend_groups (diverse results), and scalar quantization (memory/speed optimized).

## Notes

- **Expected Output:** Ingesting `sample.log` yields ~180 points. UI should show ~20 ERROR anomalies for a 60-minute window. If none appear, check timestamps in `sample.log` (regenerate if old) or Qdrant dashboard (`http://localhost:6333/dashboard`).
- **Debugging:** Check `ingest.py` logs for deduplication (`DEBUG` level) or `parse_fail`. Test `/anomalies` with `curl -X POST http://localhost:8000/anomalies -H "Content-Type: application/json" -d '{"window_sec": 3600}'`.
- **Hackathon Submission:** Video demo (<60s) shows ingestion, anomaly detection, and grouped recommendations. Submit by Sep 16, 2025, 11:59 PM PT (Sep 17, 12:29 PM IST).


## License

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

This project is licensed under the [GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.en.html) - see the [LICENSE](./LICENSE) file for details.
