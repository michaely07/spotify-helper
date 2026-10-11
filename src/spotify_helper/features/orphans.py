from __future__ import annotations

from collections.abc import Iterable

from ..matching import SongIndex
from ..models import PlaylistItem, Track


def find_orphans(liked: list[Track], playlists: Iterable[list[PlaylistItem]]) -> list[Track]:
    """Liked songs that don't appear (as any version) in any of the given playlists."""
    index = SongIndex(i.track for its in playlists for i in its)
    return [t for t in liked if t.available and index.find(t) is None]
