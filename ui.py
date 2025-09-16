# file: ui.py
import gradio as gr
import requests
import pandas as pd
import json
import time
from typing import List, Tuple, Optional, Any, Dict

# --------------- Helpers ---------------
def ts_window_from_lookback(lookback_min: int) -> Tuple[int, int]:
    end_ts = int(time.time())
    start_ts = end_ts - lookback_min * 60
    return start_ts, end_ts

def _safe_api(method: str, url: str, **kwargs):
    try:
        resp = requests.request(method, url, timeout=30, **kwargs)
        resp.raise_for_status()
        return True, resp.json()
    except requests.exceptions.RequestException as e:
        return False, {"error": str(e)}

# --- FIX: New helper function to handle dataframe selections cleanly ---
def get_selected_cluster_from_state(state: List[Dict[str, Any]], evt: gr.SelectData) -> Dict[str, Any]:
    """Safely extracts the full data for a selected cluster from the state."""
    if not state or not evt.index:
        return {} # Return an empty dict if no selection or state
    # The event gives us the row index, we use it to look up the full data in our state
    return state[evt.index[0]]

# --------------- API Wrappers ---------------

def ping_health(api_base: str):
    ok, data = _safe_api("GET", f"{api_base}/health")
    if not ok: return f"❌ Backend health failed: `{data['error']}`"
    return f"✅ Backend OK · {data}"

# In ui.py

def suppress_hash(api_base: str, selected_cluster_data: Dict[str, Any], duration_sec: int):
    if not selected_cluster_data: return "Select a cluster from the table first."
    
    # FIX: Get the hash from 'cluster_id' which is the correct key from the API response
    rhythm_hash = selected_cluster_data.get("cluster_id")
    
    if not rhythm_hash: return "❌ Invalid cluster data (missing cluster_id)."
    
    ok, data = _safe_api("POST", f"{api_base}/control/suppress", json={"rhythm_hash": rhythm_hash, "duration_sec": duration_sec})
    message = data.get('message', data.get('error', 'Unknown response'))
    return f"✅ Suppressed: {message}"

def patch_hash(api_base: str, selected_cluster_data: Dict[str, Any]):
    if not selected_cluster_data: return "Select a cluster from the table first."

    # FIX: Get the hash from 'cluster_id'
    rhythm_hash = selected_cluster_data.get("cluster_id")

    top_hit = selected_cluster_data.get("top_hit", {})
    sample_log = top_hit.get("full_log_json", {})
    
    if not rhythm_hash: return "❌ Invalid cluster data (missing cluster_id)."

    payload = {"rhythm_hash": rhythm_hash, "patch_type": "ALLOW_LIST", "context_logs": [json.dumps(sample_log)]}
    ok, data = _safe_api("POST", f"{api_base}/control/patch", json=payload)
    message = data.get('message', data.get('error', 'Unknown response'))
    return f"✅ Patched: {message}"
def fetch_clusters(api_base: str, lookback_min: Optional[int], text_filter: str):
    payload = {}
    if lookback_min is not None:
        start_ts, end_ts = ts_window_from_lookback(lookback_min)
        payload["start_ts"] = start_ts
        payload["end_ts"] = end_ts
    if text_filter: payload["text_filter"] = text_filter

    ok, data = _safe_api("POST", f"{api_base}/analysis/tier2/clusters", json=payload)
    if not ok: return f"❌ Cluster load failed: `{data['error']}`", pd.DataFrame(), [], gr.update(visible=False), f"Last updated: {time.strftime('%H:%M:%S')}"

    clusters = data.get("clusters", [])
    if not clusters:
        return "No incident clusters found.", pd.DataFrame(), [], gr.update(visible=False), f"Last updated: {time.strftime('%H:%M:%S')}"

    rows = []
    for c in clusters:
        top = c.get("top_hit", {}) or {}
        rows.append({
            "rhythm_hash": top.get("rhythm_hash"),
            "service": top.get("service"),
            "severity": top.get("severity"),
            "count": c.get("incident_count"),
            "example": top.get("body"),
        })
    df = pd.DataFrame(rows)
    return f"✅ Found {len(rows)} clusters.", df, clusters, gr.update(visible=True), f"Last updated: {time.strftime('%H:%M:%S')}"

def select_cluster_for_triage(clusters_data: List[dict], evt: gr.SelectData):
    if not clusters_data: return None, "Run cluster discovery first.", [], [], []
    selected_raw = get_selected_cluster_from_state(clusters_data, evt)
    return selected_raw, "Triage results will appear here.", [], [], []

def run_triage(api_base: str, cluster_data: Optional[Dict], positive_ids: List[str], negative_ids: List[str], lookback_min: int):
    if not cluster_data: return "Select a cluster first.", []
    start_ts, end_ts = ts_window_from_lookback(lookback_min)
    
    if not positive_ids and not negative_ids:
        positive_ids = [cluster_data.get("cluster_id")]

    payload = {"positive_ids": positive_ids, "negative_ids": negative_ids or [], "start_ts": start_ts, "end_ts": end_ts}
    ok, data = _safe_api("POST", f"{api_base}/analysis/tier2/triage", json=payload)
    if not ok: return f"❌ Triage failed: `{data['error']}`", []

    results = data.get("triage_results", [])
    if not results: return "No similar events found.", []
    
    choices = [(f"[{r.get('score', 0.0):.3f}] {r.get('payload', {}).get('body', '')[:140]}", r.get("id")) for r in results]
    table = pd.DataFrame([{"score": f"{r.get('score',0.0):.3f}", "id": r.get("id"), "body": r.get("payload",{}).get("body","")} for r in results])
    return table.to_markdown(index=False), choices

