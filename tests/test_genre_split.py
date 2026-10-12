import pytest

from helpers import items, playlist, track
from spotify_helper.features.genre_split import build_genre_plan, default_name, summarize

A, B, C, D = track("A"), track("B"), track("C"), track("D")
GENRES = {A.uri: ["indie pop", "dream pop"], B.uri: ["indie pop"], C.uri: ["drill"], D.uri: []}
BIG = playlist("big", "Everything")


def scan():
    return summarize(BIG, items(A, B, C, D), lambda t: GENRES[t.uri])


def test_summary_groups_by_genre_biggest_first_and_lists_untagged():
    s = scan()
    assert [(g.genre, [i.track.name for i in g.items]) for g in s.groups] == [
        ("indie pop", ["A", "B"]), ("dream pop", ["A"]), ("drill", ["C"])]
    assert [i.track.name for i in s.untagged] == ["D"]


def test_default_name():
    assert default_name("Everything", "uk drill") == "Everything – UK Drill"


def test_track_goes_into_every_selected_genre():
    plan = build_genre_plan(scan(), {"indie pop": "Indie", "dream pop": "Dreamy"}, existing=[])
    assert [(n.name, [t.name for t in n.tracks]) for n in plan.creates] == [("Indie", ["A", "B"]), ("Dreamy", ["A"])]
    assert plan.changes == []  # big playlist untouched


def test_same_name_combines_rows_without_duplicates():
    plan = build_genre_plan(scan(), {"indie pop": "Mix", "dream pop": "Mix", "drill": "Mix"}, existing=[])
    assert [(n.name, [t.name for t in n.tracks]) for n in plan.creates] == [("Mix", ["A", "B", "C"])]


def test_existing_playlist_with_that_name_is_topped_up():
    existing_pl = playlist("e", "Indie")
    plan = build_genre_plan(scan(), {"indie pop": "Indie"}, existing=[(existing_pl, items(track("A")))])
    assert plan.creates == []
    assert plan.changes[0].playlist is existing_pl
    assert [t.name for t in plan.changes[0].add] == ["B"]


def test_refuses_to_target_the_big_playlist():
    with pytest.raises(ValueError):
        build_genre_plan(scan(), {"drill": "Everything"}, existing=[(BIG, items(A, B, C, D))])
