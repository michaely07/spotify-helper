from __future__ import annotations

from dataclasses import dataclass

from ..matching import Tier, group_duplicates, match_tier
from ..models import ChangePlan, Playlist, PlaylistChange, PlaylistItem
from . import new_plan_id

_ALBUM_TYPE_RANK = {"album": 0, "single": 1, "compilation": 2}


@dataclass
class DuplicateGroup:
    members: list[PlaylistItem]
    keeper: PlaylistItem  # suggested copy to keep
    tiers: dict[int, Tier]  # position -> how each other copy matches the keeper

    @property
    def tier(self) -> Tier:
        """Confidence of the whole group is that of its weakest match."""
        return max(self.tiers.values())


def _keeper_rank(item: PlaylistItem):
    return _ALBUM_TYPE_RANK.get(item.track.album_type, 3), item.added_at or "~", item.position


def find_duplicates(items: list[PlaylistItem]) -> list[DuplicateGroup]:
    groups = []
    for members in group_duplicates(items):
        keeper = min(members, key=_keeper_rank)
        # Members joined only transitively (A~B, B~C) have no direct tier to the keeper; call them LIKELY.
        tiers = {m.position: match_tier(keeper.track, m.track) or Tier.LIKELY for m in members if m is not keeper}
        groups.append(DuplicateGroup(members=members, keeper=keeper, tiers=tiers))
    return groups


def build_dedupe_plan(playlist: Playlist, groups: list[DuplicateGroup], keep: dict[int, int],
                      include: set[int]) -> ChangePlan:
    """keep maps group index -> position to keep (defaults to the suggested keeper); include picks groups."""
    remove = []
    for gi in sorted(include):
        group = groups[gi]
        keep_pos = keep.get(gi, group.keeper.position)
        if keep_pos not in {m.position for m in group.members}:
            keep_pos = group.keeper.position  # never remove every copy
        remove += [m for m in group.members if m.position != keep_pos and not m.track.is_local]
    return ChangePlan(
        id=new_plan_id(),
        title=f"Remove duplicates from “{playlist.name}”",
        changes=[PlaylistChange(playlist=playlist, remove=sorted(remove, key=lambda i: i.position))],
    )
