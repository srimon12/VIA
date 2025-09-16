# file: app/services/schema_service.py
# Action: Create this new file.

import logging
import re
import json
from typing import List, Optional

from app.schemas.models import LogSchema, SchemaField
from app.db.registry import get_db_connection

log = logging.getLogger("api.services.schema")

class SchemaService:
    """Service for detecting, saving, and retrieving log parsing schemas."""

    def detect_schema(self, sample_logs: List[str]) -> Optional[LogSchema]:
        if not sample_logs:
            return None
        
        # Heuristic 1: Try parsing as JSON (OTel nested support)
        try:
            first_line_json = json.loads(sample_logs[0])
            if isinstance(first_line_json, dict):
                # Try OTel nested shape
                rl = (first_line_json.get("resourceLogs") or [{}])[0]
                scope = (rl.get("scopeLogs") or [{}])[0]
                rec = (scope.get("logRecords") or [{}])[0]

                # Extract nested paths with fallbacks
                def _svc(attrs):
                    for a in (attrs or []):
                        if a.get("key") == "service.name":
                            v = a.get("value") or {}
                            # OTel value wrappers: {"stringValue": "..."} etc.
                            return v.get("stringValue") or v.get("intValue") or v.get("doubleValue") or v.get("boolValue")
                    return None

                service_guess = _svc((rl.get("resource") or {}).get("attributes"))
                # Build a canonical schema we use everywhere in VIA
                fields = [
                    SchemaField(name="timestamp", type="datetime", source_field="resourceLogs[0].scopeLogs[0].logRecords[0].timeUnixNano"),
                    SchemaField(name="level",     type="keyword",  source_field="resourceLogs[0].scopeLogs[0].logRecords[0].severityText"),
                    SchemaField(name="service",   type="keyword",  source_field="resourceLogs[0].resource.attributes[service.name]"),
                    SchemaField(name="message",   type="string",   source_field="resourceLogs[0].scopeLogs[0].logRecords[0].body.stringValue"),
                ]
                return LogSchema(source_name="", fields=fields)
        except (json.JSONDecodeError, TypeError): pass  # Not JSON, continue
                
        # Heuristic 2: BGL-style fixed position
        bgl_detect_pattern = re.compile(
            r"^(?P<label>-|\d+)\s+(?P<unix_ts>\d+)\s+(?P<date>\S+)\s+(?P<node>\S+)\s+"
            r"(?P<time>\S+)\s+(?P<device>\S+)\s+(?P<component>RAS)\s+(?P<sub_component>\w+)\s+"
            r"(?P<level>\w+)\s+(?P<message>.*)$"
        )
        match = bgl_detect_pattern.match(sample_logs[0].strip())
        if match:            
            fields = [
                SchemaField(name="timestamp", type="datetime", source_field="unix_ts"),
                SchemaField(name="level", type="keyword", source_field="level"),
                SchemaField(name="service", type="keyword", source_field="node"),
                SchemaField(name="message", type="string", source_field="message"),
            ]
            return LogSchema(source_name="", fields=fields)
        
        
        return None

    def save_schema(self, schema: LogSchema) -> LogSchema:
        conn = get_db_connection()
        try:
            with conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO schemas (source_name, schema_json) VALUES (?, ?)
                    ON CONFLICT(source_name) DO UPDATE SET schema_json=excluded.schema_json
                    """,
                    (schema.source_name, schema.model_dump_json()),
                )
                schema.id = cursor.lastrowid or schema.id
            return schema
        finally:
            conn.close()

    def get_schema(self, source_name: str) -> Optional[LogSchema]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT schema_json FROM schemas WHERE source_name = ?', (source_name,))
            row = cursor.fetchone()
            if row:
                return LogSchema.model_validate_json(row["schema_json"])
            return None
        finally:
            conn.close()