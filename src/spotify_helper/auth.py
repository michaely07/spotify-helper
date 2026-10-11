"""Spotify login using the PKCE flow, so only a Client ID is needed (no client secret on disk)."""

from __future__ import annotations

import secrets

from spotipy.cache_handler import CacheFileHandler
from spotipy.oauth2 import SpotifyPKCE

SCOPES = " ".join([
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-private",
    "playlist-modify-public",
    "user-library-read",
])


class NotLoggedIn(Exception):
    pass


class Auth:
    def __init__(self, client_id: str, redirect_uri: str, token_cache_path: str):
        self._pkce = SpotifyPKCE(
            client_id=client_id,
            redirect_uri=redirect_uri,
            scope=SCOPES,
            cache_handler=CacheFileHandler(cache_path=token_cache_path),
            open_browser=False,
        )
        self._state: str | None = None

    def login_url(self) -> str:
        self._pkce.get_pkce_handshake_parameters()  # fresh verifier per login attempt
        self._state = secrets.token_urlsafe(16)
        return self._pkce.get_authorize_url(state=self._state)

    def finish_login(self, code: str, state: str | None) -> None:
        if not self._state or state != self._state:
            raise ValueError("Login state mismatch; please start the login again.")
        self._state = None
        self._pkce.get_access_token(code=code, check_cache=False)

    def access_token(self) -> str:
        try:
            info = self._pkce.validate_token(self._pkce.cache_handler.get_cached_token())  # refreshes if expired
        except Exception:  # revoked/invalid refresh token
            info = None
        if not info:
            raise NotLoggedIn()
        return info["access_token"]

    def is_logged_in(self) -> bool:
        try:
            self.access_token()
            return True
        except NotLoggedIn:
            return False

    def logout(self) -> None:
        self._pkce.cache_handler.save_token_to_cache({})
