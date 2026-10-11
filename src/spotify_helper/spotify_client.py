"""The only module that talks to the Spotify Web API.

Uses the post-February-2026 endpoints (/playlists/{id}/items, POST /me/playlists) and tolerates both the
new ("items"/"item") and old ("tracks"/"track") response field names.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator

import httpx

from .models import Playlist, PlaylistItem, Track

API = "https://api.spotify.com/v1"
BATCH = 100  # Spotify's max URIs per add/remove/replace request


class SpotifyError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"Spotify API error {status}: {message}")
        self.status = status


def parse_track(raw: dict | None) -> Track:
    if not raw or not raw.get("uri"):
        return Track(uri="", name="(unavailable track)")
    album = raw.get("album") or {}
    images = album.get("images") or raw.get("images") or []
    artists = raw.get("artists") or ([{"name": raw["show"]["name"]}] if raw.get("show") else [])
    return Track(
        uri=raw["uri"],
        name=raw.get("name") or "(untitled)",
        artists=tuple(a.get("name", "") for a in artists if a),
        album_name=album.get("name", ""),
        album_type=(album.get("album_type") or "").lower(),
        isrc=(raw.get("external_ids") or {}).get("isrc"),
        duration_ms=raw.get("duration_ms") or 0,
        is_local=bool(raw.get("is_local")),
        image_url=images[-1]["url"] if images else None,  # smallest image
    )


def parse_playlist_item(entry: dict, position: int) -> PlaylistItem:
    raw = entry.get("item", entry.get("track"))
    return PlaylistItem(track=parse_track(raw), position=position, added_at=entry.get("added_at") or "")


def parse_playlist(raw: dict) -> Playlist:
    contents = raw.get("items") if isinstance(raw.get("items"), dict) else raw.get("tracks")
    images = raw.get("images") or []
    owner = raw.get("owner") or {}
    return Playlist(
        id=raw["id"],
        name=raw.get("name") or "(untitled)",
        owner_id=owner.get("id", ""),
        owner_name=owner.get("display_name") or owner.get("id", ""),
        snapshot_id=raw.get("snapshot_id", ""),
        total=(contents or {}).get("total", 0),
        collaborative=bool(raw.get("collaborative")),
        public=raw.get("public"),
        image_url=images[-1]["url"] if images else None,
    )


class SpotifyClient:
    def __init__(self, token_provider: Callable[[], str], http: httpx.Client | None = None):
        self._token = token_provider
        self._http = http or httpx.Client(timeout=30)

    # --- plumbing ---------------------------------------------------------
    def _request(self, method: str, url: str, **kwargs) -> dict:
        if not url.startswith("http"):
            url = API + url
        for attempt in range(6):
            resp = self._http.request(method, url, headers={"Authorization": f"Bearer {self._token()}"}, **kwargs)
            if resp.status_code == 429:
                time.sleep(min(int(resp.headers.get("Retry-After", "1")), 30) + 0.5)
                continue
            if resp.status_code >= 500 and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            if resp.status_code >= 400:
                try:
                    message = resp.json().get("error", {}).get("message", resp.text)
                except ValueError:
                    message = resp.text
                raise SpotifyError(resp.status_code, message)
            return resp.json() if resp.content else {}
        raise SpotifyError(429, "rate limited too many times; try again in a minute")

    def _paginate(self, url: str, params: dict | None = None) -> Iterator[dict]:
        page = self._request("GET", url, params=params)
        while True:
            yield from page.get("items", [])
            if not page.get("next"):
                return
            page = self._request("GET", page["next"])

    # --- reads ------------------------------------------------------------
    def current_user_id(self) -> str:
        return self._request("GET", "/me")["id"]

    def get_my_playlists(self) -> list[Playlist]:
        return [parse_playlist(p) for p in self._paginate("/me/playlists", {"limit": 50}) if p]

    def get_playlist(self, pid: str) -> Playlist:
        return parse_playlist(self._request("GET", f"/playlists/{pid}"))

    def get_playlist_items(self, pid: str) -> list[PlaylistItem]:
        entries = self._paginate(f"/playlists/{pid}/items", {"limit": 50, "additional_types": "track,episode"})
        return [parse_playlist_item(e, pos) for pos, e in enumerate(entries)]

    def get_saved_tracks(self) -> list[Track]:
        return [parse_track(e.get("item", e.get("track"))) for e in self._paginate("/me/tracks", {"limit": 50})]

    # --- writes -----------------------------------------------------------
    def remove_uris(self, pid: str, uris: list[str]) -> None:
        """Removes EVERY occurrence of each URI (the API has no per-position removal)."""
        for i in range(0, len(uris), BATCH):
            self._request("DELETE", f"/playlists/{pid}/items", json={"items": [{"uri": u} for u in uris[i:i + BATCH]]})

    def add_uris(self, pid: str, uris: list[str], position: int | None = None) -> None:
        for i in range(0, len(uris), BATCH):
            body: dict = {"uris": uris[i:i + BATCH]}
            if position is not None:
                body["position"] = position + i
            self._request("POST", f"/playlists/{pid}/items", json=body)

    def replace_uris(self, pid: str, uris: list[str]) -> None:
        self._request("PUT", f"/playlists/{pid}/items", json={"uris": uris[:BATCH]})
        if len(uris) > BATCH:
            self.add_uris(pid, uris[BATCH:])

    def create_playlist(self, name: str, description: str = "") -> Playlist:
        raw = self._request("POST", "/me/playlists", json={"name": name, "description": description, "public": False})
        return parse_playlist(raw)
