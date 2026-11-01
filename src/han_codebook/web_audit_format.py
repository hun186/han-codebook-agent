"""Read per-run SQLite audit events without opening other project resources."""
from __future__ import annotations
import json
from pathlib import Path
import sqlite3
from typing import Any


def read_audit_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.is_symlink() or not path.is_file():
        raise ValueError("Audit file must be a regular file")
    if path.stat().st_size > 48 * 1024 * 1024:
        raise ValueError("Audit file exceeds diagnostic size cap")
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as db:
        rows = db.execute(
            "SELECT at_utc, round, stage, payload_json FROM events ORDER BY id"
        ).fetchall()
    return [{"at": stamp, "round": num, "stage": stage,
             "payload": json.loads(body)}
            for stamp, num, stage, body in rows]
