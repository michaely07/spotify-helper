from spotify_helper.models import Playlist, PlaylistItem, Track

_counter = iter(range(10_000_000))


def track(name="Song", artists=("Artist",), *, uri=None, isrc=None, duration_ms=200_000,
          album_type="album", album_name="Album", is_local=False) -> Track:
    return Track(
        uri=uri if uri is not None else f"spotify:track:t{next(_counter)}",
        name=name,
        artists=tuple(artists),
        album_name=album_name,
        album_type=album_type,
        isrc=isrc,
        duration_ms=duration_ms,
        is_local=is_local,
    )


def items(*tracks: Track, added=None) -> list[PlaylistItem]:
    """Wrap tracks as playlist items at positions 0..n-1, added on consecutive days unless given."""
    return [
        PlaylistItem(track=t, position=i, added_at=(added[i] if added else f"2024-01-{i + 1:02d}T00:00:00Z"))
        for i, t in enumerate(tracks)
    ]


def playlist(pid="p1", name=None, owner="me", **kw) -> Playlist:
    return Playlist(id=pid, name=name or pid, owner_id=owner, snapshot_id=kw.pop("snapshot_id", "s1"), **kw)
