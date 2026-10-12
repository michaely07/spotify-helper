"""Turning Last.fm's free-form tags into genres, using MusicBrainz's genre list (CC0) as the vocabulary."""

from __future__ import annotations

import re
from functools import lru_cache
from importlib.resources import files

from .matching import strip_reissue_tags
from .models import Track

MIN_WEIGHT = 20  # Last.fm tag weights are 0-100, relative to the item's top tag
MAX_GENRES = 5
_SEP = re.compile(r"[\s\-_]+")
_ALIASES = {"rnb": "r&b", "dnb": "drum and bass", "drum n bass": "drum and bass", "drum & bass": "drum and bass"}
_UPPER_WORDS = {"uk", "us", "edm", "idm", "ebm", "dj", "r&b"}


def normalize_tag(tag: str) -> str:
    return _SEP.sub(" ", tag.strip().lower()).strip()


def _squash(tag: str) -> str:
    return tag.replace(" ", "")  # "hip hop" == "hiphop"


@lru_cache(maxsize=1)
def vocabulary() -> dict[str, str]:
    """Squashed normalized form -> MusicBrainz's spelling."""
    text = files("spotify_helper").joinpath("data/genres.txt").read_text(encoding="utf-8")
    vocab: dict[str, str] = {}
    for line in text.splitlines():
        if line.strip():
            vocab.setdefault(_squash(normalize_tag(line)), line.strip().lower())
    for alias, target in _ALIASES.items():
        if _squash(normalize_tag(target)) in vocab:
            vocab.setdefault(_squash(normalize_tag(alias)), vocab[_squash(normalize_tag(target))])
    return vocab


def genres_from_tags(tags: list[tuple[str, int]]) -> list[str]:
    vocab = vocabulary()
    found: list[str] = []
    for name, weight in sorted(tags, key=lambda t: -t[1]):
        if weight < MIN_WEIGHT:
            break
        genre = vocab.get(_squash(normalize_tag(name)))
        if genre and genre not in found:
            found.append(genre)
            if len(found) == MAX_GENRES:
                break
    return found


def genre_title(genre: str) -> str:
    return " ".join(w.upper() if w in _UPPER_WORDS else w.title() for w in genre.split(" "))


class GenreTagger:
    """Genres for a track: its own Last.fm tags, else its primary artist's. Raw tags are cached."""

    def __init__(self, source, cache, max_age_days: int = 90):
        self.source, self.cache, self.max_age_days = source, cache, max_age_days

    def _tags(self, kind: str, key: str, fetch) -> list[tuple[str, int]]:
        cached = self.cache.get_tags(kind, key, self.max_age_days)
        if cached is not None:
            return cached
        tags = fetch()
        self.cache.put_tags(kind, key, tags)
        return tags

    def genres_for(self, track: Track) -> list[str]:
        if not track.available or not track.artists:
            return []
        artist = track.artists[0]
        title = strip_reissue_tags(track.name)
        tags = self._tags("track", f"{normalize_tag(artist)}|{normalize_tag(title)}",
                          lambda: self.source.track_tags(artist, title))
        return genres_from_tags(tags) or genres_from_tags(
            self._tags("artist", normalize_tag(artist), lambda: self.source.artist_tags(artist)))
