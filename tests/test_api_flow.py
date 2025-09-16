# file: tests/test_api_flow.py
import pytest
import httpx
import time
import asyncio
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
        response = await httpx.AsyncClient().get("http://localhost:8000/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        print("✅ Health Check OK")

        # 2. Schema Detection
        print("\n--- 2. Testing Schema Detection ---")
        sample_log = "1117838570 2005.06.03 R02-M1-N0-C:J12-U11 2005-06-03-15.42.50.675872 R02-M1-N0-C:J12-U11 RAS KERNEL INFO instruction cache parity error corrected"
        detect_payload = {"source_name": "BGL", "sample_logs": [sample_log]}
        response = await client.post("/schemas/detect", json=detect_payload)
        assert response.status_code == 200
        schema = response.json()
        assert schema['source_name'] == 'BGL'
        assert any(field['name'] == 'service' for field in schema['fields'])
        print("✅ Schema Detection OK")

        # 3. Wait for Ingestion
        print("\n--- 3. Waiting for Streaming Ingestion into Tier 1 ---")
        await asyncio.sleep(5) 
        
        # 4. Check for Rhythm Anomalies
        print("\n--- 4. Testing Tier 1 Rhythm Anomaly Detection ---")
        rhythm_payload = {"window_sec": 600}
        response = await client.post("/analysis/tier1/rhythm_anomalies", json=rhythm_payload)
        assert response.status_code == 200
        rhythm_data = response.json()
        # CHANGED: Assert against the new, more informative response format
        assert "novel_anomalies" in rhythm_data
        assert "frequency_anomalies" in rhythm_data
        print(f"✅ Tier 1 Analysis OK (Found {len(rhythm_data['novel_anomalies'])} novel and {len(rhythm_data['frequency_anomalies'])} frequency anomalies)")

        # 5. Verify Promotion to Tier 2
        print("\n--- 5. Testing Tier 2 Cluster Retrieval ---")
        await asyncio.sleep(2)
        now = int(time.time())
        tier2_payload = {"start_ts": now - 3600, "end_ts": now}
        # CHANGED: The endpoint is /clusters, not /anomalies, to match your router and UI.
        response = await client.post("/analysis/tier2/clusters", json=tier2_payload)
        assert response.status_code == 200
        tier2_data = response.json()
        # CHANGED: The response key is 'clusters', not 'event_clusters'.
        assert "clusters" in tier2_data
        print(f"✅ Tier 2 Retrieval OK (Found {len(tier2_data['clusters'])} promoted clusters)")

        # 6. Test the Control Loop
        # CHANGED: Combine both anomaly lists to find an event to suppress.
        all_anomalies = rhythm_data.get('novel_anomalies', []) + rhythm_data.get('frequency_anomalies', [])
        if all_anomalies:
            print("\n--- 6. Testing Control Loop (Suppress) ---")
            first_anomaly = all_anomalies[0]
            rhythm_hash_to_test = first_anomaly['rhythm_hash']

            suppress_payload = {"rhythm_hash": rhythm_hash_to_test, "duration_sec": 60}
            response = await client.post("/control/suppress", json=suppress_payload)
            assert response.status_code == 200
            print("✅ Suppression OK")

            # Re-run Tier 1 analysis and assert the anomaly is GONE
            response = await client.post("/analysis/tier1/rhythm_anomalies", json=rhythm_payload)
            refreshed_data = response.json()
            refreshed_anomalies = refreshed_data.get('novel_anomalies', []) + refreshed_data.get('frequency_anomalies', [])
            assert not any(a['rhythm_hash'] == rhythm_hash_to_test for a in refreshed_anomalies)
            print("✅ Verified anomaly is suppressed")
        else:
            print("⚠️ Skipping Control Loop test as no anomalies were found in Tier 1.")