import gradio as gr
import requests
import pandas as pd
from datetime import datetime

# --- API Communication ---
API_URL = "http://127.0.0.1:8000"

def detect_anomalies(window_min: int):
    """Calls the backend to detect anomalies and formats the output."""
    try:
        response = requests.post(f"{API_URL}/anomalies", json={"window_sec": window_min * 60}, timeout=30)
        response.raise_for_status()
        data = response.json()

        outliers = data.get("outliers", [])
        if not outliers:
            return "No anomalies detected in this time window.", [], "---"

        # Format as a Markdown table
        df = pd.DataFrame([{
            "Score": f"{o['score']:.4f}",
            "Service": o['payload']['service'],
            "Timestamp": datetime.fromtimestamp(o['payload']['ts']).strftime('%Y-%m-%d %H:%M:%S'),
            "Message": f"```{o['payload']['msg']}```"
        } for o in outliers])
        
        # Sort by score descending
        df = df.sort_values(by="Score", ascending=False)
        
        return df.to_markdown(index=False), [o["id"] for o in outliers]

    except requests.exceptions.RequestException as e:
        return f"## API Error\nCould not connect to backend: `{e}`", []
    except Exception as e:
        return f"## Error\nAn unexpected error occurred: `{e}`", []

def find_similar(ids: list, window_min: int):
    """Calls the backend to find similar past incidents."""
    if not ids:
        return "First, detect some anomalies to search for similar incidents."
        
    try:
        response = requests.post(f"{API_URL}/similar", json={"positive_ids": ids, "window_sec": window_min * 60}, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        groups = data.get("groups", [])
        if not groups:
            return "No similar past incidents found."

        # Format as a rich Markdown string
        md_output = "## Similar Past Incidents\n\n"
        for group in groups:
            service_name = group['group']
            md_output += f"### 🏛️ Service: `{service_name}`\n"
            
            items_df = pd.DataFrame([{
                "Similarity": f"{item['score']:.4f}",
                "Timestamp": datetime.fromtimestamp(item['payload']['ts']).strftime('%Y-%m-%d %H:%M:%S'),
                "Message": f"```{item['payload']['msg']}```"
            } for item in group['items']])

            md_output += items_df.to_markdown(index=False) + "\n\n"
            
        return md_output

    except requests.exceptions.RequestException as e:
        return f"## API Error\nCould not connect to backend: `{e}`"
    except Exception as e:
        return f"## Error\nAn unexpected error occurred: `{e}`"


# --- Gradio UI Layout ---
with gr.Blocks(theme=gr.themes.Soft(), title="Vector Incident Atlas") as demo:
    gr.Markdown("# 🛰️ Vector Incident Atlas (VIA)")
    gr.Markdown("A semantic log anomaly radar. Detect unusual patterns in recent logs and find similar incidents from the past.")

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 1. Set Time Window")
            window_slider = gr.Slider(minimum=1, maximum=240, value=60, step=1, label="Look back (minutes)")
            detect_btn = gr.Button("Detect Anomalies", variant="primary")
            
        with gr.Column(scale=3):
            gr.Markdown("### 2. Review Anomalies")
            anomalies_output = gr.Markdown("Click 'Detect Anomalies' to begin...")

    gr.Markdown("---")
    
    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 3. Find Similar Incidents")
            gr.Markdown("After detecting anomalies, click here to find historical context.")
            similar_btn = gr.Button("Find Similar Past Incidents", variant="secondary")

        with gr.Column(scale=3):
            gr.Markdown("### 4. Triage Past Incidents")
            similar_output = gr.Markdown("Results will appear here...")

    # Hidden state to store the IDs of detected anomalies
    anomaly_ids_state = gr.State([])

    # Button click events
    detect_btn.click(
        fn=detect_anomalies,
        inputs=[window_slider],
        outputs=[anomalies_output, anomaly_ids_state]
    )
    
    similar_btn.click(
        fn=find_similar,
        inputs=[anomaly_ids_state, window_slider],
        outputs=[similar_output]
    )

demo.launch()