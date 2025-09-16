# file: app/api/v1/endpoints/stream.py
import json
from fastapi import APIRouter, HTTPException
from typing import List, Optional, Any, Dict
from collections import deque
import pathlib

router = APIRouter()
LIVE_LOG_FILE = "logs/live_stream.jsonl"

@router.get("/tail")
def tail_log_stream(limit: int = 100, filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """Tails the live log file and returns the last N lines, with optional filtering."""
    log_file = pathlib.Path(LIVE_LOG_FILE)
    if not log_file.exists():
        return []

    try:
        with open(log_file, "r", encoding="utf-8") as f:
            # Efficiently read the last N lines (or more, to account for filtering)
            lines = deque(f, maxlen=limit * 5 if filter else limit)
        
        results = []
        if filter:
            # Filter lines case-insensitively
            for line in lines:
                if filter.lower() in line.lower():
                    results.append(json.loads(line))
        else:
            for line in lines:
                results.append(json.loads(line))
        
        # Return the last 'limit' results
        return results[-limit:]
    except Exception as e:
        # Handle cases where the file might be temporarily unreadable or contains malformed JSON
        raise HTTPException(status_code=500, detail=f"Error reading log file: {e}")