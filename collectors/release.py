import logging
import os
import re
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


def _parse_release_date(raw: Optional[str]) -> Optional[str]:
    """MusicBrainz first-release-date를 DB date 컬럼용 YYYY-MM-DD로 정규화.

    YYYY → YYYY-01-01, YYYY-MM → YYYY-MM-01, 그 외 포맷은 None 반환.
    """
    if not raw:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return raw
    if re.match(r"^\d{4}-\d{2}$", raw):
        return f"{raw}-01"
    if re.match(r"^\d{4}$", raw):
        return f"{raw}-01-01"
    return None


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
            mbid = recording.get("id")
            if mbid is None:
                continue
            tracks.append(
                {
                    "mbid": mbid,
                    "title": track.get("title"),
                    "position": track.get("position"),
                    "length_ms": track.get("length"),
                }
            )
    return tracks


def _fetch_cover_art_url(release_group_mbid: str) -> Optional[str]:
    url = f"{_CAA_BASE_URL}/release-group/{release_group_mbid}/front"
    for attempt in range(1, 4):
        time.sleep(_RATE_LIMIT_SLEEP)
        response = requests.get(url, allow_redirects=False, timeout=30)
        if response.status_code in (301, 302, 307, 308):
            return response.headers.get("Location")
        if response.status_code == 404:
            return None
        try:
            response.raise_for_status()
        except requests.RequestException as e:
            if attempt == 3:
                raise
            logger.warning("커버 아트 재시도 %d/3 mbid=%s: %s", attempt, release_group_mbid, e)
            time.sleep(5 * attempt)


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
        for attempt in range(1, 4):
            try:
                page = _fetch_release_groups(artist_mbid, offset)
                break
            except requests.RequestException as e:
                if attempt == 3:
                    logger.error("릴리즈 그룹 수집 실패 (offset=%d), 3회 시도 후 중단: %s", offset, e)
                    return results
                logger.warning("릴리즈 그룹 재시도 %d/3 (offset=%d): %s", attempt, offset, e)
                time.sleep(5 * attempt)
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
                    "first_release_date": _parse_release_date(rg.get("first-release-date")),
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
