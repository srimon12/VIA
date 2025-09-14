# Vector Incident Atlas (VIA)

Semantic log anomaly radar for Qdrant Hackathon.

## Setup

1. Generate demo data: `python generate_demo_logs.py`
2. Install dependencies: `pip install -r requirements.txt`
3. Start Qdrant locally: `docker-compose up -d`
4. Ingest logs: `python ingest.py --file logs/sample.log`
5. Run API: `uvicorn app.main:app --reload`
6. Run UI: `python ui.py`

## Demo

Detect anomalies in the last N minutes and find similar past incidents.