"""Minimal Last.fm client for tag lookups (https://www.last.fm/api). Personal, non-commercial use only."""

from __future__ import annotations

import threading
import time

import httpx

API = "https://ws.audioscrobbler.com/2.0/"
_RETRYABLE = {8, 11, 16, 29}  # operation failed, service offline, temporarily unavailable, rate limited
_FATAL = {10, 26}  # invalid / suspended API key


class LastFmError(Exception):
    pass


class LastFmClient:
    def __init__(self, api_key: str, http: httpx.Client | None = None, min_interval: float = 0.25, sleep=time.sleep):
        self._key = api_key
        self._http = http or httpx.Client(timeout=20, headers={"User-Agent": "spotify-helper/0.1 (personal tool)"})
        self._min_interval = min_interval
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last = 0.0

    def _throttle(self) -> None:
        with self._lock:
            wait = self._last + self._min_interval - time.monotonic()
            if wait > 0:
                self._sleep(wait)
            self._last = time.monotonic()

    def _call(self, method: str, **params) -> dict:
        query = {"method": method, "api_key": self._key, "format": "json", "autocorrect": "1", **params}
        for attempt in range(5):
            self._throttle()
            try:
                resp = self._http.get(API, params=query)
                data = resp.json()
            except (httpx.HTTPError, ValueError):
                self._sleep(2 ** attempt)
                continue
            code = data.get("error") if isinstance(data, dict) else None
            if code in _FATAL:
                raise LastFmError(f"Last.fm rejected the API key ({data.get('message', code)}). "
                                  "Check LASTFM_API_KEY in .env.")
            if code in _RETRYABLE or resp.status_code >= 500:
                self._sleep(2 ** attempt)
                continue
            if code:
                return {}  # e.g. 6: track/artist not found
            return data
        raise LastFmError("Last.fm is not responding right now. Try again in a few minutes.")

    @staticmethod
    def _tags(data: dict) -> list[tuple[str, int]]:
        tags = (data.get("toptags") or {}).get("tag") or []
        if isinstance(tags, dict):
            tags = [tags]
        return [(t["name"], int(t.get("count") or 0)) for t in tags if t.get("name")]

    def track_tags(self, artist: str, title: str) -> list[tuple[str, int]]:
        return self._tags(self._call("track.gettoptags", artist=artist, track=title))

    def artist_tags(self, artist: str) -> list[tuple[str, int]]:
        return self._tags(self._call("artist.gettoptags", artist=artist))
