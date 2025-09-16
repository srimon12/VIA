# file: ui.py
import gradio as gr
import requests
import pandas as pd
import json
import time
from typing import List, Tuple, Optional

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

# --------------- API Wrappers ---------------

def ping_health(api_base: str):
    ok, data = _safe_api("GET", f"{api_base}/health")
    if not ok:
        return f"❌ Backend health failed: `{data['error']}`"
    return f"✅ Backend OK · {data}"

# --- Schema Detection + Save ---

def detect_schema(api_base: str, source_name: str, sample_logs_text: str, auto_save: bool):
    sample_logs = [ln for ln in sample_logs_text.splitlines() if ln.strip()]
    if not source_name or not sample_logs:
        return "Please provide a Source name and at least one sample log.", None, None

    payload = {"source_name": source_name, "sample_logs": sample_logs}
    ok, data = _safe_api("POST", f"{api_base}/schemas/detect", json=payload)
    if not ok:
        return f"❌ Detect failed: `{data['error']}`", None, None

    if auto_save:
        _safe_api("POST", f"{api_base}/schemas", json=data)

    fields = data.get("fields", [])   
    df = pd.DataFrame(fields)
    schema_json = json.dumps(data, indent=2)
    return ("✅ Detected schema (auto-saved)." if auto_save else "✅ Detected schema."), df, schema_json

def save_schema(api_base: str, schema_json: str):
    if not schema_json:
        return "Provide a detected/edited schema JSON first."
    try:
        schema = json.loads(schema_json)
    except json.JSONDecodeError as e:  
        return f"Invalid JSON: {e}"
    ok, data = _safe_api("POST", f"{api_base}/schemas", json=schema)
    if not ok:
        return f"❌ Save failed: `{data['error']}`"
    return f"✅ Saved schema for source: **{data.get('source_name')}**"

def load_schema(api_base: str, source_name: str):
    if not source_name:
        return "Enter a source_name to load."
    ok, data = _safe_api("GET", f"{api_base}/schemas/{source_name}")
    if not ok:
        return f"❌ Load failed: `{data['error']}`", None, None
    df = pd.DataFrame(data.get("fields", []))
    return "✅ Loaded schema.", df, json.dumps(data, indent=2)

# --- Tier-1 Rhythm Anomalies ---

def run_tier1_anomalies(api_base: str, window_sec: int):
    payload = {"window_sec": window_sec}
    ok, data = _safe_api("POST", f"{api_base}/analysis/tier1/rhythm_anomalies", json=payload)
    if not ok:
        return f"❌ Tier-1 analyze failed: `{data['error']}`", None, None, []

    novel = data.get("novel_anomalies", [])
    freq = data.get("frequency_anomalies", [])

    def _df(anoms: List[dict]) -> pd.DataFrame:
        if not anoms:
            return pd.DataFrame(columns=["rhythm_hash", "service", "severity", "body", "ts"])
        rows = []
        for p in anoms:
            rows.append({
                "rhythm_hash": p.get("rhythm_hash"),
                "service": p.get("service"),
                "severity": p.get("severity"),
                "body": p.get("body"),
                "ts": p.get("ts"),
            })
        return pd.DataFrame(rows)

    novel_df = _df(novel)
    freq_df  = _df(freq)
    selectable_hashes = sorted({p.get("rhythm_hash") for p in novel + freq if p.get("rhythm_hash")})
    summary = f"✅ Detected **{len(novel)} novel** and **{len(freq)} frequency** anomalies."
    return summary, novel_df, freq_df, selectable_hashes

def suppress_hashes(api_base: str, hashes: List[str], duration_sec: int):
    if not hashes:
        return "Select at least one rhythm_hash."
    messages = []
    for h in hashes:
        ok, data = _safe_api("POST", f"{api_base}/control/suppress", json={"rhythm_hash": h, "duration_sec": duration_sec})
        messages.append(f"{'✅' if ok else '❌'} {h}: {data if ok else data.get('error')}")
    return "\n".join(messages)

# --- Tier-2 Clusters + Triage ---

