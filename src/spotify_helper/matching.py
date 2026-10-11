"""Deciding whether two tracks are "the same song". Every feature goes through this module.

Three tiers, strongest first:
  EXACT      same Spotify track URI
  RECORDING  same ISRC (the industry ID of a recording) - e.g. the single and album release
  LIKELY     same normalized title + primary artist, durations within DURATION_TOLERANCE_MS
"""

from __future__ import annotations

import enum
import re
from collections import defaultdict
from collections.abc import Iterable

from .models import PlaylistItem, Track

DURATION_TOLERANCE_MS = 3_000


class Tier(enum.IntEnum):
    EXACT = 1
    RECORDING = 2
    LIKELY = 3

    @property
    def label(self) -> str:
        return {Tier.EXACT: "same track", Tier.RECORDING: "same recording", Tier.LIKELY: "likely same"}[self]


# Tags that mark a reissue or credit rather than a different performance. Live/remix/edit/acoustic
# deliberately do not match, so those stay distinct songs.
_STRIP_TAG = re.compile(
    r"""^(
        (\d{4}\s+)?(digital(ly)?\s+)?remaster(ed)?(\s+(version|edition|\d{4}))*
      | (feat|ft|featuring|with)\b.*
      | (album|single|lp|original)\s+version
    )$""",
    re.VERBOSE,
)
_BRACKETED = re.compile(r"[(\[]([^)\]]*)[)\]]")
_DASH_SPLIT = re.compile(r"\s+-\s+")
_NON_WORD = re.compile(r"[^\w\s]")


def _is_strip_tag(segment: str) -> bool:
    return bool(_STRIP_TAG.match(segment.strip()))


def normalize_title(title: str) -> str:
    t = title.lower()
    t = _BRACKETED.sub(lambda m: "" if _is_strip_tag(m.group(1)) else m.group(0), t)
    head, *suffixes = _DASH_SPLIT.split(t)
    t = head + "".join(f" - {s}" for s in suffixes if not _is_strip_tag(s))
    return " ".join(_NON_WORD.sub(" ", t).split())


def _likely_key(t: Track) -> tuple[str, str]:
    primary = t.artists[0].strip().lower() if t.artists else ""
    return normalize_title(t.name), primary


def match_tier(a: Track, b: Track) -> Tier | None:
    if not (a.available and b.available):
        return None
    if a.uri == b.uri:
        return Tier.EXACT
    if a.isrc and a.isrc == b.isrc:
        return Tier.RECORDING
    if _likely_key(a) == _likely_key(b) and abs(a.duration_ms - b.duration_ms) <= DURATION_TOLERANCE_MS:
        return Tier.LIKELY
    return None


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        self.parent[self.find(a)] = self.find(b)


def group_duplicates(playlist_items: list[PlaylistItem]) -> list[list[PlaylistItem]]:
    """Groups of 2+ items that are the same song, each sorted by position, groups ordered by first position."""
    its = [i for i in playlist_items if i.track.available]
    uf = _UnionFind(len(its))

    def union_buckets(buckets: dict) -> None:
        for members in buckets.values():
            for m in members[1:]:
                uf.union(members[0], m)

    by_uri: dict[str, list[int]] = defaultdict(list)
    by_isrc: dict[str, list[int]] = defaultdict(list)
    by_key: dict[tuple[str, str], list[int]] = defaultdict(list)
    for idx, it in enumerate(its):
        by_uri[it.track.uri].append(idx)
        if it.track.isrc:
            by_isrc[it.track.isrc].append(idx)
        by_key[_likely_key(it.track)].append(idx)
    union_buckets(by_uri)
    union_buckets(by_isrc)

    # Fuzzy tier: cluster by duration, anchored on each cluster's shortest member so clusters can't chain.
    for members in by_key.values():
        members.sort(key=lambda i: its[i].track.duration_ms)
        anchor = members[0]
        for m in members[1:]:
            if its[m].track.duration_ms - its[anchor].track.duration_ms <= DURATION_TOLERANCE_MS:
                uf.union(anchor, m)
            else:
                anchor = m

    groups: dict[int, list[PlaylistItem]] = defaultdict(list)
    for idx, it in enumerate(its):
        groups[uf.find(idx)].append(it)
    result = [sorted(g, key=lambda i: i.position) for g in groups.values() if len(g) > 1]
    return sorted(result, key=lambda g: g[0].position)


class SongIndex:
    """Answers "is this song already in that collection, and how sure are we?" in O(1)-ish per lookup."""

    def __init__(self, tracks: Iterable[Track] = ()):
        self._uris: set[str] = set()
        self._isrcs: set[str] = set()
        self._durations: dict[tuple[str, str], list[int]] = defaultdict(list)
        for t in tracks:
            self.add(t)

    def add(self, t: Track) -> None:
        if not t.available:
            return
        self._uris.add(t.uri)
        if t.isrc:
            self._isrcs.add(t.isrc)
        self._durations[_likely_key(t)].append(t.duration_ms)

    def find(self, t: Track) -> Tier | None:
        if not t.available:
            return None
        if t.uri in self._uris:
            return Tier.EXACT
        if t.isrc and t.isrc in self._isrcs:
            return Tier.RECORDING
        durations = self._durations.get(_likely_key(t), ())
        if any(abs(d - t.duration_ms) <= DURATION_TOLERANCE_MS for d in durations):
            return Tier.LIKELY
        return None
