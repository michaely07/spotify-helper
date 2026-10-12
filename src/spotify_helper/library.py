"""Read access to the user's library, with snapshot-aware caching. Writes go through apply.py."""

from __future__ import annotations

from .cache import Cache
from .models import Playlist, PlaylistItem, Track


class Library:
    def __init__(self, client, cache: Cache):
        self.client = client
        self.cache = cache
        self._user_id: str | None = None
        # Spotify's playlist list (GET /me/playlists) lags behind writes for a while, while GET /playlists/{id}
        # is current. After our own writes we keep the fresh metadata here, along with the snapshot ids the
        # list may still report, and use it until the list catches up.
        self._recent: dict[str, tuple[set[str], Playlist]] = {}

    @property
    def user_id(self) -> str:
        if self._user_id is None:
            self._user_id = self.client.current_user_id()
        return self._user_id

    def forget_user(self) -> None:
        self._user_id = None

    def remember_write(self, before: Playlist | None, after: Playlist) -> None:
        stale = self._recent.get(after.id, (set(), after))[0]
        if before is not None and before.snapshot_id != after.snapshot_id:
            stale = stale | {before.snapshot_id}
        self._recent[after.id] = (stale, after)

    def playlists(self) -> list[Playlist]:
        listed = self.client.get_my_playlists()
        result = []
        for p in listed:
            recent = self._recent.get(p.id)
            if recent and p.snapshot_id in recent[0]:
                p = recent[1]  # list is still behind our write
            elif recent:
                del self._recent[p.id]  # list caught up (or the playlist changed elsewhere since)
            result.append(p)
        listed_ids = {p.id for p in listed}
        just_created = [after for pid, (_, after) in self._recent.items() if pid not in listed_ids]
        return just_created + result

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
