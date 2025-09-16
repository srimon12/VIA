# In app/services/ingestion_service.py

import logging
import re
import hashlib
import json
from typing import List, Dict, Any

from app.services.qdrant_service import QdrantService
from fastembed import TextEmbedding
from app.core.config import settings

log = logging.getLogger("api.services.ingestion")

class IngestionService:
    def __init__(self, qdrant_service: QdrantService):
        self.qdrant_service = qdrant_service
        # Initialize a lightweight model for semantic hashing
        self.embed_model = TextEmbedding(settings.TIER_1_EMBED_MODEL, threads=1)

    def _get_template(self, log_body: str) -> str:
        """Strips variables from a log message to create a template."""
        body = re.sub(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', '*', log_body)
        body = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '*', body)
        body = re.sub(r'\b\d+\b', '*', body)
        return body

    def _get_rhythm_hash(self, service: str, severity: str, template: str) -> str:
        """Creates a composite hash (template + structural + semantic) to categorize a log event."""
        template_hash = hashlib.sha256(template.encode()).hexdigest()[:16]

        structural_info = f"{service}:{severity}"
        structural_hash = hashlib.sha256(structural_info.encode()).hexdigest()[:16]

        embedding = list(self.embed_model.embed([template]))[0]
        semantic_hash = hashlib.sha256(str(embedding).encode()).hexdigest()[:16]

        return f"{template_hash}:{structural_hash}:{semantic_hash}"

    async def ingest_log_batch(self, logs: List[Dict[str, Any]]) -> int:
        points_to_prepare = []
        for raw in logs:
            try:
                # Standard OTel-JSON structure from our mock streamer
                rl = raw.get("resourceLogs", [{}])[0]
                scope = rl.get("scopeLogs", [{}])[0]
                rec = scope.get("logRecords", [{}])[0]
                
                rattrs = {a["key"]: list(a["value"].values())[0] for a in rl.get("resource", {}).get("attributes", [])}
                service = rattrs.get("service.name", "unknown")
                severity = rec.get("severityText", "INFO")
                ts_s = int(int(rec["timeUnixNano"]) / 1_000_000_000)
                body = rec.get("body", {}).get("stringValue", "")
            except (KeyError, IndexError, TypeError):
                log.warning(f"Skipping malformed log record: {str(raw)[:200]}")
                continue

            template = self._get_template(body)
            points_to_prepare.append({
                "template": template,
                "payload": {
                    "rhythm_hash": self._get_rhythm_hash(service, severity, template),
                    "service": service,
                    "ts": ts_s,
                    "severity": severity,
                    "body": body,
                    "full_log_json": raw, # Store the original full log object
                }
            })
            
        return await self.qdrant_service.embed_and_upsert_tier1(points_to_prepare)