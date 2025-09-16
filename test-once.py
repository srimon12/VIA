# file: test_query.py
import time
from datetime import datetime, timedelta
from qdrant_client import QdrantClient, models

# --- Configuration (matches your project's settings) ---
QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
TIER_2_COLLECTION_PREFIX = "via_forensic_index_v2"
LOOKBACK_HOURS = 1  # How far back we should look for clusters

def get_collections_for_window(prefix: str, start_ts: int, end_ts: int):
    """Generates the daily collection names for a given time window."""
    s = datetime.fromtimestamp(start_ts).date()
    e = datetime.fromtimestamp(end_ts).date()
    for i in range((e - s).days + 1):
        yield f"{prefix}_{(s + timedelta(days=i)).strftime('%Y_%m_%d')}"

def main():
    """Connects to Qdrant and runs a direct query to find Tier-2 clusters."""
    print("--- VIA Direct Qdrant Query Test ---")
    
    try:
        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        print(f"✅ Successfully connected to Qdrant at {QDRANT_HOST}:{QDRANT_PORT}")
    except Exception as e:
        print(f"❌ Could not connect to Qdrant. Is it running? Error: {e}")
        return

    # 1. Calculate the time window for the query
    end_ts = int(time.time())
    start_ts = end_ts - (LOOKBACK_HOURS * 3600)
    
    print(f"\n[1] Querying for clusters in the last {LOOKBACK_HOURS} hour(s)...")
    print(f"    - Start Timestamp: {start_ts} ({datetime.fromtimestamp(start_ts)})")
    print(f"    - End Timestamp:   {end_ts} ({datetime.fromtimestamp(end_ts)})")

    # 2. Determine which daily collections to search
    target_collections = list(get_collections_for_window(TIER_2_COLLECTION_PREFIX, start_ts, end_ts))
    
    try:
        all_collections = {c.name for c in client.get_collections().collections}
        active_collections = [c for c in target_collections if c in all_collections]
    except Exception as e:
        print(f"❌ Error fetching collection list: {e}")
        return

    if not active_collections:
        print(f"\n❌ No active Tier 2 collections found for this time window. Searched for: {target_collections}")
        return
        
    print(f"\n[2] Found active collections to search: {active_collections}")

    # 3. Define the query parameters
    query_filter = models.Filter(must=[
        models.FieldCondition(key="start_ts", range=models.Range(gte=start_ts, lte=end_ts))
    ])
    query_vector = models.NamedVector(name="log_dense_vector", vector=[0.0] * 384)

    # 4. Execute the query and gather results
    print("\n[3] Executing search_groups query...")
    all_groups = []
    for collection_name in active_collections:
        try:
            # FIX: Pass arguments directly to the function instead of using a request object.
            results = client.search_groups(
                collection_name=collection_name,
                query_vector=query_vector,
                group_by="rhythm_hash",
                query_filter=query_filter,
                group_size=1,
                limit=100,
                with_payload=True
            )
            if results.groups:
                all_groups.extend(results.groups)
                print(f"    - Found {len(results.groups)} groups in '{collection_name}'")
        except Exception as e:
            print(f"    - ❌ Error searching in '{collection_name}': {e}")
    
    # 5. Print the results (this part is unchanged)
    print("\n[4] --- QUERY RESULTS ---")
    if not all_groups:
        print("❌ No clusters found in the specified time window.")
        print("\n   Possible Reasons:")
        print("   1. No anomalies have been promoted to Tier 2 yet.")
        print("   2. Timezone Mismatch: Check if the timestamps printed above match the 'start_ts' of points in your Qdrant collections.")
        print("   3. Time Window Too Narrow: Try increasing LOOKBACK_HOURS at the top of this script.")
    else:
        print(f"✅ SUCCESS! Found a total of {len(all_groups)} clusters.")
        print("--- Top 5 Clusters ---")
        
        all_groups.sort(key=lambda g: g.hits[0].score, reverse=True)
        
        for i, group in enumerate(all_groups[:5]):
            payload = group.hits[0].payload
            print(f"\n--- Cluster #{i+1} ---")
            print(f"  Rhythm Hash: {payload.get('rhythm_hash')}")
            print(f"  Incident Count: {payload.get('count')}")
            print(f"  Service: {payload.get('service')}")
            print(f"  Severity: {payload.get('severity')}")
            print(f"  Example Body: \"{payload.get('body', '')[:100]}...\"")
if __name__ == "__main__":
    main()