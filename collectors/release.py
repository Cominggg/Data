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
    """YYYY-MM-DD 형식만 유효로 인정하고, 부분 날짜(YYYY·YYYY-MM)는 None 반환."""
    if raw and re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return raw
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
            "type": "album|single|ep",
            "fmt": "json",
            "limit": _PAGE_LIMIT,
            "offset": offset,
        },
    )


def _fetch_releases_for_group(release_group_mbid: str) -> list[dict]:
    data = _get(
        "/release/",
        {"release-group": release_group_mbid, "fmt": "json", "limit": 100},
    )
    return data.get("releases", [])


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


def _get_representative_release_mbid(release_group: dict, releases: list) -> Optional[str]:
    if not releases:
        return None
    first_release_date = release_group.get("first-release-date", "")
    for release in releases:
        if release.get("date", "") == first_release_date:
            return release.get("id")
    return releases[0].get("id")


def collect_cover_art(release_group_mbid: str) -> Optional[str]:
    """단일 release_group의 커버아트 URL을 수집한다. 404 또는 오류 시 None 반환."""
    try:
        return _fetch_cover_art_url(release_group_mbid)
    except requests.RequestException as e:
        logger.warning("커버 아트 수집 실패 release_group_mbid=%s: %s", release_group_mbid, e)
        return None


def collect_release_group(release_group_mbid: str, artist_mbid: str) -> Optional[dict]:
    """단일 release_group의 데이터(트랙·레이블 포함)를 수집한다. 허용 타입이 아니거나 오류 시 None 반환."""
    try:
        rg_data = _get(f"/release-group/{release_group_mbid}", {"fmt": "json"})
    except requests.RequestException as e:
        logger.warning("릴리즈 그룹 조회 실패: mbid=%s, %s", release_group_mbid, e)
        return None

    if rg_data.get("primary-type") not in _ALLOWED_TYPES:
        logger.info("허용되지 않는 타입 — 건너뜀: mbid=%s, type=%s", release_group_mbid, rg_data.get("primary-type"))
        return None

    releases_in_group: list[dict] = []
    try:
        releases_in_group = _fetch_releases_for_group(release_group_mbid)
    except requests.RequestException as e:
        logger.warning("릴리즈 목록 조회 실패: mbid=%s, %s", release_group_mbid, e)

    release_mbid = _get_representative_release_mbid(rg_data, releases_in_group)
    tracks: list[dict] = []
    label = None
    if release_mbid:
        try:
            release_data = _fetch_tracks(release_mbid)
            tracks = _parse_tracks(release_data)
            label = _parse_label(release_data)
        except requests.RequestException as e:
            logger.warning("트랙 수집 실패: release_mbid=%s, %s", release_mbid, e)

    return {
        "release_group_mbid": release_group_mbid,
        "artist_mbid": artist_mbid,
        "title": rg_data.get("title"),
        "type": rg_data.get("primary-type"),
        "first_release_date": _parse_release_date(rg_data.get("first-release-date")),
        "representative_release_mbid": release_mbid,
        "cover_url": None,
        "label": label,
        "tracks": tracks,
    }


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
            releases_in_group = []
            if rg_mbid:
                try:
                    releases_in_group = _fetch_releases_for_group(rg_mbid)
                except requests.RequestException as e:
                    logger.warning("릴리즈 목록 수집 실패 release_group_mbid=%s: %s", rg_mbid, e)
            release_mbid = _get_representative_release_mbid(rg, releases_in_group)

            tracks = []
            label = None
            if release_mbid:
                try:
                    release_data = _fetch_tracks(release_mbid)
                    tracks = _parse_tracks(release_data)
                    label = _parse_label(release_data)
                except requests.RequestException as e:
                    logger.warning("트랙 수집 실패 release_mbid=%s: %s", release_mbid, e)

            results.append(
                {
                    "release_group_mbid": rg_mbid,
                    "artist_mbid": artist_mbid,
                    "title": rg.get("title"),
                    "type": rg.get("primary-type"),
                    "first_release_date": _parse_release_date(rg.get("first-release-date")),
                    "representative_release_mbid": release_mbid,
                    "cover_url": None,
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