# --- FIX: Define the JavaScript for auto-refreshing here ---
JS_AUTO_REFRESH = """
() => {
    // Function to click the refresh button
    const refreshRadar = () => {
        const refreshButton = document.querySelector('#radar-refresh-button');
        if (refreshButton) {
            refreshButton.click();
            console.log('Auto-refreshing radar...');
        }
    };
    
    // Run once on page load
    refreshRadar();
    
    // Then run every 60 seconds
    setInterval(refreshRadar, 60000);
}
"""

# --------------- Gradio App ---------------
# --- FIX: Pass the JavaScript to the Blocks constructor ---
with gr.Blocks(theme=gr.themes.Soft(), title="VIA – Vector Incident Atlas", js=JS_AUTO_REFRESH) as demo:
    gr.Markdown("# 🛰️ VIA – Vector Incident Atlas")
    gr.Markdown("An automated, adaptive log intelligence platform.")

    with gr.Row():
        api_base = gr.Textbox(value="http://127.0.0.1:8000/api/v1", label="API Base URL", scale=3)
        health_btn = gr.Button("Ping Health", scale=1)
        health_out = gr.Markdown()

    with gr.Tabs():
        # -------- Radar Tab (Live View) --------
        with gr.Tab("Radar (Live) 📡"):
            radar_clusters_state = gr.State([])
            selected_radar_cluster = gr.State(None)

            gr.Markdown("## Live Incident Radar\nContinuously displays active incident clusters from the last 15 minutes.")
            with gr.Row():
                with gr.Column(scale=3):
                    radar_status = gr.Markdown("Initializing...")
                    radar_df = gr.Dataframe(headers=["rhythm_hash", "service", "severity", "count", "example"], interactive=True, wrap=True)
                with gr.Column(scale=1):
                    last_updated_display = gr.Markdown("Last updated: Never")
                    refresh_radar_btn = gr.Button("Refresh Now", variant="primary", elem_id="radar-refresh-button")                  
                    gr.Markdown("### Adaptive Control Loop")
                    suppress_duration = gr.Slider(60, 24*3600, value=3600, step=60, label="Suppress Duration (sec)")
                    suppress_btn = gr.Button("Suppress Selected Cluster")
                    patch_btn = gr.Button("Mark as Normal (Patch)")
                    control_status = gr.Markdown()            
            
            refresh_radar_btn.click(
                fn=fetch_clusters,
                inputs=[api_base, gr.State(None), gr.State("")],
                outputs=[radar_status, radar_df, radar_clusters_state, gr.State(None), last_updated_display]
            )

            
            # --- FIX: Use the new helper for a clean and correct select handler ---
            radar_df.select(
                fn=get_selected_cluster_from_state,
                inputs=[radar_clusters_state],
                outputs=[selected_radar_cluster]
            )

            suppress_btn.click(
                fn=suppress_hash,
                inputs=[api_base, selected_radar_cluster, suppress_duration],
                outputs=[control_status]
            )
            patch_btn.click(
                fn=patch_hash,
                inputs=[api_base, selected_radar_cluster],
                outputs=[control_status]
            )

        # -------- Atlas Tab (Historical Explorer) --------
        with gr.Tab("Atlas (Explore) 🗺️"):
            atlas_clusters_state = gr.State([])
            selected_atlas_cluster = gr.State(None)

            gr.Markdown("## Forensic Atlas\nPerform deep analysis on historical data. Discover, cluster, and triage past incidents.")
            with gr.Row():
                with gr.Column(scale=1):
                    lookback_min = gr.Slider(1, 1440, value=60, step=1, label="Look back (minutes)")
                    text_filter = gr.Textbox(label="Text filter (optional)", placeholder="e.g., 'database connection'")
                    fetch_btn = gr.Button("Discover Clusters", variant="primary")
                with gr.Column(scale=2):
                    cluster_status = gr.Markdown()
                    clusters_df = gr.Dataframe(headers=["rhythm_hash","service","severity","count","example"], interactive=True, wrap=True)

            with gr.Accordion("Triage Engine", open=True, visible=False) as triage_panel:
                with gr.Row():
                    with gr.Column(scale=1):
                        triage_choices = gr.CheckboxGroup(label="Add/Remove examples for triage below")
                        positive_ids = gr.CheckboxGroup(label="✅ Relevant")
                        negative_ids = gr.CheckboxGroup(label="❌ Irrelevant")
                        refine_btn = gr.Button("Refine Triage", variant="primary")
                    with gr.Column(scale=2):
                        triage_md = gr.Markdown("Triage results will appear here.")
            
            fetch_btn.click(
                fn=fetch_clusters,
                inputs=[api_base, lookback_min, text_filter],
                outputs=[cluster_status, clusters_df, atlas_clusters_state, triage_panel, gr.State(None)],
            )

            clusters_df.select(
                fn=select_cluster_for_triage,
                inputs=[atlas_clusters_state],
                outputs=[selected_atlas_cluster, triage_md, triage_choices, positive_ids, negative_ids],
            ).then(
                fn=run_triage,
                inputs=[api_base, selected_atlas_cluster, positive_ids, negative_ids, lookback_min],
                outputs=[triage_md, triage_choices]
            )

            refine_btn.click(
                fn=run_triage,
                inputs=[api_base, selected_atlas_cluster, positive_ids, negative_ids, lookback_min],
                outputs=[triage_md, triage_choices]
            )
            
    health_btn.click(fn=ping_health, inputs=[api_base], outputs=[health_out])
    
    # --- FIX: Removed the incorrect demo.load() call ---

demo.launch()