import logging
import os
import threading
from typing import Optional, Tuple

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

_running_tasks: set = set()
_running_lock = threading.Lock()


def _acquire_task(key: Tuple) -> bool:
    """키가 이미 실행 중이면 False 반환. 아니면 등록 후 True 반환."""
    with _running_lock:
        if key in _running_tasks:
            return False
        _running_tasks.add(key)
        return True


def _release_task(key: Tuple) -> None:
    with _running_lock:
        _running_tasks.discard(key)


def _wrap(fn, key: Tuple, *args):
    """BackgroundTasks용 래퍼 — 작업 완료 후 키를 해제한다."""
    try:
        fn(*args)
    finally:
        _release_task(key)


def _sync_response(result: dict) -> dict:
    """scheduler.py의 discriminated dict를 동기 API 응답으로 변환한다.

    status: not_found → 404, skipped → success:false + reason, ok → success:true + 데이터.
    """
    status = result["status"]
    if status == "not_found":
        raise HTTPException(status_code=404, detail="not found")
    if status == "skipped":
        return {"success": False, "reason": result["reason"]}
    data = {k: v for k, v in result.items() if k != "status"}
    return {"success": True, **data}


def _verify_secret(x_internal_secret: Optional[str] = Header(default=None)) -> None:
    if not _INTERNAL_SECRET or x_internal_secret != _INTERNAL_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")


class ConcertCollectRequest(BaseModel):
    kopis_id: str


class ArtistRegisterRequest(BaseModel):
    mbid: str


@app.post("/collect/concert")
def trigger_collect_concert(
    req: ConcertCollectRequest,
    _: None = Depends(_verify_secret),
) -> dict:
    key = ("concert", req.kopis_id)
    if not _acquire_task(key):
        raise HTTPException(status_code=409, detail="already running")
    try:
        result = collect_and_save_concert(req.kopis_id)
    finally:
        _release_task(key)
    return _sync_response(result)


@app.post("/collect/artist/{artist_id}/releases", status_code=202)
def trigger_collect_releases(
    artist_id: int,
    background_tasks: BackgroundTasks,
    _: None = Depends(_verify_secret),
) -> dict:
    key = ("releases", artist_id)
    if not _acquire_task(key):
        return {"accepted": False, "reason": "already running"}
    background_tasks.add_task(_wrap, collect_and_save_releases_for_artist, key, artist_id)
    return {"accepted": True}


@app.post("/collect/concert/{concert_id}/setlist")
def trigger_collect_setlist(
    concert_id: int,
    _: None = Depends(_verify_secret),
) -> dict:
    key = ("setlist", concert_id)
    if not _acquire_task(key):
        raise HTTPException(status_code=409, detail="already running")
    try:
        result = collect_and_save_setlist(concert_id)
    finally:
        _release_task(key)
    return _sync_response(result)


@app.post("/collect/artist")
def trigger_register_artist(
    req: ArtistRegisterRequest,
    _: None = Depends(_verify_secret),
) -> dict:
    key = ("artist", req.mbid)
    if not _acquire_task(key):
        raise HTTPException(status_code=409, detail="already running")
    try:
        result = register_artist_by_mbid(req.mbid)
    finally:
        _release_task(key)
    return _sync_response(result)


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
