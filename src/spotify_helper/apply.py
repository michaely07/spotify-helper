"""Executes a reviewed ChangePlan against Spotify: verify nothing changed, back up, then write."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .backup import BackupStore
from .models import ChangePlan, Playlist, PlaylistItem


class PlaylistWriter(Protocol):
    def get_playlist(self, pid: str) -> Playlist: ...
    def get_playlist_items(self, pid: str) -> list[PlaylistItem]: ...
    def remove_uris(self, pid: str, uris: list[str]) -> None: ...
    def add_uris(self, pid: str, uris: list[str], position: int | None = None) -> None: ...
    def replace_uris(self, pid: str, uris: list[str]) -> None: ...
    def create_playlist(self, name: str, description: str = "") -> Playlist: ...


class StalePlanError(Exception):
    """The playlist changed in Spotify after the plan was previewed."""


@dataclass
class ApplyResult:
    backup_ids: list[int] = field(default_factory=list)
    created: Playlist | None = None
    messages: list[str] = field(default_factory=list)


def plan_removal(items: list[PlaylistItem], remove_positions: set[int]) -> tuple[list[str], list[tuple[int, list[str]]]]:
    """Translate "remove these positions" into API calls.

    Spotify's remove endpoint deletes every occurrence of a URI, so to drop only some copies we
    remove the URI entirely and re-insert the copies we keep. Returns (uris_to_delete, reinserts)
    where reinserts are (position, uris) runs to apply in order, positions in the final playlist.
    """
    ordered = sorted(items, key=lambda i: i.position)
    doomed = [i for i in ordered if i.position in remove_positions]
    if any(i.track.is_local for i in doomed):
        raise ValueError("Spotify's API cannot remove local files")
    delete = list(dict.fromkeys(i.track.uri for i in doomed if i.track.available))
    deleted = set(delete)

    reinserts: list[tuple[int, list[str]]] = []
    final = [i for i in ordered if i.position not in remove_positions]
    for idx, it in enumerate(final):
        if it.track.uri not in deleted:
            continue
        # Inserting in ascending final position works because every earlier final entry is already present.
        if reinserts and reinserts[-1][0] + len(reinserts[-1][1]) == idx:
            reinserts[-1][1].append(it.track.uri)
        else:
            reinserts.append((idx, [it.track.uri]))
    return delete, reinserts


def apply_plan(plan: ChangePlan, client: PlaylistWriter, backups: BackupStore) -> ApplyResult:
    result = ApplyResult()

    # Phase 1: verify every playlist is unchanged and back it up. No writes until all pass.
    current_items: dict[str, list[PlaylistItem]] = {}
    for change in plan.changes:
        live = client.get_playlist(change.playlist.id)
        if live.snapshot_id != change.playlist.snapshot_id:
            raise StalePlanError(f"“{live.name}” changed in Spotify since this preview. Re-scan and try again.")
        current_items[live.id] = client.get_playlist_items(live.id)
    for change in plan.changes:
        result.backup_ids.append(backups.snapshot(change.playlist, current_items[change.playlist.id], plan.title))

    # Phase 2: write.
    for change in plan.changes:
        pid = change.playlist.id
        if change.replace_with is not None:
            uris = [t.uri for t in change.replace_with if t.available and not t.is_local]
            skipped = len(change.replace_with) - len(uris)
            client.replace_uris(pid, uris)
            if skipped:
                result.messages.append(f"{skipped} local/unavailable track(s) could not be restored to "
                                       f"“{change.playlist.name}”.")
        else:
            delete, reinserts = plan_removal(current_items[pid], {i.position for i in change.remove})
            if delete:
                client.remove_uris(pid, delete)
            for position, uris in reinserts:
                client.add_uris(pid, uris, position=position)
        if change.add:
            client.add_uris(pid, [t.uri for t in change.add if t.available and not t.is_local])
        result.messages.append(_summary(change))

    if plan.create:
        created = client.create_playlist(plan.create.name, plan.create.description)
        uris = [t.uri for t in plan.create.tracks if t.available and not t.is_local]
        if uris:
            client.add_uris(created.id, uris)
        result.created = created
        result.messages.append(f"Created “{created.name}” with {len(uris)} tracks.")
    return result


def _summary(change) -> str:
    name = change.playlist.name
    if change.replace_with is not None:
        return f"Restored “{name}” to {len(change.replace_with)} tracks."
    parts = []
    if change.remove:
        parts.append(f"removed {len(change.remove)}")
    if change.add:
        parts.append(f"added {len(change.add)}")
    return f"“{name}”: {', '.join(parts) or 'no changes'}."
