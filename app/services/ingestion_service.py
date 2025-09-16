# In file: app/services/ingestion_service.py
import logging
import re
import hashlib
from typing import List, Dict, Any
from simhash import Simhash # NEW: Import Simhash

from app.services.qdrant_service import QdrantService

log = logging.getLogger("api.services.ingestion")

class IngestionService:
    def __init__(self, qdrant_service: QdrantService):
        self.qdrant_service = qdrant_service

    def _get_template(self, log_body: str) -> str:
        # ... (this function is unchanged) ...
        body = re.sub(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', '*', log_body)
        body = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '*', body)
        body = re.sub(r'\b\d+\b', '*', body)
        return body

    def _get_rhythm_hash(self, service: str, severity: str, template: str) -> str:
        # ... (this function is unchanged) ...
        template_hash = hashlib.sha256(template.encode()).hexdigest()[:16]
        structural_info = f"{service}:{severity}"
        structural_hash = hashlib.sha256(structural_info.encode()).hexdigest()[:16]
        return f"{template_hash}:{structural_hash}"

    # NEW: Function to generate the 64-dim binary vector from a log template
    def _get_semantic_vector(self, template: str) -> List[float]:
        """
        Generates a 64-bit Simhash and converts it to a 64-dimensional
        binary vector {0.0, 1.0} for Qdrant.
        """
        # Simhash is fast and great for capturing semantic similarity of text.
        sh = Simhash(template, f=64).value
        # Convert the 64-bit integer into a 64-element list of floats
        return [float((sh >> i) & 1) for i in range(64)]

    async def ingest_log_batch(self, logs: List[Dict[str, Any]]) -> int:
        points_to_prepare = []
        for raw in logs:
            try:
                # ... (parsing logic is unchanged) ...
                rl = raw.get("resourceLogs", [{}])[0]
                scope = rl.get("scopeLogs", [{}])[0]
                rec = scope.get("logRecords", [{}])[0]
                rattrs = {a["key"]: list(a["value"].values())[0] for a in rl.get("resource", {}).get("attributes", [])}
                service = rattrs.get("service.name", "unknown")
                severity = rec.get("severityText", "INFO")
                ts_s = int(int(rec["timeUnixNano"]) / 1_000_000_000)
                body = rec.get("body", {}).get("stringValue", "")

                template = self._get_template(body)
                
                # MODIFIED: Prepare the point with the new semantic vector
                points_to_prepare.append({
                    "vector": self._get_semantic_vector(template), # Add the vector
                    "payload": {
                        "rhythm_hash": self._get_rhythm_hash(service, severity, template),
                        "service": service,
                        "ts": ts_s,
                        "severity": severity,
                        "body": body,
                        "full_log_json": raw,
                    }
                })
            except (KeyError, IndexError, TypeError):
                log.warning(f"Skipping malformed log record: {str(raw)[:200]}")
                continue
        
        # Call the updated qdrant service function
        return await self.qdrant_service.upsert_tier1_points(points_to_prepare)