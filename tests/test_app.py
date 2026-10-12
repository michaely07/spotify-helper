import re
import time

import pytest
from fastapi.testclient import TestClient

from fake_spotify import FakeSpotifyClient
from helpers import playlist, track
from spotify_helper.app import create_app


@pytest.fixture(autouse=True)
def no_real_config(monkeypatch):
    """Keep the developer's .env (e.g. a real LASTFM_API_KEY) out of tests."""
    monkeypatch.delenv("LASTFM_API_KEY", raising=False)
    monkeypatch.setattr("spotify_helper.app.load_dotenv", lambda: None)


@pytest.fixture
def env(tmp_path):
    fake = FakeSpotifyClient()
    app = create_app(client=fake, data_dir=tmp_path)
    return fake, TestClient(app)


def _plan_id(resp):
    assert resp.status_code == 200, resp.text
    return re.search(r"/plans/([0-9a-f]{32})/apply", resp.text).group(1)


def test_home_lists_editable_and_followed(env):
    fake, http = env
    fake.put(playlist("mine", "My Mix"), [])
    fake.put(playlist("theirs", "Their Hits", owner="someone"), [])
    page = http.get("/").text
    assert "My Mix" in page and "Their Hits" in page and "can't be scanned" in page


def test_dedupe_flow_end_to_end(env):
    fake, http = env
    single = track("Song", isrc="I", album_type="single")
    album = track("Song", isrc="I", album_type="album")
    other = track("Other")
    pl = fake.put(playlist("p", "Mix"), [single, other, album, single])

    page = http.get("/dedupe/p")
    assert "1 group" in page.text
    resp = http.post("/dedupe/p", data={"snapshot_id": pl.snapshot_id, "include": "0", "keep_0": "2"})
    plan_id = _plan_id(resp)  # redirect followed to preview
    assert "Remove 2" in resp.text

    done = http.post(f"/plans/{plan_id}/apply")
    assert done.status_code == 200 and "Done" in done.text
    assert fake.uris("p") == [other.uri, album.uri]
    assert "Mix" in http.get("/backups").text


def test_dedupe_rejects_stale_page(env):
    fake, http = env
    t = track("Song")
    fake.put(playlist("p"), [t, t])
    resp = http.post("/dedupe/p", data={"snapshot_id": "old", "include": "0"})
    assert resp.status_code == 400 and "changed in Spotify" in resp.text


def test_split_flow(env):
    fake, http = env
    a, b, c = track("A"), track("B"), track("C")
    big = fake.put(playlist("big", "Everything"), [a, b, c])
    fake.put(playlist("t1", "Chill"), [a])
    fake.put(playlist("t2", "Rock"), [b])

    page = http.get("/split", params=[("big", "big"), ("targets", "t1"), ("targets", "t2")]).text
    assert "Already sorted: 2 of 3" in page and "Still to sort: 1" in page

    resp = http.post("/split", data={"big": "big", "snapshot_id": big.snapshot_id, "positions": ["0", "1"]})
    http.post(f"/plans/{_plan_id(resp)}/apply")
    assert fake.uris("big") == [c.uri]


def test_orphans_page(env):
    fake, http = env
    a, b = track("A"), track("Lonely Song")
    fake.put(playlist("p"), [a])
    fake.liked = [a, b]
    page = http.get("/orphans").text
    assert "1 of 2 liked songs" in page and "Lonely Song" in page


def test_overlap_and_pair(env):
    fake, http = env
    a = track("Shared Song")
    fake.put(playlist("p1", "One"), [a, track("X")])
    fake.put(playlist("p2", "Two"), [a])
    page = http.get("/overlap", params=[("ids", "p1"), ("ids", "p2")]).text
    assert "/overlap/pair?a=p1&b=p2" in page
    assert "Shared Song" in http.get("/overlap/pair", params={"a": "p1", "b": "p2"}).text


def test_merge_flow(env):
    fake, http = env
    a, b = track("A"), track("B")
    fake.put(playlist("p1"), [a, b])
    fake.put(playlist("p2"), [b])
    resp = http.post("/merge", data={"name": "Combined", "ids": ["p1", "p2"]})
    assert "1 duplicate track(s) skipped" in resp.text
    http.post(f"/plans/{_plan_id(resp)}/apply")
    new = next(p for p in fake.meta.values() if p.name == "Combined")
    assert fake.uris(new.id) == [a.uri, b.uri]


def test_move_flow(env):
    fake, http = env
    a, b = track("A"), track("B")
    src = fake.put(playlist("src", "From"), [a, b])
    fake.put(playlist("dst", "To"), [])
    assert "A" in http.get("/move", params={"src": "src", "dst": "dst"}).text
    resp = http.post("/move", data={"src": "src", "dst": "dst", "snapshot_id": src.snapshot_id, "positions": ["0"]})
    http.post(f"/plans/{_plan_id(resp)}/apply")
    assert fake.uris("src") == [b.uri] and fake.uris("dst") == [a.uri]


def test_restore_flow(env):
    fake, http = env
    a, b = track("A"), track("B")
    pl = fake.put(playlist("p", "Mix"), [a, b, a])
    resp = http.post("/dedupe/p", data={"snapshot_id": pl.snapshot_id, "include": "0"})
    http.post(f"/plans/{_plan_id(resp)}/apply")
    assert fake.uris("p") == [a.uri, b.uri]

    resp = http.post("/backups/1/restore")
    assert "1 track(s) will come back" in resp.text
    http.post(f"/plans/{_plan_id(resp)}/apply")
    assert fake.uris("p") == [a.uri, b.uri, a.uri]


