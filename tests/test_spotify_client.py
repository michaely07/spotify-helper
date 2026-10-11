import json

import httpx
import pytest

from spotify_helper import spotify_client
from spotify_helper.spotify_client import SpotifyClient, SpotifyError

RAW_TRACK = {
    "uri": "spotify:track:abc",
    "name": "Song",
    "artists": [{"name": "A"}, {"name": "B"}],
    "album": {"name": "LP", "album_type": "album", "images": [{"url": "big"}, {"url": "small"}]},
    "external_ids": {"isrc": "US123"},
    "duration_ms": 1234,
    "is_local": False,
}


def make_client(handler):
    return SpotifyClient(lambda: "tok", http=httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(spotify_client.time, "sleep", lambda s: None)


def test_playlist_items_paginates_and_parses_new_and_old_field_names():
    pages = {
        "/v1/playlists/p/items": {"items": [{"added_at": "2024", "item": RAW_TRACK}, {"added_at": "2024", "item": None}],
                                  "next": "https://api.spotify.com/v1/playlists/p/items?offset=2"},
    }

    def handler(req):
        if req.url.params.get("offset") == "2":
            return httpx.Response(200, json={"items": [{"added_at": "2025", "track": RAW_TRACK}], "next": None})
        return httpx.Response(200, json=pages[req.url.path])

    items = make_client(handler).get_playlist_items("p")
    assert [i.position for i in items] == [0, 1, 2]
    t = items[0].track
    assert (t.uri, t.artists, t.album_type, t.isrc, t.image_url) == ("spotify:track:abc", ("A", "B"), "album", "US123", "small")
    assert not items[1].track.available
    assert items[2].track.uri == "spotify:track:abc"


def test_playlist_total_reads_items_or_tracks():
    def handler(req):
        return httpx.Response(200, json={"items": [
            {"id": "1", "name": "new", "owner": {"id": "me"}, "items": {"total": 7}},
            {"id": "2", "name": "old", "owner": {"id": "me"}, "tracks": {"total": 3}},
        ], "next": None})

    assert [p.total for p in make_client(handler).get_my_playlists()] == [7, 3]


def test_retries_on_429_then_succeeds():
    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json={"id": "me"})

    assert make_client(handler).current_user_id() == "me"
    assert len(calls) == 2


def test_errors_surface_spotify_message():
    def handler(req):
        return httpx.Response(403, json={"error": {"status": 403, "message": "Forbidden"}})

    with pytest.raises(SpotifyError, match="Forbidden"):
        make_client(handler).get_playlist("p")


def test_writes_use_items_endpoint_and_batch_positions():
    seen = []

    def handler(req):
        seen.append((req.method, req.url.path, json.loads(req.content) if req.content else None))
        return httpx.Response(200, json={"snapshot_id": "s"})

    c = make_client(handler)
    c.remove_uris("p", ["u1"])
    c.add_uris("p", [f"u{i}" for i in range(150)], position=5)
    assert seen[0] == ("DELETE", "/v1/playlists/p/items", {"items": [{"uri": "u1"}]})
    assert [(m, body["position"], len(body["uris"])) for m, _, body in seen[1:]] == [("POST", 5, 100), ("POST", 105, 50)]
