# In app/services/ingestion_service.py

import logging
import re
import hashlib
import json
from typing import List, Dict, Any

from app.services.qdrant_service import QdrantService
from app.schemas.models import OTelLogRecord
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

    def _get_rhythm_hash(self, log_record: OTelLogRecord) -> str:
        """Creates a composite hash (template + structural + semantic) to categorize a log event."""
        # 1. Template Hash (What it says)
        template = self._get_template(log_record.Body)
        template_hash = hashlib.sha256(template.encode()).hexdigest()[:16]

        # 2. Structural Hash (What it looks like)
        attribute_keys = sorted([attr.key for attr in log_record.Attributes])
        structural_hash = hashlib.sha256(json.dumps(attribute_keys).encode()).hexdigest()[:16]

        # 3. Semantic Hash (What it means)
        embedding = list(self.embed_model.embed([template]))[0]
        # Using a hash of the vector string is a fast way to get a semantic fingerprint
        semantic_hash = hashlib.sha256(str(embedding).encode()).hexdigest()[:16]

        return f"{template_hash}:{structural_hash}:{semantic_hash}"

    def ingest_log_batch(self, logs: List[OTelLogRecord]) -> int:
        points_to_prepare = []
        for raw in logs:
            # Accept either flattened OTelLogRecord or nested OTel resourceLogs shape
            if hasattr(raw, "Body"):  # flattened (our Pydantic model)
                log_record = raw
                attrs = {a.key: a.value for a in log_record.Attributes}
                service = attrs.get("service.name", "unknown")
                ts_s = log_record.TimeUnixNano // 1_000_000_000
                body = log_record.Body
                full_log = raw.model_dump()
            else:
                # nested shape (resourceLogs/scopeLogs/logRecords[0])
                rl = raw["resourceLogs"][0]
                scope = rl["scopeLogs"][0]
                rec = scope["logRecords"][0]
                # service.name from resource.attributes
                rattrs = {a["key"]: list(a["value"].values())[0] for a in rl.get("resource", {}).get("attributes", [])}
                service = rattrs.get("service.name", "unknown")
                ts_s = int(int(rec["timeUnixNano"]) / 1_000_000_000)
                body = rec.get("body", {}).get("stringValue", "")
                # flatten attributes
                attrs = {a["key"]: list(a["value"].values())[0] for a in rec.get("attributes", [])}
                full_log = raw

            points_to_prepare.append({
                "template": self._get_template(body),
                "payload": {
                    "rhythm_hash": self._get_rhythm_hash(
                        # fabricate a minimal OTelLogRecord-like object for hashing
                        type("F", (), {"Body": body, "Attributes": [type("A", (), {"key": k, "value": v}) for k, v in attrs.items()]})()
                    ),
                    "service": service,
                    "ts": ts_s,
                    "severity": "INFO",
                    "body": body,
                    "full_log_json": full_log,
                }
            })
            
        return self.qdrant_service.embed_and_upsert_tier1(points_to_prepare)