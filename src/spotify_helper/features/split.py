from __future__ import annotations

from dataclasses import dataclass, field

from ..matching import SongIndex, Tier
from ..models import ChangePlan, Playlist, PlaylistChange, PlaylistItem
from . import new_plan_id


@dataclass
class SplitRow:
    item: PlaylistItem
    matches: list[tuple[Playlist, Tier]] = field(default_factory=list)


@dataclass
class SplitResult:
    rows: list[SplitRow]

    @property
    def placed(self) -> list[SplitRow]:
        return [r for r in self.rows if r.matches]

    @property
    def leftovers(self) -> list[SplitRow]:
        return [r for r in self.rows if not r.matches]


def analyze_split(big: list[PlaylistItem], targets: list[tuple[Playlist, list[PlaylistItem]]]) -> SplitResult:
    indexes = [(pl, SongIndex(i.track for i in its)) for pl, its in targets]
    rows = []
    for item in big:
        if not item.track.available:
            continue
        matches = [(pl, tier) for pl, idx in indexes if (tier := idx.find(item.track)) is not None]
        rows.append(SplitRow(item=item, matches=matches))
    return SplitResult(rows=rows)


def build_split_plan(big_playlist: Playlist, big: list[PlaylistItem], positions: set[int]) -> ChangePlan:
    remove = [i for i in big if i.position in positions and not i.track.is_local]
    return ChangePlan(
        id=new_plan_id(),
        title=f"Remove already-sorted tracks from “{big_playlist.name}”",
        changes=[PlaylistChange(playlist=big_playlist, remove=remove)],
    )
