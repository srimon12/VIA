# file: app/schemas/models.py
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

# --- OTel & Log Ingestion ---
class OTelLogAttribute(BaseModel):
    key: str
    value: str

class OTelLogRecord(BaseModel):
    TimeUnixNano: int
    SeverityText: str = "INFO"
    Body: str
    Attributes: List[OTelLogAttribute] = []

# --- Schema Management ---
class SchemaField(BaseModel):
    name: str
    type: str # "datetime", "keyword", "integer", "string"
    source_field: str

class LogSchema(BaseModel):
    id: Optional[int] = None
    source_name: str
    fields: List[SchemaField]

class DetectSchemaRequest(BaseModel):
    source_name: str
    sample_logs: List[str]

# --- Analysis & Querying ---
class AnomalyQuery(BaseModel):
    start_ts: int
    end_ts: int

class RhythmQuery(BaseModel):
    window_sec: int = 300

# --- Feedback & Control Loop ---
class SuppressRequest(BaseModel):
    rhythm_hash: str
    duration_sec: int = 3600

class PatchRequest(BaseModel):
    rhythm_hash: str
    patch_type: str # "ALLOW_LIST"
    context_logs: List[str]

# --- Service Layer Payloads ---
class Tier1Point(BaseModel):
    vector: List[float]
    payload: Dict[str, Any]