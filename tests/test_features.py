from helpers import items, playlist, track
from spotify_helper.features.dedupe import build_dedupe_plan, find_duplicates
from spotify_helper.features.merge_move import build_merge_plan, build_move_plan
from spotify_helper.features.orphans import find_orphans
from spotify_helper.features.overlap import overlap_matrix, shared_tracks
from spotify_helper.features.split import analyze_split, build_split_plan
from spotify_helper.matching import Tier


# --- dedupe -------------------------------------------------------------

def test_dedupe_prefers_album_version_as_keeper():
    single = track("Song", isrc="I", album_type="single")
    comp = track("Song", isrc="I", album_type="compilation")
    album = track("Song", isrc="I", album_type="album")
    groups = find_duplicates(items(single, comp, album))
    assert len(groups) == 1
    assert groups[0].keeper.position == 2
    assert groups[0].tiers == {0: Tier.RECORDING, 1: Tier.RECORDING}


def test_dedupe_ties_go_to_earliest_added():
    t = track("Song")
    its = items(t, t, added=["2024-05-01T00:00:00Z", "2023-01-01T00:00:00Z"])
    assert find_duplicates(its)[0].keeper.position == 1


def test_dedupe_group_tier_is_weakest_link():
    t = track("Song", isrc="I")
    groups = find_duplicates(items(t, t, track("Song (feat. X)")))
    assert groups[0].tier is Tier.LIKELY


def test_dedupe_plan_honors_user_keeper_and_skips_locals():
    t = track("Song")
    local = track("Song", uri="spotify:local:song", is_local=True)
    its = items(t, t, local, track("Other"), track("Other"))
    pl = playlist()
    groups = find_duplicates(its)
    plan = build_dedupe_plan(pl, groups, keep={0: 1}, include={0})  # only first group, keep position 1
    assert [i.position for i in plan.changes[0].remove] == [0]


# --- split --------------------------------------------------------------

def test_split_maps_tracks_to_targets_and_lists_leftovers():
    a, b, c = track("A", isrc="IA"), track("B"), track("C")
    big = items(a, b, c)
    t1 = (playlist("t1"), items(track("A", isrc="IA", album_type="single")))
    t2 = (playlist("t2"), items(a, b))
    result = analyze_split(big, [t1, t2])
    found = {r.item.position: [(p.id, tier) for p, tier in r.matches] for r in result.rows}
    assert found == {0: [("t1", Tier.RECORDING), ("t2", Tier.EXACT)], 1: [("t2", Tier.EXACT)], 2: []}
    assert [r.item.position for r in result.placed] == [0, 1]
    assert [r.item.position for r in result.leftovers] == [2]


def test_split_plan_removes_selected_placed_tracks():
    big_pl = playlist("big")
    big = items(track("A"), track("B"))
    plan = build_split_plan(big_pl, big, {1})
    assert plan.changes[0].playlist is big_pl
    assert [i.position for i in plan.changes[0].remove] == [1]


# --- orphans ------------------------------------------------------------

def test_orphans_are_liked_songs_in_no_playlist():
    a, b, c = track("A"), track("B", isrc="IB"), track("C")
    pls = [items(a), items(track("B", isrc="IB", album_type="single"))]
    assert find_orphans([a, b, c], pls) == [c]


# --- overlap ------------------------------------------------------------

def test_overlap_matrix_counts_songs_of_row_found_in_column():
    a, b, c = track("A"), track("B"), track("C")
    p1, p2, p3 = (playlist("p1"), items(a, b, c)), (playlist("p2"), items(a, b)), (playlist("p3"), items(c))
    m = overlap_matrix([p1, p2, p3])
    assert m == [[3, 2, 1], [2, 2, 0], [1, 0, 1]]


def test_shared_tracks_lists_matches_with_tier():
    a = track("A", isrc="I")
    shared = shared_tracks(items(a, track("B")), items(track("A", isrc="I")))
    assert [(i.track.name, tier) for i, tier in shared] == [("A", Tier.RECORDING)]


# --- merge / move -------------------------------------------------------

def test_merge_dedupes_across_sources_in_order():
    a, b, c = track("A"), track("B"), track("C")
    plan = build_merge_plan("Mix", [(playlist("p1"), items(a, b)), (playlist("p2"), items(b, track("A - 2011 Remaster"), c))])
    assert [t.name for t in plan.creates[0].tracks] == ["A", "B", "C"]
    assert plan.creates[0].name == "Mix"


def test_move_skips_songs_already_in_destination_but_still_removes_from_source():
    a, b = track("A"), track("B")
    src_pl, dst_pl = playlist("src"), playlist("dst")
    src, dst = items(a, b), items(track("B"))
    plan = build_move_plan(src_pl, src, {0, 1}, dst_pl, dst)
    src_change, dst_change = plan.changes
    assert [i.position for i in src_change.remove] == [0, 1]
    assert [t.name for t in dst_change.add] == ["A"]
