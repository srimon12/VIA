# In app/services/control_service.py

import logging
import time
import sqlite3
from typing import Dict, Set, List, Any
import json
import pathlib
import yaml # Add this import

from app.db.registry import get_db_connection

log = logging.getLogger("api.services.control")

class ControlService:
    """Service for the Adaptive Control Loop (suppression and patching)."""
    def __init__(self):
        self.suppression_cache: Dict[str, int] = {}
        self.patch_registry: Set[str] = self._load_patches()
        self.evals_dir = pathlib.Path("evals")
        self.evals_dir.mkdir(exist_ok=True)

    def _load_patches(self) -> Set[str]:
        # ... (this method remains the same)
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

    def _generate_eval_case(self, rhythm_hash: str, context_logs: List[str]):
        """Generates a YAML file for a regression test case."""
        eval_data = {
            "description": f"Auto-generated eval case for patched rhythm_hash.",
            "rhythm_hash": rhythm_hash,
            "context_logs": context_logs,
            "expected_outcome": {
                "is_anomaly": False,
                "reason": "This hash was patched as a false positive by an operator."
            }
        }
        
        # Use first 12 chars of hash and timestamp for a unique filename
        filename = f"eval_{rhythm_hash[:12]}_{int(time.time())}.yml"
        filepath = self.evals_dir / filename
        
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                yaml.dump(eval_data, f, default_flow_style=False, sort_keys=False)
            log.info(f"Successfully generated eval case: {filepath}")
        except Exception as e:
            log.error(f"Failed to generate eval case for hash {rhythm_hash}: {e}")

    def suppress_anomaly(self, rhythm_hash: str, duration_sec: int):
        # ... (this method remains the same)
        expiry_ts = int(time.time()) + duration_sec
        self.suppression_cache[rhythm_hash] = expiry_ts
        log.info(f"Suppressed rhythm_hash '{rhythm_hash}' for {duration_sec} seconds.")

    def patch_anomaly(self, rhythm_hash: str, reason: str, context_logs: List[str]):
        """Adds a permanent ALLOW_LIST patch and generates an eval case."""
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
            self.patch_registry.add(rhythm_hash)
            log.info(f"Patched rhythm_hash '{rhythm_hash}' as permanently allowed.")
            
            # --- NEW: Generate the eval case ---
            if context_logs:
                self._generate_eval_case(rhythm_hash, context_logs)

        finally:
            conn.close()

    def is_suppressed_or_patched(self, rhythm_hash: str) -> bool:
        # ... (this method remains the same)
        if rhythm_hash in self.patch_registry:
            return True
        if rhythm_hash in self.suppression_cache:
            if time.time() < self.suppression_cache[rhythm_hash]:
                return True
            else:
                del self.suppression_cache[rhythm_hash]
        return False

    def get_all_rules(self) -> Dict[str, Any]:
        """Returns all active patches and temporary suppressions."""
        # Get permanent patches from the database
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT rhythm_hash, reason, created_ts FROM patch_registry WHERE is_active = 1")
            patches = [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

        # Get temporary suppressions from the in-memory cache
        now = int(time.time())
        suppressions = [
            {"rhythm_hash": h, "expires_at": ts}
            for h, ts in self.suppression_cache.items() if ts > now
        ]
        
        return {"patches": patches, "suppressions": suppressions}

    def delete_patch(self, rhythm_hash: str) -> None:
        """Deactivates a permanent patch in the database."""
        conn = get_db_connection()
        try:
            with conn:
                conn.execute("UPDATE patch_registry SET is_active = 0 WHERE rhythm_hash = ?", (rhythm_hash,))
            if rhythm_hash in self.patch_registry:
                self.patch_registry.remove(rhythm_hash)
            log.info(f"Deactivated patch for rhythm_hash '{rhythm_hash}'.")
        finally:
            conn.close()

    def delete_suppression(self, rhythm_hash: str) -> None:
        """Removes a temporary suppression from the cache."""
        if rhythm_hash in self.suppression_cache:
            del self.suppression_cache[rhythm_hash]
            log.info(f"Removed suppression for rhythm_hash '{rhythm_hash}'.")