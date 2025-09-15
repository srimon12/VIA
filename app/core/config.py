# In app/core/config.py

from pydantic_settings import BaseSettings
import pathlib

class Settings(BaseSettings):
    """
    Centralized application configuration.
    Values are loaded from environment variables (e.g., from a .env file).
    """
    # Qdrant Configuration
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    
    # Collection Name Prefixes (for time-partitioning)
    TIER_1_COLLECTION_PREFIX: str = "via_rhythm_monitor"
    TIER_2_COLLECTION_PREFIX: str = "via_forensic_index"

    # Embedding Model Configuration
    TIER_1_EMBED_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    TIER_2_EMBED_MODEL: str = "BAAI/bge-small-en-v1.5"
    
    # Database path for schemas and patches
    REGISTRY_DB_PATH: str = "registry.db"

    # --- ADD THESE MISSING FIELDS FROM YOUR .env ---
    BGL_LOG_PATH: str = "logs/telemetry_logs.jsonl"
    INGESTOR_URL: str = "http://localhost:8000/api/v1/ingest/stream"
    STREAM_INTERVAL_SEC: int = 2
    STREAM_BATCH_SIZE: int = 50
    
    # These fields below seem to be from an older config. 
    # Add them if they are still in your .env to prevent errors,
    # but we should consider removing them from the .env file later if they are unused.
    QDRANT_URL: str = "localhost:6333" 
    MODEL: str = "BAAI/bge-small-en-v1.5"
    STREAMER_HOST: str = "localhost"
    QUANTIZE: str = "1"


    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()