"""FastAPI web UI. Routes stay thin: load data via Library, compute via features/, write via apply.py."""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.datastructures import FormData

from .apply import StalePlanError, apply_plan
from .auth import Auth, NotLoggedIn
from .backup import BackupStore
from .cache import Cache
from .features import new_plan_id
from .features.dedupe import build_dedupe_plan, find_duplicates
from .features.merge_move import build_merge_plan, build_move_plan
from .features.orphans import find_orphans
from .features.overlap import overlap_matrix, shared_tracks
from .features.split import analyze_split, build_split_plan
from .library import Library
from .matching import SongIndex
from .models import ChangePlan, Playlist, PlaylistChange
from .spotify_client import SpotifyClient, SpotifyError

PKG = Path(__file__).parent
DEFAULT_REDIRECT = "http://127.0.0.1:8000/callback"


class NotConfigured(Exception):
    pass


class UserFacingError(Exception):
    pass


async def _form(request: Request) -> FormData:
    return await request.form()


Form = Annotated[FormData, Depends(_form)]


def _ints(values) -> set[int]:
    return {int(v) for v in values}


def create_app(client=None, data_dir: str | Path | None = None) -> FastAPI:
    """Pass `client` to run against a fake Spotify (tests); otherwise configured from .env."""
    load_dotenv()
    data_dir = Path(data_dir or os.environ.get("SPOTIFY_HELPER_DATA", "data"))
    auth: Auth | None = None
    if client is None:
        client_id = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
        if client_id and client_id != "your-client-id":
            redirect = os.environ.get("SPOTIFY_REDIRECT_URI", DEFAULT_REDIRECT)
            auth = Auth(client_id, redirect, str(data_dir / "token_cache.json"))
            client = SpotifyClient(auth.access_token)

    library = Library(client, Cache(data_dir / "spotify_helper.db")) if client else None
    backups = BackupStore(data_dir / "spotify_helper.db")
    plans: dict[str, ChangePlan] = {}

    app = FastAPI(title="Spotify Helper")
    app.mount("/static", StaticFiles(directory=PKG / "static"), name="static")
    templates = Jinja2Templates(directory=PKG / "templates")

    @app.middleware("http")
    async def no_store(request: Request, call_next):
        response = await call_next(request)
        if not request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"  # pages reflect live Spotify data; never reuse them
        return response

    def render(request: Request, name: str, status_code: int = 200, **ctx) -> HTMLResponse:
        return templates.TemplateResponse(request, name, ctx, status_code=status_code)

    def lib() -> Library:
        if library is None:
            raise NotConfigured()
        return library

    def store_plan(plan: ChangePlan) -> RedirectResponse:
        plans[plan.id] = plan
        return RedirectResponse(f"/plans/{plan.id}", status_code=303)

    def fresh(pid: str, expected_snapshot: str | None) -> Playlist:
        """Current playlist; refuse if it changed since the page the user is submitting was rendered."""
        pl = lib().playlist(pid)
        if expected_snapshot is not None and pl.snapshot_id != expected_snapshot:
            raise StalePlanError(f"“{pl.name}” changed in Spotify since you loaded that page. Reload and try again.")
        return pl

    def by_id(ids: list[str]) -> list[Playlist]:
        editable = {p.id: p for p in lib().editable_playlists()}
        return [editable[i] for i in dict.fromkeys(ids) if i in editable]

    # --- error handling --------------------------------------------------
    @app.exception_handler(NotConfigured)
    def _not_configured(request: Request, exc: NotConfigured):
        return render(request, "setup.html", redirect_uri=os.environ.get("SPOTIFY_REDIRECT_URI", DEFAULT_REDIRECT))

    @app.exception_handler(NotLoggedIn)
    def _not_logged_in(request: Request, exc: NotLoggedIn):
        return RedirectResponse("/", status_code=303)

    @app.exception_handler(StalePlanError)
    @app.exception_handler(SpotifyError)
    @app.exception_handler(UserFacingError)
    def _user_error(request: Request, exc: Exception):
        return render(request, "error.html", status_code=400, message=str(exc))

    # --- auth & home -----------------------------------------------------
    @app.get("/")
    def index(request: Request):
        library = lib()
        if auth and not auth.is_logged_in():
            return render(request, "login.html")
        pls = library.playlists()
        uid = library.user_id
        return render(request, "index.html",
                      editable=[p for p in pls if p.editable_by(uid)],
                      others=[p for p in pls if not p.editable_by(uid)])

    @app.get("/login")
    def login():
        if auth is None:
            return RedirectResponse("/", status_code=303)
        return RedirectResponse(auth.login_url(), status_code=303)

    @app.get("/callback")
    def callback(code: str | None = None, state: str | None = None, error: str | None = None):
        if auth is None:
            return RedirectResponse("/", status_code=303)
        if error or not code:
            raise UserFacingError(f"Spotify login was cancelled or failed ({error or 'no code'}).")
        try:
            auth.finish_login(code, state)
        except ValueError as e:
            raise UserFacingError(str(e)) from e
        lib().forget_user()
        return RedirectResponse("/", status_code=303)

    @app.post("/logout")
    def logout():
        if auth:
            auth.logout()
            lib().forget_user()
        return RedirectResponse("/", status_code=303)

    # --- plans (preview / apply) ----------------------------------------
    @app.get("/plans/{plan_id}")
    def plan_preview(request: Request, plan_id: str):
        plan = plans.get(plan_id)
        if plan is None:
            raise UserFacingError("That preview has expired (the app may have restarted). Please start again.")
        return render(request, "plan.html", plan=plan)

    @app.post("/plans/{plan_id}/apply")
    def plan_apply(request: Request, plan_id: str):
        plan = plans.pop(plan_id, None)
        if plan is None:
            raise UserFacingError("That preview has expired or was already applied.")
        result = apply_plan(plan, lib().client, backups)
        for before, after in result.updated:
            lib().remember_write(before, after)
        if result.created:
            lib().remember_write(None, result.created)
        return render(request, "result.html", plan=plan, result=result, created=result.created is not None,
                      totals={after.id: after.total for _, after in result.updated})

    # --- dedupe ----------------------------------------------------------
    @app.get("/dedupe/{pid}")
    def dedupe_page(request: Request, pid: str):
        pl = lib().playlist(pid)
        groups = find_duplicates(lib().items(pl))
        return render(request, "dedupe.html", playlist=pl, groups=groups)

    @app.post("/dedupe/{pid}")
    def dedupe_submit(pid: str, form: Form):
        pl = fresh(pid, form.get("snapshot_id"))
        groups = find_duplicates(lib().items(pl))
        include = _ints(form.getlist("include"))
        keep = {gi: int(form[f"keep_{gi}"]) for gi in include if f"keep_{gi}" in form}
        return store_plan(build_dedupe_plan(pl, groups, keep, include))

    # --- split -----------------------------------------------------------
    @app.get("/split")
    def split_page(request: Request, big: str | None = None, targets: Annotated[list[str], Query()] = []):
        editable = lib().editable_playlists()
        result = big_pl = None
        chosen = by_id([t for t in targets if t != big])
        if big and chosen:
            big_pl = next((p for p in editable if p.id == big), None)
            if big_pl is None:
                raise UserFacingError("You can only split a playlist you own or collaborate on.")
            result = analyze_split(lib().items(big_pl), [(p, lib().items(p)) for p in chosen])
        return render(request, "split.html", editable=editable, big=big_pl, targets=chosen,
                      target_ids={p.id for p in chosen}, result=result)

    @app.post("/split")
    def split_submit(form: Form):
        pl = fresh(form["big"], form.get("snapshot_id"))
        return store_plan(build_split_plan(pl, lib().items(pl), _ints(form.getlist("positions"))))

    # --- orphans ---------------------------------------------------------
    @app.get("/orphans")
    def orphans_page(request: Request, refresh: bool = False):
        fetched_at, liked = lib().liked(refresh=refresh)
        editable = lib().editable_playlists()
        orphans = find_orphans(liked, (lib().items(p) for p in editable))
        return render(request, "orphans.html", orphans=orphans, liked_count=len(liked),
                      playlist_count=len(editable), fetched_at=fetched_at)

    # --- overlap ---------------------------------------------------------
    @app.get("/overlap")
    def overlap_page(request: Request, ids: Annotated[list[str], Query()] = []):
        editable = lib().editable_playlists()
        chosen = by_id(ids)
        matrix = overlap_matrix([(p, lib().items(p)) for p in chosen]) if len(chosen) >= 2 else None
        return render(request, "overlap.html", editable=editable, chosen=chosen,
                      chosen_ids={p.id for p in chosen}, matrix=matrix)

    @app.get("/overlap/pair")
    def overlap_pair(request: Request, a: str, b: str):
        pa, pb = lib().playlist(a), lib().playlist(b)
        return render(request, "overlap_pair.html", a=pa, b=pb, shared=shared_tracks(lib().items(pa), lib().items(pb)))

    # --- merge / move ----------------------------------------------------
    @app.get("/merge")
    def merge_page(request: Request):
        return render(request, "merge.html", editable=lib().editable_playlists())

    @app.post("/merge")
    def merge_submit(form: Form):
        sources = by_id(form.getlist("ids"))
        name = (form.get("name") or "").strip()
        if len(sources) < 2 or not name:
            raise UserFacingError("Pick at least two playlists and give the new playlist a name.")
        return store_plan(build_merge_plan(name, [(p, lib().items(p)) for p in sources]))

    @app.get("/move")
    def move_page(request: Request, src: str | None = None, dst: str | None = None):
        editable = lib().editable_playlists()
        rows = src_pl = dst_pl = None
        if src and dst and src != dst:
            found = by_id([src, dst])
            if len(found) != 2:
                raise UserFacingError("You can only move tracks between playlists you own or collaborate on.")
            src_pl, dst_pl = found
            dst_index = SongIndex(i.track for i in lib().items(dst_pl))
            rows = [(it, dst_index.find(it.track)) for it in lib().items(src_pl) if it.track.available]
        return render(request, "move.html", editable=editable, src=src_pl, dst=dst_pl, rows=rows)

    @app.post("/move")
    def move_submit(form: Form):
        src = fresh(form["src"], form.get("snapshot_id"))
        dst = lib().playlist(form["dst"])
        positions = _ints(form.getlist("positions"))
        if not positions:
            raise UserFacingError("Tick at least one track to move.")
        return store_plan(build_move_plan(src, lib().items(src), positions, dst, lib().items(dst)))

    # --- backups ---------------------------------------------------------
    @app.get("/backups")
    def backups_page(request: Request):
        return render(request, "backups.html", backups=backups.list())

    @app.get("/backups/{backup_id}")
    def backup_detail(request: Request, backup_id: int):
        try:
            meta, items = backups.get(backup_id)
        except KeyError:
            raise UserFacingError("No such backup.") from None
        return render(request, "backup_detail.html", meta=meta, items=items)

    @app.post("/backups/{backup_id}/restore")
    def backup_restore(backup_id: int):
        try:
            meta, saved = backups.get(backup_id)
        except KeyError:
            raise UserFacingError("No such backup.") from None
        current = lib().playlist(meta.playlist_id)
        then = [i.track for i in saved if i.track.available]
        now_counts = Counter(i.track.uri for i in lib().items(current) if i.track.available)
        then_counts = Counter(t.uri for t in then)
        back = sum((then_counts - now_counts).values())
        gone = sum((now_counts - then_counts).values())
        plan = ChangePlan(
            id=new_plan_id(),
            title=f"Restore “{current.name}” from backup of {meta.created_at}",
            changes=[PlaylistChange(playlist=current, replace_with=then)],
            notes=[f"{back} track(s) will come back; {gone} track(s) not in the backup will be removed.",
                   "Spotify resets the “date added” of every track when a playlist is restored.",
                   "The current version is backed up first, so this restore can be undone too."],
        )
        return store_plan(plan)

    return app


def app() -> FastAPI:  # factory for `uvicorn --factory spotify_helper.app:app`
    return create_app()
