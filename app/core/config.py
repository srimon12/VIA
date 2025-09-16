# file: app/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """
    Centralized application configuration.
    Values are loaded from environment variables (e.g., from a .env file).
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra='ignore'
    )

    # --- Qdrant Cluster Configuration ---
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    
    QDRANT_REPLICATION_FACTOR: int = 2
    QDRANT_SHARD_NUMBER: int = 2
    
    # --- Collection & Model Configuration ---
    TIER_1_COLLECTION_PREFIX: str = "via_rhythm_monitor_v2"
    TIER_2_COLLECTION_PREFIX: str = "via_forensic_index_v2"

    TIER_1_EMBED_MODEL: str = "BAAI/bge-small-en-v1.5"
    TIER_2_EMBED_MODEL: str = "BAAI/bge-small-en-v1.5"

    # --- Database Path for Registries ---
    REGISTRY_DB_PATH: str = "registry.db"


# Create a single settings instance to be used throughout the application
settings = Settings()