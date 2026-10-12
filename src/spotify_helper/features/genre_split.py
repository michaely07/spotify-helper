from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from ..genres import genre_title
from ..matching import SongIndex
from ..models import ChangePlan, NewPlaylist, Playlist, PlaylistChange, PlaylistItem, Track
from . import new_plan_id


@dataclass
class GenreGroup:
    genre: str
    items: list[PlaylistItem]

    @property
    def title(self) -> str:
        return genre_title(self.genre)


@dataclass
class GenreScan:
    playlist: Playlist
    groups: list[GenreGroup]  # biggest first
    untagged: list[PlaylistItem]


def summarize(playlist: Playlist, items: list[PlaylistItem], genres_for: Callable[[Track], list[str]]) -> GenreScan:
    by_genre: dict[str, list[PlaylistItem]] = defaultdict(list)
    untagged = []
    for it in items:
        if not it.track.available:
            continue
        genres = genres_for(it.track)
        if not genres:
            untagged.append(it)
        for g in genres:
            by_genre[g].append(it)
    groups = sorted((GenreGroup(g, its) for g, its in by_genre.items()), key=lambda g: (-len(g.items), g.genre))
    return GenreScan(playlist=playlist, groups=groups, untagged=untagged)


def default_name(playlist_name: str, genre: str) -> str:
    return f"{playlist_name} – {genre_title(genre)}"


def build_genre_plan(scan: GenreScan, selections: dict[str, str],
                     existing: list[tuple[Playlist, list[PlaylistItem]]]) -> ChangePlan:
    """selections maps genre -> target playlist name; genres sharing a name go into one playlist.

    An owned playlist that already has a target's name is topped up instead of duplicated. The scanned
    playlist itself is never a target.
    """
    groups = {g.genre: g for g in scan.groups}
    targets: dict[str, list[str]] = defaultdict(list)  # name -> genres, in selection order
    for genre, name in selections.items():
        if genre in groups and name.strip():
            targets[name.strip()].append(genre)
    if scan.playlist.name in targets:
        raise ValueError(f"“{scan.playlist.name}” is the playlist being split; choose a different name.")
    owned: dict[str, tuple[Playlist, list[PlaylistItem]]] = {}
    for pl, its in existing:
        if pl.id != scan.playlist.id:
            owned.setdefault(pl.name, (pl, its))

    changes, creates, notes = [], [], []
    for name, genres in targets.items():
        members = {i.position: i for g in genres for i in groups[g].items}
        current = owned.get(name)
        index = SongIndex(i.track for i in current[1]) if current else SongIndex()
        tracks = []
        for pos in sorted(members):
            t = members[pos].track
            if t.is_local or index.find(t):
                continue
            index.add(t)
            tracks.append(t)
        if current:
            if tracks:
                changes.append(PlaylistChange(playlist=current[0], add=tracks))
            else:
                notes.append(f"“{name}” already has all of its tracks.")
        else:
            label = ", ".join(genre_title(g) for g in genres)
            creates.append(NewPlaylist(name=name, description=f"{label} from “{scan.playlist.name}”", tracks=tracks))
    return ChangePlan(
        id=new_plan_id(),
        title=f"Split “{scan.playlist.name}” by genre into {len(targets)} playlist(s)",
        changes=changes, creates=creates, notes=notes,
    )
