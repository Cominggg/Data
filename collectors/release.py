import logging
import os
import time
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_BASE_URL = "https://musicbrainz.org/ws/2"
_USER_AGENT = os.environ.get("MUSICBRAINZ_USER_AGENT")
if not _USER_AGENT:
    raise ValueError("MUSICBRAINZ_USER_AGENT 환경변수가 설정되지 않았습니다.")
_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "application/json",
}
_RATE_LIMIT_SLEEP = 1.1
_PAGE_LIMIT = 100
_ALLOWED_TYPES = {"Album", "Single", "EP"}
_CAA_BASE_URL = "https://coverartarchive.org"


def _get(path: str, params: dict) -> dict:
    time.sleep(_RATE_LIMIT_SLEEP)
    url = f"{_BASE_URL}{path}"
    response = requests.get(url, headers=_HEADERS, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def _fetch_release_groups(artist_mbid: str, offset: int) -> dict:
    return _get(
        "/release-group/",
        {
            "artist": artist_mbid,
            "inc": "releases",
            "fmt": "json",
            "limit": _PAGE_LIMIT,
            "offset": offset,
        },
    )


def _fetch_tracks(release_mbid: str) -> dict:
    return _get(
        f"/release/{release_mbid}",
        {"inc": "recordings+labels", "fmt": "json"},
    )


def _parse_label(release_data: dict) -> Optional[str]:
    label_info = release_data.get("label-info", [])
    if not label_info:
        return None
    label = label_info[0].get("label") or {}
    return label.get("name")


def _parse_tracks(release_data: dict) -> list[dict]:
    tracks = []
    for medium in release_data.get("media", []):
        for track in medium.get("tracks", []):
            recording = track.get("recording", {})
            tracks.append(
                {
                    "mbid": recording.get("id"),
                    "title": track.get("title"),
                    "position": track.get("position"),
                    "length_ms": track.get("length"),
                }
            )
    return tracks


def _fetch_cover_art_url(release_group_mbid: str) -> Optional[str]:
    time.sleep(_RATE_LIMIT_SLEEP)
    url = f"{_CAA_BASE_URL}/release-group/{release_group_mbid}/front"
    response = requests.get(url, allow_redirects=False, timeout=30)
    if response.status_code in (301, 302, 307, 308):
        return response.headers.get("Location")
    if response.status_code == 404:
        return None
    response.raise_for_status()


def _get_representative_release_mbid(release_group: dict) -> Optional[str]:
    releases = release_group.get("releases", [])
    if not releases:
        return None
    first_release_date = release_group.get("first-release-date", "")
    for release in releases:
        if release.get("date", "") == first_release_date:
            return release.get("id")
    return releases[0].get("id")


def collect_releases(artist_mbid: str) -> list[dict]:
    """아티스트의 릴리즈 그룹(앨범·싱글·EP) 수집."""
    logger.info("릴리즈 수집 시작: artist_mbid=%s", artist_mbid)
    results = []
    offset = 0

    while True:
        logger.debug("릴리즈 그룹 조회 offset=%d", offset)
        page = _fetch_release_groups(artist_mbid, offset)
        batch = page.get("release-groups", [])
        total = page.get("release-group-count", 0)

        if not batch:
            break

        for rg in [r for r in batch if r.get("primary-type") in _ALLOWED_TYPES]:
            rg_mbid = rg.get("id")
            release_mbid = _get_representative_release_mbid(rg)

            tracks = []
            label = None
            if release_mbid:
                try:
                    release_data = _fetch_tracks(release_mbid)
                    tracks = _parse_tracks(release_data)
                    label = _parse_label(release_data)
                except requests.RequestException as e:
                    logger.warning("트랙 수집 실패 release_mbid=%s: %s", release_mbid, e)

            cover_url = None
            if rg_mbid:
                try:
                    cover_url = _fetch_cover_art_url(rg_mbid)
                except requests.RequestException as e:
                    logger.warning("커버 아트 수집 실패 release_group_mbid=%s: %s", rg_mbid, e)

            results.append(
                {
                    "release_group_mbid": rg_mbid,
                    "artist_mbid": artist_mbid,
                    "title": rg.get("title"),
                    "type": rg.get("primary-type"),
                    "first_release_date": rg.get("first-release-date") or None,
                    "representative_release_mbid": release_mbid,
                    "cover_url": cover_url,
                    "label": label,
                    "tracks": tracks,
                }
            )

        offset += len(batch)
        logger.info("진행: %d / %d", offset, total)

        if offset >= total:
            break

    logger.info("릴리즈 수집 완료: artist_mbid=%s, 총 %d건", artist_mbid, len(results))
    return results
