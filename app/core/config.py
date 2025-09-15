# file: app/core/config.py
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
    
    # New: Database path for schemas and patches
    REGISTRY_DB_PATH: str = "registry.db"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()