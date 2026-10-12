from spotify_helper.genres import genre_title, genres_from_tags, normalize_tag
from spotify_helper.matching import strip_reissue_tags


def test_normalize_tag():
    assert normalize_tag("  Hip-Hop ") == "hip hop"
    assert normalize_tag("indie_pop") == "indie pop"


def test_keeps_only_real_genres_strongest_first():
    tags = [("seen live", 100), ("Dream Pop", 40), ("shoegaze", 90), ("female vocalists", 80)]
    assert genres_from_tags(tags) == ["shoegaze", "dream pop"]


def test_spelling_variants_map_to_one_genre():
    assert genres_from_tags([("hip-hop", 100), ("Hip Hop", 90), ("hiphop", 80)]) == ["hip hop"]
    assert genres_from_tags([("synthpop", 100)]) == ["synth-pop"]
    assert genres_from_tags([("rnb", 100)]) == ["r&b"]


def test_weak_tags_are_ignored_and_capped_at_five():
    assert genres_from_tags([("shoegaze", 19)]) == []
    many = [(g, 100 - i) for i, g in enumerate(["rock", "pop", "jazz", "blues", "funk", "soul", "disco"])]
    assert genres_from_tags(many) == ["rock", "pop", "jazz", "blues", "funk"]


def test_genre_title():
    assert genre_title("indie pop") == "Indie Pop"
    assert genre_title("r&b") == "R&B"
    assert genre_title("uk drill") == "UK Drill"
    assert genre_title("k-pop") == "K-Pop"


def test_strip_reissue_tags_keeps_case_and_real_versions():
    assert strip_reissue_tags("Don't Stop Me Now - Remastered 2011") == "Don't Stop Me Now"
    assert strip_reissue_tags("Stay (with Justin Bieber)") == "Stay"
    assert strip_reissue_tags("Song - Live") == "Song - Live"


from helpers import track
from spotify_helper.cache import Cache
from spotify_helper.genres import GenreTagger


class FakeTags:
    def __init__(self, tracks=None, artists=None):
        self.tracks, self.artists, self.calls = tracks or {}, artists or {}, []

    def track_tags(self, artist, title):
        self.calls.append(("track", artist, title))
        return self.tracks.get((artist, title), [])

    def artist_tags(self, artist):
        self.calls.append(("artist", artist))
        return self.artists.get(artist, [])


def test_track_tags_win_and_are_cached(tmp_path):
    src = FakeTags(tracks={("Slowdive", "Alison"): [("shoegaze", 100)]}, artists={"Slowdive": [("dream pop", 100)]})
    tagger = GenreTagger(src, Cache(tmp_path / "c.db"))
    t = track("Alison - 2010 Remaster", ["Slowdive"])
    assert tagger.genres_for(t) == ["shoegaze"]
    assert tagger.genres_for(t) == ["shoegaze"]
    assert src.calls == [("track", "Slowdive", "Alison")]  # looked up once, with the remaster tag removed


def test_falls_back_to_artist_tags_once_per_artist(tmp_path):
    src = FakeTags(artists={"Drake": [("hip-hop", 100), ("seen live", 90)]})
    tagger = GenreTagger(src, Cache(tmp_path / "c.db"))
    assert tagger.genres_for(track("One", ["Drake"])) == ["hip hop"]
    assert tagger.genres_for(track("Two", ["Drake"])) == ["hip hop"]
    assert [c for c in src.calls if c[0] == "artist"] == [("artist", "Drake")]


def test_untaggable_and_unavailable(tmp_path):
    tagger = GenreTagger(FakeTags(), Cache(tmp_path / "c.db"))
    assert tagger.genres_for(track("Mystery", ["Nobody"])) == []
    assert tagger.genres_for(track("", uri="")) == []


def test_cache_expires(tmp_path):
    cache = Cache(tmp_path / "c.db")
    cache.put_tags("artist", "x", [("rock", 100)])
    assert cache.get_tags("artist", "x", max_age_days=90) == [("rock", 100)]
    assert cache.get_tags("artist", "x", max_age_days=-1) is None
