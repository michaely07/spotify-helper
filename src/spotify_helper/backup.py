"""Snapshots of playlist contents, taken automatically before every write so any change can be undone."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .db import connect
from .models import Playlist, PlaylistItem


@dataclass(frozen=True)
class BackupMeta:
    id: int
    playlist_id: str
    playlist_name: str
    created_at: str
    reason: str
    track_count: int


class BackupStore:
    def __init__(self, path: str | Path):
        self._lock = threading.Lock()
        self._conn = connect(path)
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS backups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_id TEXT NOT NULL,
                playlist_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                reason TEXT NOT NULL,
                track_count INTEGER NOT NULL,
                items_json TEXT NOT NULL
            )"""
        )
        self._conn.commit()

    def snapshot(self, playlist: Playlist, items: list[PlaylistItem], reason: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO backups (playlist_id, playlist_name, created_at, reason, track_count, items_json)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (playlist.id, playlist.name, datetime.now(timezone.utc).isoformat(timespec="seconds"), reason,
                 len(items), json.dumps([i.to_dict() for i in items])),
            )
            self._conn.commit()
            return cur.lastrowid

    def list(self) -> list[BackupMeta]:
        rows = self._conn.execute(
            "SELECT id, playlist_id, playlist_name, created_at, reason, track_count FROM backups ORDER BY id DESC"
        ).fetchall()
        return [BackupMeta(**dict(r)) for r in rows]

    def get(self, backup_id: int) -> tuple[BackupMeta, list[PlaylistItem]]:
        row = self._conn.execute("SELECT * FROM backups WHERE id = ?", (backup_id,)).fetchone()
        if row is None:
            raise KeyError(backup_id)
        data = dict(row)
        items = [PlaylistItem.from_dict(d) for d in json.loads(data.pop("items_json"))]
        return BackupMeta(**data), items
