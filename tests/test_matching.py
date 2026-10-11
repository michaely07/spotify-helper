import pytest

from helpers import items, track
from spotify_helper.matching import SongIndex, Tier, group_duplicates, match_tier, normalize_title


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Here Comes the Sun - Remastered 2019", "here comes the sun"),
        ("Here Comes the Sun (2009 Remaster)", "here comes the sun"),
        ("Bohemian Rhapsody - Remastered", "bohemian rhapsody"),
        ("Wonderwall - 2014 Digital Remaster", "wonderwall"),
        ("Stay (with Justin Bieber)", "stay"),
        ("Song (feat. Someone)", "song"),
        ("Song [ft. Someone & Other]", "song"),
        ("Song - Album Version", "song"),
        ("Song (Single Version)", "song"),
        ("  Don't   Stop  Me Now ", "don t stop me now"),
    ],
)
def test_normalize_title_strips_reissue_and_feature_tags(raw, expected):
    assert normalize_title(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["Song - Live", "Song (Live at Wembley)", "Song - Remix", "Song (Acoustic)", "Song - Radio Edit",
     "Song (Extended Mix)"],
)
def test_normalize_title_keeps_distinct_versions(raw):
    assert normalize_title(raw) != normalize_title("Song")


def test_match_tier_exact_beats_everything():
    a = track(uri="spotify:track:x", isrc="ISRC1")
    assert match_tier(a, a) is Tier.EXACT


def test_match_tier_same_isrc_is_same_recording():
    single = track("Song", isrc="US123", album_type="single")
    album = track("Song", isrc="US123", album_type="album")
    assert match_tier(single, album) is Tier.RECORDING


def test_match_tier_fuzzy_requires_close_duration():
    a = track("Song - Remastered 2011", duration_ms=200_000)
    b = track("Song", duration_ms=202_500)
    c = track("Song", duration_ms=210_000)
    assert match_tier(a, b) is Tier.LIKELY
    assert match_tier(a, c) is None


def test_match_tier_fuzzy_requires_same_primary_artist():
    assert match_tier(track("Song", ["A"]), track("Song", ["B"])) is None
    assert match_tier(track("Song", ["A", "B"]), track("Song", ["a"])) is Tier.LIKELY


def test_live_version_is_not_a_duplicate():
    assert match_tier(track("Song"), track("Song - Live")) is None


def test_different_isrc_but_same_title_still_likely():
    # Same song released twice with different ISRCs (e.g. a re-upload) still reads as a likely dupe.
    assert match_tier(track("Song", isrc="A"), track("Song", isrc="B")) is Tier.LIKELY


def test_unavailable_entries_never_match():
    gone = track("", uri="")
    assert match_tier(gone, gone) is None


def test_group_duplicates_unions_across_tiers():
    t = track("Song", isrc="I1")
    its = items(
        t,                                       # 0
        track("Other"),                          # 1
        t,                                       # 2 exact dup of 0
        track("Song", isrc="I1", album_type="single"),  # 3 same recording as 0
        track("Song - 2011 Remaster", isrc="I9"),        # 4 likely dup of 0
        track("Song - Live"),                    # 5 distinct
    )
    groups = group_duplicates(its)
    assert [[i.position for i in g] for g in groups] == [[0, 2, 3, 4]]


def test_group_duplicates_duration_clusters_do_not_chain_forever():
    its = items(*(track("Song", duration_ms=200_000 + 2_000 * k) for k in range(4)))
    # 200.0s, 202.0s, 204.0s, 206.0s: each cluster spans at most 3s from its first member
    groups = group_duplicates(its)
    assert [[i.position for i in g] for g in groups] == [[0, 1], [2, 3]]


def test_song_index_finds_best_tier():
    t = track("Song", isrc="I1")
    index = SongIndex([t, track("Another")])
    assert index.find(t) is Tier.EXACT
    assert index.find(track("Song", isrc="I1")) is Tier.RECORDING
    assert index.find(track("Song (feat. X)")) is Tier.LIKELY
    assert index.find(track("Nope")) is None


def test_song_index_incremental_add():
    index = SongIndex()
    t = track("Song")
    assert index.find(t) is None
    index.add(t)
    assert index.find(track("Song")) is Tier.LIKELY
