# file: app/services/ingestion_service.py
# Action: Create this new file.

import logging
import re
import hashlib
from typing import List, Dict, Any

from app.services.qdrant_service import QdrantService
from app.schemas.models import OTelLogRecord

log = logging.getLogger("api.services.ingestion")

class IngestionService:
    def __init__(self, qdrant_service: QdrantService):
        self.qdrant_service = qdrant_service

    def _get_template(self, log_body: str) -> str:
        """Strips variables from a log message to create a template."""
        body = re.sub(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', '*', log_body)
        body = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '*', body)
        body = re.sub(r'\b\d+\b', '*', body)
        return body

    def _get_rhythm_hash(self, log_body: str) -> str:
        """Creates a composite hash to categorize a log event."""
        template = self._get_template(log_body)
        return hashlib.sha256(template.encode()).hexdigest()

    def ingest_log_batch(self, logs: List[OTelLogRecord]) -> int:
        """Processes a batch of logs for Tier 1 ingestion."""
        points_to_prepare = []
        for log_record in logs:
            log_body = log_record.Body
            template = self._get_template(log_body)
            
            points_to_prepare.append({
                "template": template,
                "payload": {
                    "rhythm_hash": self._get_rhythm_hash(log_body),
                    "service": next((attr.value for attr in log_record.Attributes if attr.key == "service.name"), "unknown"),
                    "ts": log_record.TimeUnixNano // 1_000_000_000,
                    "severity": log_record.SeverityText,
                    "full_log_json": log_record.model_dump_json(),
                }
            })
        
        return self.qdrant_service.embed_and_upsert_tier1(points_to_prepare)