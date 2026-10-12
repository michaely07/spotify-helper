"""SQLite cache: playlist contents keyed by Spotify's snapshot_id (so unchanged playlists aren't re-downloaded),
liked songs, and Last.fm tags. Scans run in a background thread, so every query holds the lock."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .db import connect
from .models import PlaylistItem, Track


class Cache:
    def __init__(self, path: str | Path):
        self._lock = threading.Lock()
        self._conn = connect(path)
        self._conn.executescript(
            """CREATE TABLE IF NOT EXISTS playlist_items (
                   playlist_id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL, items_json TEXT NOT NULL);
               CREATE TABLE IF NOT EXISTS liked (
                   id INTEGER PRIMARY KEY CHECK (id = 1), fetched_at TEXT NOT NULL, tracks_json TEXT NOT NULL);
               CREATE TABLE IF NOT EXISTS lastfm_tags (
                   kind TEXT NOT NULL, key TEXT NOT NULL, fetched_at TEXT NOT NULL, tags_json TEXT NOT NULL,
                   PRIMARY KEY (kind, key));"""
        )

    def get_items(self, playlist_id: str, snapshot_id: str) -> list[PlaylistItem] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT items_json FROM playlist_items WHERE playlist_id = ? AND snapshot_id = ?",
                (playlist_id, snapshot_id),
            ).fetchone()
        return [PlaylistItem.from_dict(d) for d in json.loads(row["items_json"])] if row else None

    def put_items(self, playlist_id: str, snapshot_id: str, items: list[PlaylistItem]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO playlist_items VALUES (?, ?, ?)",
                (playlist_id, snapshot_id, json.dumps([i.to_dict() for i in items])),
            )
            self._conn.commit()

    def get_liked(self) -> tuple[str, list[Track]] | None:
        with self._lock:
            row = self._conn.execute("SELECT fetched_at, tracks_json FROM liked WHERE id = 1").fetchone()
        return (row["fetched_at"], [Track.from_dict(d) for d in json.loads(row["tracks_json"])]) if row else None

    def put_liked(self, tracks: list[Track]) -> str:
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO liked VALUES (1, ?, ?)",
                               (fetched_at, json.dumps([t.to_dict() for t in tracks])))
            self._conn.commit()
        return fetched_at

    def get_tags(self, kind: str, key: str, max_age_days: int) -> list[tuple[str, int]] | None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat(timespec="seconds")
        with self._lock:
            row = self._conn.execute(
                "SELECT tags_json FROM lastfm_tags WHERE kind = ? AND key = ? AND fetched_at > ?", (kind, key, cutoff)
            ).fetchone()
        return [(n, w) for n, w in json.loads(row["tags_json"])] if row else None

    def put_tags(self, kind: str, key: str, tags: list[tuple[str, int]]) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO lastfm_tags VALUES (?, ?, ?, ?)",
                               (kind, key, datetime.now(timezone.utc).isoformat(timespec="seconds"), json.dumps(tags)))
            self._conn.commit()
