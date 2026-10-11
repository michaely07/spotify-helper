# Spotify Helper — Design & Implementation Plan

## Context
The user's Spotify playlists have two pain points: (1) the same song appears twice in a playlist (often as different Spotify entries — single vs. album release), and (2) a huge catch-all playlist needs to be broken up, so they want to see which of its tracks already live in other playlists they choose. We're building a local web tool for this, plus agreed extras: backup/undo, orphan finders, and merge/move/overlap. The project directory `C:\Users\zkyu2\spotify-helper` is empty (not a git repo) — greenfield.

Decisions made with the user:
- Local web app, Python: **FastAPI + Jinja2 + htmx**, **Spotipy**, **SQLite** cache/backups.
- Dedupe default keep = **album version** (album_type `album` > `single` > `compilation`; tie → earliest `added_at`).
- Splitter = **report + remove already-placed tracks** from the big playlist (no auto-assigning leftovers).
- Matching uses three tiers including a fuzzy fallback (approved).
- Every destructive action: preview → confirm → auto-backup → apply.

## Project layout
```
spotify-helper/
  pyproject.toml            # fastapi, uvicorn, jinja2, spotipy, python-dotenv; dev: pytest, httpx
  .env.example              # SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI=http://127.0.0.1:8000/callback
  README.md                 # Spotify dashboard setup steps + run instructions
  src/spotify_helper/
    app.py                  # FastAPI app, routes, template wiring
    auth.py                 # Spotipy OAuth (scopes below), token cache file
    spotify_client.py       # thin wrapper: paging, 100-item batching, 429 retry; returns Track models
    models.py               # dataclasses: Track(id, uri, name, artists, album_name, album_type, isrc, duration_ms, added_at, position, is_local), Playlist
    cache.py                # SQLite: playlist tracks keyed by (playlist_id, snapshot_id); liked songs cache
    matching.py             # normalize_title(), track_key tiers, group_duplicates(), same_song()
    features/
      dedupe.py             # find groups + pick default keeper + build removal plan
      split.py              # map big-playlist tracks → target playlists; leftovers; removal plan
      orphans.py            # liked-but-in-no-playlist
      overlap.py            # pairwise shared-track counts
      merge_move.py         # merge (dedup) into new playlist; move tracks src→dst
    backup.py               # snapshot(playlist) → SQLite; list; restore(snapshot)
    apply.py                # executes a ChangePlan: backup first, then API writes
    templates/ static/      # Jinja pages + htmx partials, minimal CSS
  tests/                    # pytest, fixture tracks, FakeSpotifyClient
```

## Key design points
- **Scopes:** `playlist-read-private playlist-read-collaborative playlist-modify-private playlist-modify-public user-library-read`.
- **Redirect URI must be `127.0.0.1`**, not `localhost` (Spotify policy since 2025).
- **Only the user's own (or collaborative) playlists are writable**; UI lists others as read-only targets (fine for splitter matching).
- **Matching tiers (`matching.py`)** — one shared function used by every feature:
  1. `exact`: same track ID
  2. `recording`: same ISRC (`external_ids.isrc`)
  3. `likely`: normalized title (lowercase; strip only remaster/year, `feat.`, and "Album Version" tags — live, remix, radio edit, acoustic stay distinct) + same primary artist + |Δduration| ≤ 3s
  Groups carry the strongest tier so the UI can badge confidence. Local files (`is_local`) match only by name+artist.
- **ChangePlan** (`apply.py`): a list of `{playlist_id, remove: [(uri, positions)], add: [(uri, position)]}`. Preview pages render the plan; confirm posts it back by plan ID (held server-side in memory). `apply` always calls `backup.snapshot()` for each touched playlist first.
- **Removing one copy of an exact-ID duplicate:** Spotify's remove endpoint may drop *all* occurrences of a URI. Step 1 of implementation verifies whether `positions`-specific removal is honored; if not, plan = remove URI entirely then re-insert one copy at the kept position.
- **Restore** = replace playlist items with snapshot URIs (first 100 via replace, rest via add batches). Note in UI: `added_at` dates reset.
- **Endpoint drift:** verify playlist-items endpoint names/fields against current Spotify Web API docs during step 1 (they changed in 2025–26); keep all calls inside `spotify_client.py` so a fix is one place.

## Pages
- `/` playlists list (name, count, owner, writable) + login status
- `/dedupe/{playlist}` duplicate groups, radio per group (album version pre-selected), confirm
- `/split` choose big playlist + targets (checkbox list) → table: track | found in [targets] ; leftovers section ; "remove placed tracks" → preview → confirm
- `/orphans` liked songs not in any of the user's playlists (export-friendly table)
- `/overlap` select playlists → matrix of shared counts (click a cell → shared tracks)
- `/merge`, `/move` forms → preview → confirm
- `/backups` list snapshots, restore button (with preview of diff vs. current)

## Implementation order
1. Scaffold (`git init`, pyproject, .env.example, README with dashboard steps); auth + `spotify_client` fetching playlists/tracks; **probe** removal-by-position behavior & endpoint names on a throwaway playlist.
2. `models`, `cache`, `matching` with unit tests (TDD).
3. `backup` + `apply` (ChangePlan) with FakeSpotifyClient tests.
4. Dedupe feature + page.
5. Split feature + page.
6. Orphans, overlap, merge/move.
7. Backups page + restore.
8. Write spec copy to `docs/superpowers/specs/2026-10-11-spotify-helper-design.md`, commit.

## Verification
- `pytest` — matching tiers (remaster vs. original, feat. variants, live/remix NOT merged, ISRC match across single/album), dedupe keeper selection, split/leftover mapping, overlap counts, ChangePlan always backs up before writes (FakeSpotifyClient records call order).
- Manual E2E: `uvicorn spotify_helper.app:app --host 127.0.0.1 --port 8000`, log in, create a throwaway playlist with a song added twice + single/album versions, run dedupe → confirm one remains; build a mini "big" playlist + two targets, run split → placed tracks removed; restore from backup → original contents return.

## Changes made during implementation
- Spotify's February 2026 API changes: playlist endpoints are now `/playlists/{id}/items` (response fields `items`/`item`), and contents are only readable for playlists the user owns or collaborates on. `DELETE /items` has no per-position removal, so removing some copies is done by removing the URI entirely and re-inserting the kept copies (`apply.plan_removal`). ISRC (`external_ids`) is still available.
- API calls are made directly with httpx (`spotify_client.py`). Spotipy is used only for the PKCE login, so no client secret is needed.
- Plain server-rendered forms plus a small JS file (`static/app.js`) replaced htmx, which wasn't needed.
- Before applying a plan, the app checks that every affected playlist's `snapshot_id` is unchanged and backs up all of them, and only then writes anything.
