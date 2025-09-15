# file: app/services/control_service.py
# Action: Create this new file.

import logging
import time
import sqlite3
from typing import Dict, Set

from app.db.registry import get_db_connection

log = logging.getLogger("api.services.control")

class ControlService:
    """Service for the Adaptive Control Loop (suppression and patching)."""
    def __init__(self):
        # In-memory cache for snoozed anomalies. In production, use Redis.
        self.suppression_cache: Dict[str, int] = {}
        # In-memory set of permanent patches for fast lookups.
        self.patch_registry: Set[str] = self._load_patches()

    def _load_patches(self) -> Set[str]:
        """Loads active ALLOW_LIST patches from the DB into an in-memory set."""
        log.info("Loading patch registry into memory...")
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT rhythm_hash FROM patch_registry WHERE rule = 'ALLOW_LIST' AND is_active = 1")
            rows = cursor.fetchall()
            patches = {row['rhythm_hash'] for row in rows}
            log.info(f"Loaded {len(patches)} active patches.")
            return patches
        finally:
            conn.close()

    def suppress_anomaly(self, rhythm_hash: str, duration_sec: int):
        """Adds a rhythm_hash to the temporary suppression cache."""
        expiry_ts = int(time.time()) + duration_sec
        self.suppression_cache[rhythm_hash] = expiry_ts
        log.info(f"Suppressed rhythm_hash '{rhythm_hash}' for {duration_sec} seconds.")

    def patch_anomaly(self, rhythm_hash: str, reason: str):
        """Adds a permanent ALLOW_LIST patch to the registry DB."""
        conn = get_db_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO patch_registry (rhythm_hash, rule, reason, created_ts, is_active)
                    VALUES (?, 'ALLOW_LIST', ?, ?, 1)
                    ON CONFLICT(rhythm_hash) DO UPDATE SET is_active=1
                    """,
                    (rhythm_hash, reason, int(time.time()))
                )
            # Update in-memory set
            self.patch_registry.add(rhythm_hash)
            log.info(f"Patched rhythm_hash '{rhythm_hash}' as permanently allowed.")
        finally:
            conn.close()

    def is_suppressed_or_patched(self, rhythm_hash: str) -> bool:
        """Checks if a hash is currently suppressed or permanently patched."""
        # Check permanent patch registry first (cheapest)
        if rhythm_hash in self.patch_registry:
            return True
        
        # Check temporary suppression cache
        if rhythm_hash in self.suppression_cache:
            if time.time() < self.suppression_cache[rhythm_hash]:
                return True
            else:
                # Clean up expired entry
                del self.suppression_cache[rhythm_hash]
        
        return False