# file: tests/test_api_flow.py
# Action: Create this new file.

import pytest
import httpx
import time
import os

# --- Configuration ---
API_BASE_URL = "http://localhost:8000/api/v1"
# Ensure the mock streamer is pointing to the correct API URL
os.environ["INGESTOR_URL"] = f"{API_BASE_URL}/ingest/stream"

# --- Test Suite ---
@pytest.mark.asyncio
async def test_full_api_flow():
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=30) as client:
        # 1. Health Check
        print("\n--- 1. Testing Health Check ---")
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        print("✅ Health Check OK")

        # 2. Schema Detection (using a sample from your provided logs)
        print("\n--- 2. Testing Schema Detection ---")
        sample_log = "1117838570 2005.06.03 R02-M1-N0-C:J12-U11 2005-06-03-15.42.50.675872 R02-M1-N0-C:J12-U11 RAS KERNEL INFO instruction cache parity error corrected"
        detect_payload = {"source_name": "BGL", "sample_logs": [sample_log]}
        response = await client.post("/schemas/detect", json=detect_payload)
        assert response.status_code == 200
        schema = response.json()
        assert schema['source_name'] == 'BGL'
        assert any(field['name'] == 'service' for field in schema['fields'])
        print("✅ Schema Detection OK")

        # For this test, we assume the otel_mock service is running and streaming data.
        # We will wait a few seconds to ensure logs are ingested into Tier 1.
        print("\n--- 3. Waiting for Streaming Ingestion into Tier 1 ---")
        await asyncio.sleep(5) # Wait for a couple of batches from the mock streamer
        
        # 4. Check for Rhythm Anomalies (this will also trigger promotion to Tier 2)
        print("\n--- 4. Testing Tier 1 Rhythm Anomaly Detection ---")
        rhythm_payload = {"window_sec": 600}
        response = await client.post("/analysis/tier1/rhythm_anomalies", json=rhythm_payload)
        assert response.status_code == 200
        rhythm_data = response.json()
        assert "novel_anomalies_found" in rhythm_data
        print(f"✅ Tier 1 Analysis OK (Found {rhythm_data['novel_anomalies_found']} novel events)")

        # 5. Verify Promotion to Tier 2
        print("\n--- 5. Testing Tier 2 Anomaly Retrieval ---")
        # Wait a moment for promotion to complete
        await asyncio.sleep(2)
        now = int(time.time())
        tier2_payload = {"start_ts": now - 3600, "end_ts": now}
        response = await client.post("/analysis/tier2/anomalies", json=tier2_payload)
        assert response.status_code == 200
        tier2_data = response.json()
        assert "event_clusters" in tier2_data
        print(f"✅ Tier 2 Retrieval OK (Found {len(tier2_data['event_clusters'])} promoted clusters)")

        # 6. Test the Control Loop
        if rhythm_data['promoted_events']:
            print("\n--- 6. Testing Control Loop (Suppress & Patch) ---")
            first_anomaly = rhythm_data['promoted_events'][0]
            rhythm_hash_to_test = first_anomaly['rhythm_hash']

            # Suppress it
            suppress_payload = {"rhythm_hash": rhythm_hash_to_test, "duration_sec": 60}
            response = await client.post("/control/suppress", json=suppress_payload)
            assert response.status_code == 200
            print("✅ Suppression OK")

            # Re-run Tier 1 analysis and assert the anomaly is GONE
            response = await client.post("/analysis/tier1/rhythm_anomalies", json=rhythm_payload)
            refreshed_anomalies = response.json()['promoted_events']
            assert not any(a['rhythm_hash'] == rhythm_hash_to_test for a in refreshed_anomalies)
            print("✅ Verified anomaly is suppressed")