def fetch_clusters(api_base: str, lookback_min: int, text_filter: str):
    start_ts, end_ts = ts_window_from_lookback(lookback_min)
    payload = {"start_ts": start_ts, "end_ts": end_ts}
    if text_filter:
        payload["text_filter"] = text_filter

    ok, data = _safe_api("POST", f"{api_base}/analysis/tier2/clusters", json=payload)
    if not ok:
        return f"❌ Cluster load failed: `{data['error']}`", None, [], gr.update(visible=False)

    clusters = data.get("clusters", [])
    if not clusters:
        return "No incident clusters found.", pd.DataFrame(columns=["cluster_id","service","severity","count","example"]), [], gr.update(visible=False)

    rows = []
    for c in clusters:
        top = c.get("top_hit", {}) or {}
        rows.append({
            "cluster_id": c.get("cluster_id"),
            "service": top.get("service"),
            "severity": top.get("severity"),
            "count": c.get("incident_count"),
            "example": top.get("body"),
        })
    df = pd.DataFrame(rows)
    return f"✅ {len(rows)} clusters.", df, clusters, gr.update(visible=True)

def select_cluster(clusters_data: List[dict], evt: gr.SelectData):
    if not clusters_data:
        return None, "Run cluster discovery first.", [], [], []
    row_idx = evt.index[0] if isinstance(evt.index, (list, tuple)) else evt.index
    row_idx = int(row_idx)
    selected = clusters_data[row_idx]
    # Reset triage state upon selection
    return json.dumps(selected), "Triage results will appear here.", [], [], []

def run_triage(api_base: str, cluster_json: Optional[str], positive_ids: List[str], negative_ids: List[str], lookback_min: int):
    if not cluster_json:
        return "Select a cluster first.", []
    start_ts, end_ts = ts_window_from_lookback(lookback_min)

    # If nothing selected, use cluster_id as positive seed
    cluster = json.loads(cluster_json)
    if not positive_ids and not negative_ids:
        positive_ids = [cluster.get("cluster_id")]

    payload = {
        "positive_ids": positive_ids,
        "negative_ids": negative_ids or [],
        "start_ts": start_ts,
        "end_ts": end_ts,
    }
    ok, data = _safe_api("POST", f"{api_base}/analysis/tier2/triage", json=payload)
    if not ok:
        return f"❌ Triage failed: `{data['error']}`", []

    results = data.get("triage_results", [])
    if not results:
        return "No similar events found.", []

    # Build human choices: label → id
    choices = []
    for r in results:
        msg = r.get("payload", {}).get("body", "")
        rid = r.get("id")
        score = r.get("score", 0.0)
        label = f"[{score:.3f}] {msg[:140]}{'...' if len(msg)>140 else ''}"
        choices.append((label, rid))
    table = pd.DataFrame([{"score": f"{r.get('score',0.0):.3f}", "id": r.get("id"), "body": r.get("payload",{}).get("body","")} for r in results])
    return table.to_markdown(index=False), choices

# --------------- Gradio App ---------------

