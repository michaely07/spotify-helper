"""`python -m spotify_helper` starts the app on the host/port from SPOTIFY_REDIRECT_URI."""

import os
import webbrowser
from urllib.parse import urlparse

import uvicorn
from dotenv import load_dotenv

from .app import DEFAULT_REDIRECT

if __name__ == "__main__":
    load_dotenv()
    url = urlparse(os.environ.get("SPOTIFY_REDIRECT_URI", DEFAULT_REDIRECT))
    host, port = url.hostname or "127.0.0.1", url.port or 8000
    print(f"Spotify Helper running at http://{host}:{port}  (Ctrl+C to stop)")
    webbrowser.open(f"http://{host}:{port}/")
    uvicorn.run("spotify_helper.app:app", factory=True, host=host, port=port, log_level="warning")
