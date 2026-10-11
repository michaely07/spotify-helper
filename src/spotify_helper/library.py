"""Read access to the user's library, with snapshot-aware caching. Writes go through apply.py."""

from __future__ import annotations

from .cache import Cache
from .models import Playlist, PlaylistItem, Track


class Library:
    def __init__(self, client, cache: Cache):
        self.client = client
        self.cache = cache
        self._user_id: str | None = None

    @property
    def user_id(self) -> str:
        if self._user_id is None:
            self._user_id = self.client.current_user_id()
        return self._user_id

    def forget_user(self) -> None:
        self._user_id = None

    def playlists(self) -> list[Playlist]:
        return self.client.get_my_playlists()

    def editable_playlists(self) -> list[Playlist]:
        """Playlists whose contents Spotify will show us (owned or collaborative)."""
        return [p for p in self.playlists() if p.editable_by(self.user_id)]

    def playlist(self, pid: str) -> Playlist:
        return self.client.get_playlist(pid)

    def items(self, playlist: Playlist) -> list[PlaylistItem]:
        cached = self.cache.get_items(playlist.id, playlist.snapshot_id)
        if cached is not None:
            return cached
        fetched = self.client.get_playlist_items(playlist.id)
        self.cache.put_items(playlist.id, playlist.snapshot_id, fetched)
        return fetched

    def liked(self, refresh: bool = False) -> tuple[str, list[Track]]:
        cached = None if refresh else self.cache.get_liked()
        if cached is not None:
            return cached
        tracks = self.client.get_saved_tracks()
        return self.cache.put_liked(tracks), tracks
