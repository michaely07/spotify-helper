import pytest

from fake_spotify import FakeSpotifyClient
from helpers import playlist, track
from spotify_helper.apply import StalePlanError, apply_plan, plan_removal
from spotify_helper.backup import BackupStore
from spotify_helper.models import ChangePlan, NewPlaylist, PlaylistChange


@pytest.fixture
def backups(tmp_path):
    return BackupStore(tmp_path / "test.db")


def test_plan_removal_distinct_uris_needs_no_reinserts():
    fake = FakeSpotifyClient()
    a, b, c = track("A"), track("B"), track("C")
    pl = fake.put(playlist(), [a, b, c])
    delete, reinserts = plan_removal(fake.get_playlist_items(pl.id), {1})
    assert delete == [b.uri]
    assert reinserts == []


def test_plan_removal_exact_duplicate_reinserts_kept_copy():
    a, b, c = track("A"), track("B"), track("C")
    fake = FakeSpotifyClient()
    pl = fake.put(playlist(), [a, b, a, c, a])
    # keep the copy at position 2, drop positions 0 and 4
    delete, reinserts = plan_removal(fake.get_playlist_items(pl.id), {0, 4})
    assert delete == [a.uri]
    assert reinserts == [(1, [a.uri])]  # final list: b, a, c


def test_plan_removal_groups_consecutive_reinserts():
    a, b, x = track("A"), track("B"), track("X")
    fake = FakeSpotifyClient()
    pl = fake.put(playlist(), [x, a, b, a, b])
    delete, reinserts = plan_removal(fake.get_playlist_items(pl.id), {3, 4})
    assert sorted(delete) == sorted([a.uri, b.uri])
    assert reinserts == [(1, [a.uri, b.uri])]


def test_plan_removal_refuses_local_files():
    fake = FakeSpotifyClient()
    pl = fake.put(playlist(), [track("L", uri="spotify:local:x", is_local=True)])
    with pytest.raises(ValueError):
        plan_removal(fake.get_playlist_items(pl.id), {0})


def _change(fake, pid, remove_positions=(), add=()):
    pl = fake.get_playlist(pid)
    its = fake.get_playlist_items(pid)
    return PlaylistChange(playlist=pl, remove=[i for i in its if i.position in remove_positions], add=list(add))


def test_apply_removes_one_copy_and_preserves_order(backups):
    a, b, c = track("A"), track("B"), track("C")
    fake = FakeSpotifyClient()
    pl = fake.put(playlist(), [a, b, a, c, a])
    plan = ChangePlan(id="x", title="dedupe", changes=[_change(fake, pl.id, {0, 4})])

    apply_plan(plan, fake, backups)

    assert fake.uris(pl.id) == [b.uri, a.uri, c.uri]


def test_apply_backs_up_every_playlist_before_any_write(backups):
    fake = FakeSpotifyClient()
    p1 = fake.put(playlist("p1"), [track("A"), track("B")])
    p2 = fake.put(playlist("p2"), [track("C")])
    new = track("N")
    plan = ChangePlan(id="x", title="move", changes=[_change(fake, p1.id, {0}), _change(fake, p2.id, add=[new])])

    result = apply_plan(plan, fake, backups)

    first_write = next(i for i, c in enumerate(fake.calls) if c[0] in {"remove_uris", "add_uris", "replace_uris"})
    reads_before = {c[1] for c in fake.calls[:first_write] if c[0] == "get_playlist_items"}
    assert reads_before == {"p1", "p2"}
    assert len(result.backup_ids) == 2
    saved = {backups.get(bid)[0].playlist_id for bid in result.backup_ids}
    assert saved == {"p1", "p2"}
    assert fake.uris("p2")[-1] == new.uri


def test_apply_refuses_stale_plan_without_writing(backups):
    fake = FakeSpotifyClient()
    pl = fake.put(playlist(), [track("A"), track("B")])
    plan = ChangePlan(id="x", title="dedupe", changes=[_change(fake, pl.id, {0})])
    fake.add_uris(pl.id, [track("Z").uri])  # someone edits the playlist in Spotify meanwhile
    fake.calls.clear()

    with pytest.raises(StalePlanError):
        apply_plan(plan, fake, backups)
    assert not any(c[0] in {"remove_uris", "add_uris", "replace_uris"} for c in fake.calls)
    assert backups.list() == []


def test_restore_round_trip(backups):
    a, b, c = track("A"), track("B"), track("C")
    fake = FakeSpotifyClient()
    pl = fake.put(playlist(), [a, b, c])
    apply_plan(ChangePlan(id="1", title="remove b", changes=[_change(fake, pl.id, {1})]), fake, backups)
    assert fake.uris(pl.id) == [a.uri, c.uri]

    backup_id = backups.list()[0].id
    meta, saved_items = backups.get(backup_id)
    restore = ChangePlan(id="2", title="restore", changes=[
        PlaylistChange(playlist=fake.get_playlist(pl.id), replace_with=[i.track for i in saved_items])])
    result = apply_plan(restore, fake, backups)

    assert fake.uris(pl.id) == [a.uri, b.uri, c.uri]
    assert len(result.backup_ids) == 1  # restoring is itself undoable
    assert len(backups.list()) == 2


def test_apply_creates_new_playlist(backups):
    fake = FakeSpotifyClient()
    tracks = [track("A"), track("B")]
    plan = ChangePlan(id="x", title="merge", create=NewPlaylist(name="Merged", description="", tracks=tracks))

    result = apply_plan(plan, fake, backups)

    assert result.created is not None
    assert fake.uris(result.created.id) == [t.uri for t in tracks]
