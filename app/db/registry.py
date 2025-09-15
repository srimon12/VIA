# file: app/db/registry.py
# Action: Create this new file.

import sqlite3
import logging
from app.core.config import settings

log = logging.getLogger("api.db")

def initialize_registry():
    """
    Initializes the SQLite database and creates necessary tables if they don't exist.
    This function is idempotent.
    """
    log.info(f"Initializing registry database at: {settings.REGISTRY_DB_PATH}")
    try:
        with sqlite3.connect(settings.REGISTRY_DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Table for Dynamic Schemas
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS schemas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_name TEXT NOT NULL UNIQUE,
                schema_json TEXT NOT NULL
            )
            """)

            # Table for the Adaptive Control Loop (Patches)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS patch_registry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rhythm_hash TEXT NOT NULL UNIQUE,
                rule TEXT NOT NULL, -- e.g., 'ALLOW_LIST'
                reason TEXT,
                created_ts INTEGER,
                is_active BOOLEAN DEFAULT 1
            )
            """)
            
            conn.commit()
        log.info("Registry database initialized successfully.")
    except sqlite3.Error as e:
        log.error(f"Database error during initialization: {e}")
        raise

def get_db_connection():
    """Provides a connection to the registry database."""
    conn = sqlite3.connect(settings.REGISTRY_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn