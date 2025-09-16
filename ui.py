# file: ui.py
import gradio as gr
import requests
import pandas as pd
import json
import time
from typing import List, Tuple, Optional, Any, Dict
from urllib.parse import urlparse

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

def get_selected_cluster_from_state(state: List[Dict[str, Any]], evt: gr.SelectData) -> Dict[str, Any]:
    """Safely extracts the full data for a selected cluster from the state."""
    if not state or not evt.index:
        return {}
    return state[evt.index[0]]

# --------------- API Wrappers ---------------

def ping_health(api_base: str):
    try:
        parsed_url = urlparse(api_base)
        health_url = f"{parsed_url.scheme}://{parsed_url.netloc}/health"
    except Exception:
        return "❌ Invalid API Base URL format."
    ok, data = _safe_api("GET", health_url)
    if not ok: return f"❌ Backend health failed: `{data['error']}`"
    return f"✅ Backend OK · {data}"

def suppress_hash(api_base: str, selected_cluster_data: Dict[str, Any], duration_sec: int):
    if not selected_cluster_data: return "Select a cluster from the table first."
    rhythm_hash = selected_cluster_data.get("cluster_id")
    if not rhythm_hash: return "❌ Invalid cluster data (missing cluster_id)."
    ok, data = _safe_api("POST", f"{api_base}/control/suppress", json={"rhythm_hash": rhythm_hash, "duration_sec": duration_sec})
    message = data.get('message', data.get('error', 'Unknown response'))
    return f"✅ Suppressed: {message}"

def fetch_log_stream(api_base: str, limit: int, text_filter: str):
    params = {"limit": int(limit)}
    if text_filter:
        params["filter"] = text_filter
    ok, data = _safe_api("GET", f"{api_base}/stream/tail", params=params)
    if not ok:
        return f"❌ Log stream failed: `{data.get('error', 'Unknown error')}`"
    return json.dumps(data, indent=2)

def fetch_rules(api_base: str):
    ok, data = _safe_api("GET", f"{api_base}/control/rules")
    if not ok:
        return pd.DataFrame(), pd.DataFrame(), f"❌ Failed to fetch rules: {data.get('error')}"
    patches = pd.DataFrame(data.get("patches", []))
    suppressions = pd.DataFrame(data.get("suppressions", []))
    return patches, suppressions, "✅ Rules loaded successfully."

def remove_rule(api_base: str, rule_type: str, selected_row: Dict[str, Any]):
    if selected_row is None or pd.DataFrame(selected_row).empty:
        return "Select a rule from the table first."
    
    try:
        df = pd.DataFrame(selected_row)
        rhythm_hash = df.iloc[0]["rhythm_hash"]
    except (KeyError, IndexError):
        return "❌ Invalid selection."
        
    endpoint = "patch" if rule_type == "patch" else "suppress"
    ok, data = _safe_api("DELETE", f"{api_base}/control/{endpoint}/{rhythm_hash}")
    return data.get('message', 'An unknown error occurred.')

def classify_triage_examples(
    selected_choices: List[str],
    all_choices_dict: Dict[str, str],
    current_positives: List[str],
    current_negatives: List[str],
    move_to: str
):
    """
    Handles moving selected triage examples between the available, positive, and negative lists.
    """
    if not selected_choices:
        return gr.update(), gr.update(), gr.update(), gr.update(), gr.update()

    positive_set = set(current_positives)
    negative_set = set(current_negatives)
    
    for choice_label in selected_choices:
        item_id = all_choices_dict.get(choice_label)
        if not item_id:
            continue # Should not happen, but a safeguard

        if move_to == "positive":
            positive_set.add(item_id)
            if item_id in negative_set:
                negative_set.remove(item_id)
        elif move_to == "negative":
            negative_set.add(item_id)
            if item_id in positive_set:
                positive_set.remove(item_id)

    remaining_choices = {
        label: id for label, id in all_choices_dict.items() 
        if id not in positive_set and id not in negative_set
    }

    positive_display = "\n".join([f"- `{pid}`" for pid in positive_set]) or "None"
    negative_display = "\n".join([f"- `{nid}`" for nid in negative_set]) or "None"

    return gr.update(choices=list(remaining_choices.keys()), value=[]), positive_display, negative_display, list(positive_set), list(negative_set)
