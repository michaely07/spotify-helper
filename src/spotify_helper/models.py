"""Plain data types shared across the app. No Spotify API or I/O knowledge here."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Track:
    uri: str  # "" for entries Spotify no longer returns (removed/unavailable)
    name: str
    artists: tuple[str, ...] = ()
    album_name: str = ""
    album_type: str = ""  # "album" | "single" | "compilation" | ""
    isrc: str | None = None
    duration_ms: int = 0
    is_local: bool = False
    image_url: str | None = None

    @property
    def available(self) -> bool:
        return bool(self.uri)

    @property
    def artist_line(self) -> str:
        return ", ".join(self.artists)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["artists"] = list(self.artists)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Track:
        return cls(**{**d, "artists": tuple(d.get("artists", ()))})


@dataclass(frozen=True)
class PlaylistItem:
    track: Track
    position: int  # index within the playlist, counting every entry
    added_at: str = ""  # ISO-8601 timestamp, sorts chronologically as a string

    def to_dict(self) -> dict:
        return {"track": self.track.to_dict(), "position": self.position, "added_at": self.added_at}

    @classmethod
    def from_dict(cls, d: dict) -> PlaylistItem:
        return cls(track=Track.from_dict(d["track"]), position=d["position"], added_at=d.get("added_at", ""))


@dataclass(frozen=True)
class Playlist:
    id: str
    name: str
    owner_id: str
    owner_name: str = ""
    snapshot_id: str = ""
    total: int = 0
    collaborative: bool = False
    public: bool | None = None
    image_url: str | None = None

    def editable_by(self, user_id: str) -> bool:
        """Spotify only exposes items of, and allows edits to, playlists you own or collaborate on."""
        return self.owner_id == user_id or self.collaborative


@dataclass
class PlaylistChange:
    """Edits to one existing playlist. Positions refer to the playlist as it was when the plan was built."""

    playlist: Playlist
    remove: list[PlaylistItem] = field(default_factory=list)
    add: list[Track] = field(default_factory=list)  # appended at the end
    replace_with: list[Track] | None = None  # full replacement (used by restore)


@dataclass
class NewPlaylist:
    name: str
    description: str
    tracks: list[Track]


@dataclass
class ChangePlan:
    id: str
    title: str
    changes: list[PlaylistChange] = field(default_factory=list)
    create: NewPlaylist | None = None
    notes: list[str] = field(default_factory=list)
