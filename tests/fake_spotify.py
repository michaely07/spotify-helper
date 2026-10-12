"""In-memory stand-in for SpotifyClient that mimics the real API's write semantics."""

from spotify_helper.models import Playlist, PlaylistItem, Track


class FakeSpotifyClient:
    def __init__(self, user_id="me"):
        self.user_id = user_id
        self.meta: dict[str, Playlist] = {}
        self.tracks: dict[str, list[Track]] = {}
        self.liked: list[Track] = []
        self.calls: list[tuple] = []
        self._version = 0
        self._frozen_list: list[Playlist] | None = None

    # --- setup helpers -------------------------------------------------
    def put(self, pl: Playlist, tracks: list[Track]) -> Playlist:
        self.meta[pl.id] = pl
        self.tracks[pl.id] = list(tracks)
        return self._touch(pl.id)

    def _touch(self, pid: str) -> Playlist:
        self._version += 1
        old = self.meta[pid]
        self.meta[pid] = Playlist(**{**old.__dict__, "snapshot_id": f"v{self._version}",
                                     "total": len(self.tracks[pid])})
        return self.meta[pid]

    def lag_playlist_list(self) -> None:
        """Mimic Spotify: GET /me/playlists keeps returning this moment's metadata for a while after writes."""
        self._frozen_list = list(self.meta.values())

    def uris(self, pid: str) -> list[str]:
        return [t.uri for t in self.tracks[pid]]

    # --- client interface ----------------------------------------------
    def current_user_id(self) -> str:
        return self.user_id

    def get_my_playlists(self) -> list[Playlist]:
        return list(self._frozen_list if self._frozen_list is not None else self.meta.values())

    def get_playlist(self, pid: str) -> Playlist:
        self.calls.append(("get_playlist", pid))
        return self.meta[pid]

    def get_playlist_items(self, pid: str) -> list[PlaylistItem]:
        self.calls.append(("get_playlist_items", pid))
        return [PlaylistItem(t, i, f"2024-01-01T00:00:{i:02d}Z") for i, t in enumerate(self.tracks[pid])]

    def get_saved_tracks(self) -> list[Track]:
        return list(self.liked)

    def remove_uris(self, pid: str, uris: list[str]) -> None:
        # Real API: removes EVERY occurrence of each URI.
        self.calls.append(("remove_uris", pid, list(uris)))
        gone = set(uris)
        self.tracks[pid] = [t for t in self.tracks[pid] if t.uri not in gone]
        self._touch(pid)

    def add_uris(self, pid: str, uris: list[str], position: int | None = None) -> None:
        self.calls.append(("add_uris", pid, list(uris), position))
        new = [self._lookup(u) for u in uris]
        lst = self.tracks[pid]
        if position is None:
            lst.extend(new)
        else:
            lst[position:position] = new
        self._touch(pid)

    def replace_uris(self, pid: str, uris: list[str]) -> None:
        self.calls.append(("replace_uris", pid, list(uris)))
        self.tracks[pid] = [self._lookup(u) for u in uris]
        self._touch(pid)

    def create_playlist(self, name: str, description: str = "") -> Playlist:
        self.calls.append(("create_playlist", name))
        pid = f"new{len(self.meta)}"
        return self.put(Playlist(id=pid, name=name, owner_id=self.user_id), [])

    def _lookup(self, uri: str) -> Track:
        for lst in self.tracks.values():
            for t in lst:
                if t.uri == uri:
                    return t
        return Track(uri=uri, name=uri)
