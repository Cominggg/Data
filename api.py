import logging
import os
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from collectors import kopis, musicbrainz
from scheduler import (
    collect_and_save_concert,
    collect_and_save_releases_for_artist,
    collect_and_save_setlist,
    register_artist_by_mbid,
)

logger = logging.getLogger(__name__)

_INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "")

app = FastAPI(title="Coming Data Internal API", docs_url=None, redoc_url=None)


def _verify_secret(x_internal_secret: Optional[str] = Header(default=None)) -> None:
    if not _INTERNAL_SECRET or x_internal_secret != _INTERNAL_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")


class ConcertCollectRequest(BaseModel):
    kopis_id: str


class ArtistRegisterRequest(BaseModel):
    mbid: str


@app.post("/collect/concert", status_code=202)
def trigger_collect_concert(
    req: ConcertCollectRequest,
    background_tasks: BackgroundTasks,
    _: None = Depends(_verify_secret),
) -> dict:
    background_tasks.add_task(collect_and_save_concert, req.kopis_id)
    return {"accepted": True}


@app.post("/collect/artist/{artist_id}/releases", status_code=202)
def trigger_collect_releases(
    artist_id: int,
    background_tasks: BackgroundTasks,
    _: None = Depends(_verify_secret),
) -> dict:
    background_tasks.add_task(collect_and_save_releases_for_artist, artist_id)
    return {"accepted": True}


@app.post("/collect/concert/{concert_id}/setlist", status_code=202)
def trigger_collect_setlist(
    concert_id: int,
    background_tasks: BackgroundTasks,
    _: None = Depends(_verify_secret),
) -> dict:
    background_tasks.add_task(collect_and_save_setlist, concert_id)
    return {"accepted": True}


@app.post("/collect/artist", status_code=202)
def trigger_register_artist(
    req: ArtistRegisterRequest,
    background_tasks: BackgroundTasks,
    _: None = Depends(_verify_secret),
) -> dict:
    background_tasks.add_task(register_artist_by_mbid, req.mbid)
    return {"accepted": True}


@app.get("/search/artists")
def search_artists_endpoint(
    name: str,
    _: None = Depends(_verify_secret),
) -> list:
    return musicbrainz.search_artists(name)


@app.get("/search/concerts")
def search_concerts_endpoint(
    title: str,
    _: None = Depends(_verify_secret),
) -> list:
    return kopis.search_concerts(title)
