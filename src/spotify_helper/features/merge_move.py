from __future__ import annotations

from ..matching import SongIndex
from ..models import ChangePlan, NewPlaylist, Playlist, PlaylistChange, PlaylistItem
from . import new_plan_id


def build_merge_plan(name: str, sources: list[tuple[Playlist, list[PlaylistItem]]]) -> ChangePlan:
    seen = SongIndex()
    tracks, skipped = [], 0
    for _, its in sources:
        for it in its:
            if not it.track.available or it.track.is_local:
                continue
            if seen.find(it.track):
                skipped += 1
                continue
            seen.add(it.track)
            tracks.append(it.track)
    source_names = ", ".join(pl.name for pl, _ in sources)
    return ChangePlan(
        id=new_plan_id(),
        title=f"Merge {len(sources)} playlists into “{name}”",
        creates=[NewPlaylist(name=name, description=f"Merged from: {source_names}", tracks=tracks)],
        notes=[f"{skipped} duplicate track(s) skipped."] if skipped else [],
    )


def build_move_plan(src: Playlist, src_items: list[PlaylistItem], positions: set[int],
                    dst: Playlist, dst_items: list[PlaylistItem]) -> ChangePlan:
    moving = [i for i in src_items if i.position in positions and i.track.available and not i.track.is_local]
    dst_index = SongIndex(i.track for i in dst_items)
    to_add = []
    for it in moving:
        if not dst_index.find(it.track):
            dst_index.add(it.track)
            to_add.append(it.track)
    already = len(moving) - len(to_add)
    return ChangePlan(
        id=new_plan_id(),
        title=f"Move {len(moving)} tracks from “{src.name}” to “{dst.name}”",
        changes=[PlaylistChange(playlist=src, remove=moving), PlaylistChange(playlist=dst, add=to_add)],
        notes=[f"{already} track(s) were already in “{dst.name}” and won't be added again."] if already else [],
    )