def patch_hash(api_base: str, selected_cluster_data: Dict[str, Any]):
    if not selected_cluster_data: return "Select a cluster from the table first."
    rhythm_hash = selected_cluster_data.get("cluster_id")
    # Correctly access the nested payload for the sample log
    top_hit_payload = selected_cluster_data.get("top_hit", {}).get("payload", {})
    sample_log = top_hit_payload.get("full_log_json", {})
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
        top_hit = c.get("top_hit", {}) or {}
        payload_data = top_hit.get("payload", {}) or {}
        rows.append({
            "type": payload_data.get("anomaly_type", "unknown").upper(),
            "service": payload_data.get("service"),
            "severity": payload_data.get("severity"),
            "count": c.get("incident_count"),
            "example": payload_data.get("body"),
            "context": payload_data.get("anomaly_context"),
            "rhythm_hash": payload_data.get("rhythm_hash"),
        })
    df = pd.DataFrame(rows)
    return f"✅ Found {len(rows)} clusters.", df, clusters, gr.update(visible=True), f"Last updated: {time.strftime('%H:%M:%S')}"

def run_triage(api_base: str, cluster_data: Optional[Dict], positive_ids: List[str], negative_ids: List[str], lookback_min: int):    
    if not isinstance(api_base, str) or not api_base.startswith('http'):
        return f"❌ Invalid API URL provided to triage function: {api_base}", [], [] 

    if not cluster_data:
        return "Select a cluster first.", [], [] 

    start_ts, end_ts = ts_window_from_lookback(lookback_min)
    
    if not positive_ids and not negative_ids:
        top_hit_id = cluster_data.get("top_hit", {}).get("id")
        if top_hit_id:
            positive_ids = [top_hit_id]
        else:
            return "❌ Cannot start triage: selected cluster is missing a valid example ID.", [], [] 

    payload = {"positive_ids": positive_ids, "negative_ids": negative_ids or [], "start_ts": start_ts, "end_ts": end_ts}
    
    ok, data = _safe_api("POST", f"{api_base}/analysis/tier2/triage", json=payload)
    if not ok:
        return f"❌ Triage failed: `{data['error']}`", [], [] 

    results = data.get("triage_results", [])
    if not results:
        return "No similar events found.", [], [] 
    
    choices = [(f"[{r.get('score', 0.0):.3f}] {r.get('payload', {}).get('body', '')[:140]}", r.get("id")) for r in results]
    table = pd.DataFrame([{"score": f"{r.get('score',0.0):.3f}", "id": r.get("id"), "body": r.get("payload",{}).get("body","")} for r in results])
    
    return table.to_markdown(index=False), choices, results
# --------------- Schema Management API Wrappers ---------------

def detect_schema_from_file(api_base: str, source_name: str, temp_file: Any):
    if not source_name or not temp_file:
        return "Source Name and Log File are required.", pd.DataFrame()
    
    with open(temp_file.name, 'r', encoding='utf-8') as f:
        sample_logs = [line for i, line in enumerate(f) if i < 100] # Send up to 100 lines

    payload = {"source_name": source_name, "sample_logs": sample_logs}
    ok, data = _safe_api("POST", f"{api_base}/schemas/detect", json=payload)
    
    if not ok:
        return f"❌ Schema detection failed: `{data.get('error', 'Unknown error')}`", pd.DataFrame()

    fields = data.get("fields", [])
    df = pd.DataFrame(fields) if fields else pd.DataFrame()
    return f"✅ Schema detected for '{source_name}'. You can edit it below.", df

def save_schema_from_df(api_base: str, source_name: str, schema_df: pd.DataFrame):
    if not source_name:
        return "Source Name is required to save."
    
    schema_dict = {"source_name": source_name, "fields": schema_df.to_dict('records')}
    ok, data = _safe_api("POST", f"{api_base}/schemas", json=schema_dict)

    if not ok:
        return f"❌ Failed to save schema: {data.get('error')}"
    
    return f"✅ Schema for '{source_name}' saved successfully."

def load_all_schemas(api_base: str):
    ok, data = _safe_api("GET", f"{api_base}/schemas")
    if not ok:
        return gr.update(choices=[], value=None), f"❌ Failed to load schemas: {data.get('error')}"
    return gr.update(choices=data or []), "Refreshed schema list."

