# file: app/services/promotion_service.py

import logging
from typing import Any, Dict, List

from app.services.qdrant_service import QdrantService

log = logging.getLogger("api.services.promotion")

class PromotionService:
    def __init__(self, qdrant_service: QdrantService) -> None:
        self.qdrant_service = qdrant_service

    async def promote_anomalies(self, anomalies: List[Dict[str, Any]]):
        """
        Transforms Tier-1 anomaly payloads into the structured Tier-2 event format
        and ingests them.
        """
        if not anomalies:
            return

        clusters: Dict[str, List[Dict[str, Any]]] = {}
        for anomaly in anomalies:
            rhash = anomaly["rhythm_hash"]
            clusters.setdefault(rhash, []).append(anomaly)

        events_to_ingest: List[Dict[str, Any]] = []
        for rhash, logs in clusters.items():
            sorted_logs = sorted(logs, key=lambda x: x["ts"])
            start_ts = sorted_logs[0]["ts"]
            end_ts = sorted_logs[-1]["ts"]
            text_for_embedding = sorted_logs[0].get("body", "")

            event_payload = {
                "entity_type": "event_cluster",
                "rhythm_hash": rhash,
                "start_ts": start_ts,
                "end_ts": end_ts,
                "count": len(logs),
                "service": sorted_logs[0].get("service", "unknown"),
                "severity": sorted_logs[0].get("severity", "INFO"),
                "anomaly_type": sorted_logs[0].get("anomaly_type", "unknown"),
                "anomaly_context": sorted_logs[0].get("anomaly_context", ""),
                "body": text_for_embedding,
                "sample_logs": [log["full_log_json"] for log in sorted_logs[:5]],
            }
            
            events_to_ingest.append({
                "text_for_embedding": text_for_embedding,
                "payload": event_payload
            })

        await self.qdrant_service.ingest_to_tier2(events_to_ingest)