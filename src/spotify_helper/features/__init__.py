"""Pure feature logic: take playlists/tracks in, return findings or ChangePlans. No API calls."""

import uuid


def new_plan_id() -> str:
    return uuid.uuid4().hex
