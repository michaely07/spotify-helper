# Spotify Helper

A local web tool for tidying up Spotify playlists. It runs on your own computer, and your data stays in `data/`.

| Feature | What it does |
|---|---|
| **Find duplicates** | Finds the same song more than once in a playlist, including different releases of one song (single vs. album, remasters, "feat." variants). The album version is pre-selected to keep. |
| **Split** | For a big playlist, shows which tracks are already in the playlists you pick, lists what's left to sort, and can remove the already-sorted tracks. |
| **Orphans** | Lists Liked Songs that aren't in any of your playlists. |
| **Overlap** | Shows a grid of how many tracks each pair of playlists shares. Click a number to see the tracks. |
| **Merge** | Combines playlists into a new private one, without duplicates. |
| **Move** | Adds tracks to one playlist and removes them from another in a single step. |
| **Backups** | Saves each playlist automatically before any change. You can restore any backup. |

Before anything changes in Spotify, you see a preview and have to confirm it.

## Setup (once)

1. Create an app at <https://developer.spotify.com/dashboard> (tick **Web API**).
   - Redirect URI: `http://127.0.0.1:8000/callback` (Spotify rejects `localhost`).
   - Under **User Management**, add the email of your Spotify account.
   - Spotify requires the app owner to have **Premium** for development-mode apps.
2. Copy `.env.example` to `.env` and paste in the app's **Client ID**. No client secret is needed, because the app logs in with PKCE.
3. Install:
   ```
   python -m venv .venv
   .venv\Scripts\python -m pip install -e ".[dev]"
   ```

## Run

```
.venv\Scripts\python -m spotify_helper
```

This opens <http://127.0.0.1:8000> in your browser.

## How "same song" is decided

The checks below run from strongest to weakest. Every feature uses them, and the UI shows a badge for which one matched:

1. **same track**: the identical Spotify track.
2. **same recording**: the same ISRC (the industry ID of a recording), e.g. the single and the album release.
3. **likely same**: the same title after removing remaster, year, "feat." and "album version" tags, the same main artist, and lengths within 3 seconds. Live versions, remixes, radio edits and acoustic versions stay separate songs.

## Limits imposed by Spotify (2026)

- Apps can only read the contents of playlists you **own or collaborate on**. Followed playlists are listed but can't be scanned.
- Spotify's remove call deletes *every* copy of a track. To remove only some copies, the tool removes them all and puts back the copies you keep, in their original positions. Those re-added copies get a new "date added".
- Restoring a backup also resets "date added". Local files can't be removed or restored through the API, so the tool always leaves them alone.

## Development

```
.venv\Scripts\python -m pytest
```

Tests use a fake Spotify client (`tests/fake_spotify.py`) that copies the real API's write behaviour, so they never touch your account.
