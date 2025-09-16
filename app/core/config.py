# file: app/core/config.py
# Action: Replace the entire file with this content.

from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """
    Centralized application configuration.
    Values are loaded from environment variables (e.g., from a .env file).
    """
    # --- Qdrant Cluster Configuration ---
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    
    # CRITICAL: These must match your docker-compose setup for a cluster
    QDRANT_REPLICATION_FACTOR: int = 2 # Must be <= number of nodes
    QDRANT_SHARD_NUMBER: int = 2       # Should ideally be a multiple of node count
    
    # --- Collection & Model Configuration ---
    TIER_1_COLLECTION_PREFIX: str = "via_rhythm_monitor_v2"
    TIER_2_COLLECTION_PREFIX: str = "via_forensic_index_v2"

    TIER_1_EMBED_MODEL: str = "BAAI/bge-small-en-v1.5" 
    TIER_2_EMBED_MODEL: str = "BAAI/bge-small-en-v1.5"


    # --- Database Path for Registries ---
    REGISTRY_DB_PATH: str = "registry.db"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

# Create a single settings instance to be used throughout the application
settings = Settings()