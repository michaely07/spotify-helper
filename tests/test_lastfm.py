import httpx
import pytest

from spotify_helper.lastfm import LastFmClient, LastFmError


def client(handler):
    return LastFmClient("key", http=httpx.Client(transport=httpx.MockTransport(handler)), min_interval=0, sleep=lambda s: None)


def test_track_tags_parses_and_sends_params():
    seen = {}

    def handler(req):
        seen.update(req.url.params)
        return httpx.Response(200, json={"toptags": {"tag": [{"name": "Shoegaze", "count": 100}, {"name": "dream pop", "count": "55"}]}})

    assert client(handler).track_tags("Slowdive", "Alison") == [("Shoegaze", 100), ("dream pop", 55)]
    assert seen["method"] == "track.gettoptags" and seen["artist"] == "Slowdive" and seen["track"] == "Alison"
    assert seen["autocorrect"] == "1" and seen["format"] == "json" and seen["api_key"] == "key"


def test_single_tag_comes_back_as_object():
    def handler(req):
        return httpx.Response(200, json={"toptags": {"tag": {"name": "drill", "count": 100}}})

    assert client(handler).artist_tags("X") == [("drill", 100)]


def test_not_found_is_empty():
    def handler(req):
        return httpx.Response(200, json={"error": 6, "message": "Track not found"})

    assert client(handler).track_tags("Nobody", "Nothing") == []


def test_rate_limit_retries():
    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(429, json={"error": 29, "message": "Rate limit exceeded"})
        return httpx.Response(200, json={"toptags": {"tag": []}})

    assert client(handler).artist_tags("X") == []
    assert len(calls) == 3


def test_bad_key_is_fatal():
    def handler(req):
        return httpx.Response(403, json={"error": 10, "message": "Invalid API key"})

    with pytest.raises(LastFmError, match="API key"):
        client(handler).artist_tags("X")
