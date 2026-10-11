from __future__ import annotations

from ..matching import SongIndex, Tier
from ..models import Playlist, PlaylistItem


def overlap_matrix(playlists: list[tuple[Playlist, list[PlaylistItem]]]) -> list[list[int]]:
    """m[i][j] = how many tracks of playlist i are also in playlist j (the diagonal is i's size)."""
    indexes = [SongIndex(i.track for i in its) for _, its in playlists]
    matrix = []
    for i, (_, its) in enumerate(playlists):
        available = [it for it in its if it.track.available]
        row = [len(available) if i == j else sum(1 for it in available if idx.find(it.track))
               for j, idx in enumerate(indexes)]
        matrix.append(row)
    return matrix


def shared_tracks(a: list[PlaylistItem], b: list[PlaylistItem]) -> list[tuple[PlaylistItem, Tier]]:
    index = SongIndex(i.track for i in b)
    return [(it, tier) for it in a if (tier := index.find(it.track)) is not None]