def test_applying_twice_is_refused(env):
    fake, http = env
    t = track("Song")
    pl = fake.put(playlist("p"), [t, t])
    plan_id = _plan_id(http.post("/dedupe/p", data={"snapshot_id": pl.snapshot_id, "include": "0"}))
    assert http.post(f"/plans/{plan_id}/apply").status_code == 200
    assert http.post(f"/plans/{plan_id}/apply").status_code == 400


def test_counts_are_current_even_while_spotify_playlist_list_lags(env):
    fake, http = env
    t, other = track("Song"), track("Other")
    pl = fake.put(playlist("p", "Mix"), [t, other, t])
    fake.put(playlist("q", "Other list"), [other])
    fake.lag_playlist_list()

    plan_id = _plan_id(http.post("/dedupe/p", data={"snapshot_id": pl.snapshot_id, "include": "0"}))
    http.post(f"/plans/{plan_id}/apply")
    assert fake.uris("p") == [t.uri, other.uri]

    home = http.get("/").text
    assert 'data-count-for="p">2<' in home, "home page shows the pre-change count"
    # Pages that read track lists must not reuse the pre-change cached contents either.
    overlap = http.get("/overlap", params=[("ids", "p"), ("ids", "q")]).text
    assert re.search(r'<td><span class="muted">2</span></td>', overlap)


def test_pages_are_not_cached_by_the_browser(env):
    _, http = env
    assert "no-store" in http.get("/").headers.get("cache-control", "")


def test_split_disables_the_big_playlist_in_the_target_list(env):
    fake, http = env
    fake.put(playlist("big", "Everything"), [])
    fake.put(playlist("t1", "Chill"), [])
    page = http.get("/split", params={"big": "big"}).text  # big chosen, no targets yet
    assert re.search(r'<input[^>]*name="targets" value="big"[^>]*disabled', page)
    assert not re.search(r'<input[^>]*name="targets" value="t1"[^>]*disabled', page)
    assert 'data-disables="targets"' in page


def _wait_for_results(http, url):
    for _ in range(200):
        page = http.get(url).text
        if "data-poll" not in page:
            return page
        time.sleep(0.02)
    raise AssertionError("scan never finished")


def test_genre_split_flow(tmp_path):
    class Tags:
        def track_tags(self, artist, title):
            return {"A": [("shoegaze", 100)], "B": [("shoegaze", 90), ("dream pop", 60)],
                    "C": [("drill", 100)]}.get(title, [])

        def artist_tags(self, artist):
            return []

    fake = FakeSpotifyClient()
    a, b, c, d = track("A"), track("B"), track("C"), track("D")
    fake.put(playlist("big", "Everything"), [a, b, c, d])
    fake.put(playlist("old", "Everything – Drill"), [])
    http = TestClient(create_app(client=fake, data_dir=tmp_path, tag_source=Tags()))

    resp = http.post("/genres/scan", data={"big": "big"})
    page = _wait_for_results(http, resp.url.path)
    assert "Shoegaze" in page and "Dream Pop" in page and "No usable genre tags: 1" in page
    job_id = re.search(r'name="job_id" value="([0-9a-f]+)"', page).group(1)
    # rows: 0 shoegaze (2 tracks), 1 dream pop (1), 2 drill (1)
    resp = http.post("/genres/preview", data={"job_id": job_id, "include": ["0", "2"],
                                               "name_0": "Everything – Shoegaze", "name_2": "Everything – Drill"})
    http.post(f"/plans/{_plan_id(resp)}/apply")

    assert fake.uris("big") == [a.uri, b.uri, c.uri, d.uri]  # untouched
    shoegaze = next(p for p in fake.meta.values() if p.name == "Everything – Shoegaze")
    assert fake.uris(shoegaze.id) == [a.uri, b.uri]
    assert fake.uris("old") == [c.uri]  # topped up, not duplicated


def test_genre_split_refuses_big_playlist_name(tmp_path):
    class Tags:
        def track_tags(self, artist, title):
            return [("drill", 100)]

        def artist_tags(self, artist):
            return []

    fake = FakeSpotifyClient()
    fake.put(playlist("big", "Everything"), [track("A")])
    http = TestClient(create_app(client=fake, data_dir=tmp_path, tag_source=Tags()))
    page = _wait_for_results(http, http.post("/genres/scan", data={"big": "big"}).url.path)
    job_id = re.search(r'name="job_id" value="([0-9a-f]+)"', page).group(1)
    resp = http.post("/genres/preview", data={"job_id": job_id, "include": ["0"], "name_0": "Everything"})
    assert resp.status_code == 400 and "playlist being split" in resp.text


def test_genre_scan_error_is_shown(tmp_path):
    from spotify_helper.lastfm import LastFmError

    class Broken:
        def track_tags(self, artist, title):
            raise LastFmError("Last.fm rejected the API key (Invalid API key).")

        artist_tags = track_tags

    fake = FakeSpotifyClient()
    fake.put(playlist("big", "Everything"), [track("A")])
    http = TestClient(create_app(client=fake, data_dir=tmp_path, tag_source=Broken()))
    url = http.post("/genres/scan", data={"big": "big"}).url.path
    page = _wait_for_results(http, url)
    assert "rejected the API key" in page


def test_genres_page_explains_setup_without_lastfm_key(env):
    _, http = env
    assert "LASTFM_API_KEY" in http.get("/genres").text