def load_selected_schema(api_base: str, source_name: str):
    if not source_name:
        return "Select a schema to load.", pd.DataFrame()
        
    ok, data = _safe_api("GET", f"{api_base}/schemas/{source_name}")
    if not ok:
        return f"❌ Failed to load schema '{source_name}': {data.get('error')}", pd.DataFrame()

    fields = data.get("fields", [])
    df = pd.DataFrame(fields) if fields else pd.DataFrame()
    return f"✅ Loaded schema for '{source_name}'.", df
# --------------- UI Layout ---------------
JS_AUTO_REFRESH = """
() => {
    const refreshRadar = () => {
        const refreshButton = document.querySelector('#radar-refresh-button');
        if (refreshButton) {
            refreshButton.click();
        }
    };
    refreshRadar();
    setInterval(refreshRadar, 60000);
}
"""

with gr.Blocks(theme=gr.themes.Soft(), title="VIA – VeriStamp Incident Atlas", js=JS_AUTO_REFRESH) as demo:
    gr.Markdown("# 🛰️ VIA – VeriStamp Incident Atlas")
    gr.Markdown("An automated, adaptive log intelligence platform.")
    with gr.Row():
        api_base = gr.Textbox(value="http://127.0.0.1:8000/api/v1", label="API Base URL", scale=3)
        health_btn = gr.Button("Ping Health", scale=1)
        health_out = gr.Markdown()
    with gr.Tabs():
        # --- NEW SCHEMA MANAGEMENT TAB ---
        with gr.Tab("Data Sources ⚙️"):
            gr.Markdown("## Dynamic Schema Management\nOnboard new log sources by detecting and saving their structure.")
            schema_status = gr.Markdown()
            
            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("### 1. Detect New Schema")
                    detect_source_name = gr.Textbox(label="New Source Name", placeholder="e.g., nginx_access_logs")
                    log_file_upload = gr.File(label="Upload Sample Log File (.log, .txt, .jsonl)")
                    detect_btn = gr.Button("Detect Schema", variant="primary")

                    gr.Markdown("---")
                    gr.Markdown("### 2. Manage Existing Schemas")
                    schema_dropdown = gr.Dropdown(label="Select an Existing Schema")
                    with gr.Row():
                        refresh_schemas_btn = gr.Button("Refresh List")
                        load_schema_btn = gr.Button("Load Schema")

                with gr.Column(scale=2):
                    gr.Markdown("### 3. Edit and Save Schema")
                    schema_df = gr.Dataframe(
                        headers=["name", "type", "source_field"],
                        datatype=["str", "str", "str"],
                        interactive=True,
                        label="Detected/Loaded Schema"
                    )
                    save_schema_btn = gr.Button("Save Current Schema", variant="primary")
            
            # --- Event Handlers for Schema Tab ---
            detect_btn.click(
                fn=detect_schema_from_file,
                inputs=[api_base, detect_source_name, log_file_upload],
                outputs=[schema_status, schema_df]
            )
            save_schema_btn.click(
                fn=save_schema_from_df,
                inputs=[api_base, detect_source_name, schema_df],
                outputs=[schema_status]
            ).then(
                fn=load_all_schemas,
                inputs=[api_base],
                outputs=[schema_dropdown, schema_status]
            )
            refresh_schemas_btn.click(
                fn=load_all_schemas,
                inputs=[api_base],
                outputs=[schema_dropdown, schema_status]
            )
            load_schema_btn.click(
                fn=load_selected_schema,
                inputs=[api_base, schema_dropdown],
                outputs=[schema_status, schema_df]
            ).then(
                lambda x: x, # Copy dropdown value to the source name textbox
                inputs=[schema_dropdown],
                outputs=[detect_source_name]
            )

        # Live Stream Tab
        with gr.Tab("Live Log Stream 🔴"):
            gr.Markdown("## Live Log Stream\nA real-time view of the raw logs being ingested into VIA.")
            with gr.Row():
                stream_filter = gr.Textbox(label="Filter logs (text/regex)", placeholder="e.g., 'payment-service' or 'ERROR'")
                stream_limit = gr.Slider(10, 500, value=100, step=10, label="Lines to show")
                stream_refresh_btn = gr.Button("Refresh Stream", variant="primary")
            log_output = gr.Code(label="Log Output", language="json", interactive=False)
            stream_refresh_btn.click(fn=fetch_log_stream, inputs=[api_base, stream_limit, stream_filter], outputs=[log_output])
        # Radar Tab
        with gr.Tab("Radar (Live) 📡"):
            radar_clusters_state = gr.State([])
            selected_radar_cluster = gr.State(None)
            gr.Markdown("## Live Incident Radar\nContinuously displays active incident clusters from the last 15 minutes.")
            with gr.Row():
                with gr.Column(scale=3):
                    radar_status = gr.Markdown("Initializing...")
                    headers=["type", "service", "severity", "count", "example", "context", "rhythm_hash"]
                    radar_df = gr.Dataframe(headers=headers, interactive=True, wrap=True)
                with gr.Column(scale=1):
                    last_updated_display = gr.Markdown("Last updated: Never")
                    refresh_radar_btn = gr.Button("Refresh Now", variant="primary", elem_id="radar-refresh-button")
                    gr.Markdown("### Adaptive Control Loop")
                    suppress_duration = gr.Slider(60, 24*3600, value=3600, step=60, label="Suppress Duration (sec)")
                    suppress_btn = gr.Button("Suppress Selected Cluster")
                    patch_btn = gr.Button("Mark as Normal (Patch)")
                    control_status = gr.Markdown()
            refresh_radar_btn.click(fn=fetch_clusters, inputs=[api_base, gr.State(15), gr.State("")], outputs=[radar_status, radar_df, radar_clusters_state, gr.State(None), last_updated_display])
            radar_df.select(fn=get_selected_cluster_from_state, inputs=[radar_clusters_state], outputs=[selected_radar_cluster])
            suppress_btn.click(fn=suppress_hash, inputs=[api_base, selected_radar_cluster, suppress_duration], outputs=[control_status])
            patch_btn.click(fn=patch_hash, inputs=[api_base, selected_radar_cluster], outputs=[control_status])
        # Atlas Tab
        with gr.Tab("Atlas (Explore) 🗺️"):
            atlas_clusters_state = gr.State([])
            selected_atlas_cluster = gr.State(None)
            gr.Markdown("## Forensic Atlas\nPerform deep analysis on historical data.")
            with gr.Row():
                with gr.Column(scale=1):
                    lookback_min = gr.Slider(1, 1440, value=60, step=1, label="Look back (minutes)")
                    text_filter = gr.Textbox(label="Text filter (optional)", placeholder="e.g., 'database connection'")
                    fetch_btn = gr.Button("Discover Clusters", variant="primary")
                with gr.Column(scale=2):
                    cluster_status = gr.Markdown()
                    headers=["type", "service", "severity", "count", "example", "context", "rhythm_hash"]
                    clusters_df = gr.Dataframe(headers=headers, interactive=True, wrap=True)
            # In ui.py, in the Atlas Tab, replace the Accordion block

            with gr.Accordion("Triage Engine", open=True, visible=False) as triage_panel:
                all_triage_choices_state = gr.State({})
                positive_ids_state = gr.State([])
                negative_ids_state = gr.State([])
                triage_results_state = gr.State([])

                with gr.Row():
                    with gr.Column(scale=2):
                        gr.Markdown("#### 1. Select Examples to Classify")
                        triage_choices = gr.CheckboxGroup(label="Available Examples (from initial search)")
                        with gr.Row():
                            mark_relevant_btn = gr.Button("Mark as ✅ Relevant")
                            mark_irrelevant_btn = gr.Button("Mark as ❌ Irrelevant")
                        refine_btn = gr.Button("Refine Triage Using Feedback", variant="primary")
                    with gr.Column(scale=1):
                        gr.Markdown("#### 2. Your Feedback")
                        gr.Markdown("##### ✅ Relevant Examples")
                        positive_ids_display = gr.Markdown("None")
                        gr.Markdown("##### ❌ Irrelevant Examples")
                        negative_ids_display = gr.Markdown("None")

                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown("#### 3. Refined Triage Results")
                        triage_md = gr.Markdown("Triage results will appear here.")
                    with gr.Column(scale=1):
                        # FIX: Add the detail viewer component
                        gr.Markdown("#### Selected Example Detail")
                        triage_detail_view = gr.Code(label="Full Log JSON", language="json", interactive=False)
            fetch_btn.click(fn=fetch_clusters, inputs=[api_base, lookback_min, text_filter], outputs=[cluster_status, clusters_df, atlas_clusters_state, triage_panel, selected_atlas_cluster])
            
            def on_select_cluster(clusters_data: List[dict], evt: gr.SelectData, api_base_val: str, lookback_min_val: int):
                selected_raw = get_selected_cluster_from_state(clusters_data, evt)
                table_md, choices_list, raw_results = run_triage(api_base_val, selected_raw, [], [], lookback_min_val)
                choices_dict = {label: id for label, id in choices_list}
                return selected_raw, table_md, gr.update(choices=list(choices_dict.keys()), value=[]), choices_dict, "None", "None", [], [], raw_results, "Select an example from the checklist to see details."
            
            clusters_df.select(
                fn=on_select_cluster,
                inputs=[atlas_clusters_state, api_base, lookback_min],
                outputs=[selected_atlas_cluster, triage_md, triage_choices, all_triage_choices_state, positive_ids_display, negative_ids_display, positive_ids_state, negative_ids_state, triage_results_state, triage_detail_view],
            )
            
            mark_relevant_btn.click(fn=classify_triage_examples, inputs=[triage_choices, all_triage_choices_state, positive_ids_state, negative_ids_state, gr.State("positive")], outputs=[triage_choices, positive_ids_display, negative_ids_display, positive_ids_state, negative_ids_state])
            mark_irrelevant_btn.click(fn=classify_triage_examples, inputs=[triage_choices, all_triage_choices_state, positive_ids_state, negative_ids_state, gr.State("negative")], outputs=[triage_choices, positive_ids_display, negative_ids_display, positive_ids_state, negative_ids_state])
            
            def show_triage_detail(selected_labels: List[str], choices_dict: Dict[str, str], full_results: List[Dict]):
                if not selected_labels or not full_results:
                    return gr.update()
                
                last_selected_label = selected_labels[-1]
                selected_id = choices_dict.get(last_selected_label)

                for result in full_results:
                    if result.get("id") == selected_id:
                        payload = result.get("payload", {})
                        
                        sample_logs = payload.get("sample_logs", [])
                        if sample_logs:
                            return json.dumps(sample_logs[0], indent=2)
                        
                        return json.dumps(payload, indent=2)
                        
                return "Details not found."
            
            triage_choices.select(
                fn=show_triage_detail,
                inputs=[triage_choices, all_triage_choices_state, triage_results_state],
                outputs=[triage_detail_view]
            )

            def refined_triage_search(api_base_val, cluster_data, pos_ids, neg_ids, lookback):
                table_md, _, raw_results = run_triage(api_base_val, cluster_data, pos_ids, neg_ids, lookback)
                return table_md, raw_results
            
            refine_btn.click(fn=refined_triage_search, inputs=[api_base, selected_atlas_cluster, positive_ids_state, negative_ids_state, lookback_min], outputs=[triage_md, triage_results_state])
        # Control Panel Tab
        with gr.Tab("Control Panel ⚙️"):
            gr.Markdown("## Adaptive Control Rules\nView and manage all active suppression and patch rules.")
            control_panel_status = gr.Markdown()
            refresh_rules_btn = gr.Button("Refresh Rules", variant="primary")
            with gr.Row():
                with gr.Column():
                    gr.Markdown("### Permanent Patches (Marked as Normal)")
                    patch_df = gr.Dataframe(interactive=True, wrap=True)
                    remove_patch_btn = gr.Button("Remove Selected Patch")
                with gr.Column():
                    gr.Markdown("### Temporary Suppressions (Snoozed)")
                    suppress_df = gr.Dataframe(interactive=True, wrap=True)
                    remove_suppress_btn = gr.Button("Remove Selected Suppression")
            selected_patch = gr.State(None)
            selected_suppression = gr.State(None)
            patch_df.select(lambda _, row: row, inputs=[patch_df, patch_df], outputs=selected_patch, show_progress=False)
            suppress_df.select(lambda _, row: row, inputs=[suppress_df, suppress_df], outputs=selected_suppression, show_progress=False)
            refresh_rules_btn.click(fn=fetch_rules, inputs=[api_base], outputs=[patch_df, suppress_df, control_panel_status])
            remove_patch_btn.click(fn=remove_rule, inputs=[api_base, gr.State("patch"), selected_patch], outputs=[control_panel_status]).then(fn=fetch_rules, inputs=[api_base], outputs=[patch_df, suppress_df, control_panel_status])
            remove_suppress_btn.click(fn=remove_rule, inputs=[api_base, gr.State("suppress"), selected_suppression], outputs=[control_panel_status]).then(fn=fetch_rules, inputs=[api_base], outputs=[patch_df, suppress_df, control_panel_status])
    health_btn.click(fn=ping_health, inputs=[api_base], outputs=[health_out])
demo.launch()