with gr.Blocks(theme=gr.themes.Soft(), title="VIA – Incident Workbench") as demo:
    gr.Markdown("# 🛰️ VIA – Incident Workbench")
    gr.Markdown("End-to-end controls to **detect**, **promote**, **cluster**, **triage**, and **suppress** anomalies.")

    with gr.Row():
        api_base = gr.Textbox(value="http://127.0.0.1:8000/api/v1", label="API Base URL", scale=3)
        health_btn = gr.Button("Ping Health", scale=1)
        health_out = gr.Markdown()

    health_btn.click(fn=ping_health, inputs=[api_base], outputs=[health_out])

    with gr.Tabs():
        # -------- Schema Tab --------
        with gr.Tab("Schema"):
            with gr.Row():
                with gr.Column(scale=1):
                    src_name = gr.Textbox(label="Source name (e.g., BGL)")
                    sample_logs = gr.Textbox(label="Sample logs (one per line)", lines=8, placeholder="Paste a few raw log lines…")
                    detect_btn = gr.Button("Detect Schema", variant="primary")
                    save_btn = gr.Button("Save Schema")
                    load_btn = gr.Button("Load Schema")
                with gr.Column(scale=2):
                    schema_status = gr.Markdown()
                    fields_df = gr.Dataframe(headers=["name","type","source_field"], interactive=False, wrap=True)
                    schema_json = gr.Code(language="json", label="Schema JSON", interactive=True)

            detect_btn.click(
                fn=detect_schema,
                inputs=[api_base, src_name, sample_logs],
                outputs=[schema_status, fields_df, schema_json],
            )
            save_btn.click(
                fn=save_schema,
                inputs=[api_base, schema_json],
                outputs=[schema_status],
            )
            load_btn.click(
                fn=load_schema,
                inputs=[api_base, src_name],
                outputs=[schema_status, fields_df, schema_json],
            )

        # -------- Tier-1 Tab --------
        with gr.Tab("Tier-1 (Detect & Suppress)"):
            with gr.Row():
                with gr.Column(scale=1):
                    window_sec = gr.Slider(60, 3600, value=600, step=30, label="Detection Window (sec)")
                    run_t1_btn = gr.Button("Run Tier-1 Detection", variant="primary")
                    suppress_duration = gr.Slider(60, 24*3600, value=3600, step=60, label="Suppress Duration (sec)")
                    hashes_select = gr.CheckboxGroup(label="Select rhythm_hashes to suppress")
                    suppress_btn = gr.Button("Suppress Selected")
                with gr.Column(scale=2):
                    t1_summary = gr.Markdown()
                    gr.Markdown("**Novel Anomalies**")
                    novel_table = gr.Dataframe(interactive=False, wrap=True)
                    gr.Markdown("**Frequency Anomalies**")
                    freq_table = gr.Dataframe(interactive=False, wrap=True)
                    suppress_result = gr.Markdown()

            run_t1_btn.click(
                fn=run_tier1_anomalies,
                inputs=[api_base, window_sec],
                outputs=[t1_summary, novel_table, freq_table, hashes_select],
            )
            suppress_btn.click(
                fn=suppress_hashes,
                inputs=[api_base, hashes_select, suppress_duration],
                outputs=[suppress_result],
            )

        # -------- Tier-2 Tab --------
        with gr.Tab("Tier-2 (Clusters & Triage)"):
            clusters_state = gr.State([])           # raw clusters
            selected_cluster = gr.State(None)       # JSON string of selected cluster

            with gr.Row():
                with gr.Column(scale=1):
                    lookback_min = gr.Slider(1, 240, value=60, step=1, label="Look back (minutes)")
                    text_filter = gr.Textbox(label="Text filter (optional)", placeholder="e.g., 'database connection'")
                    fetch_btn = gr.Button("Discover Clusters", variant="primary")
                with gr.Column(scale=2):
                    cluster_status = gr.Markdown()
                    clusters_df = gr.Dataframe(headers=["cluster_id","service","severity","count","example"], interactive=False, wrap=True)

            with gr.Accordion("Triage", open=True, visible=False) as triage_panel:
                with gr.Row():
                    with gr.Column(scale=1):
                        triage_choices = gr.CheckboxGroup(label="Add/Remove examples for triage below")
                        positive_ids = gr.CheckboxGroup(label="✅ Relevant")
                        negative_ids = gr.CheckboxGroup(label="❌ Irrelevant")
                        refine_btn = gr.Button("Refine Triage", variant="primary")
                    with gr.Column(scale=2):
                        triage_md = gr.Markdown("Triage results will appear here.")

            # Discover clusters
            fetch_btn.click(
                fn=fetch_clusters,
                inputs=[api_base, lookback_min, text_filter],
                outputs=[cluster_status, clusters_df, clusters_state, triage_panel],
            )

            # Select cluster → seed triage
            clusters_df.select(
                fn=select_cluster,
                inputs=[clusters_state],
                outputs=[selected_cluster, triage_md, triage_choices, positive_ids, negative_ids],
            ).then(
                fn=run_triage,
                inputs=[api_base, selected_cluster, positive_ids, negative_ids, lookback_min],
                outputs=[triage_md, triage_choices]
            )

            # Refine triage with user selections
            refine_btn.click(
                fn=run_triage,
                inputs=[api_base, selected_cluster, positive_ids, negative_ids, lookback_min],
                outputs=[triage_md, triage_choices]
            )

demo.launch()
