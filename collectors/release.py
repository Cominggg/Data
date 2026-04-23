import logging
import os
import time

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
_RELEASE_TYPES = "Album|Single|EP"


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
            "type": _RELEASE_TYPES,
            "inc": "releases",
            "fmt": "json",
            "limit": _PAGE_LIMIT,
            "offset": offset,
        },
    )


def _get_representative_release_mbid(release_group: dict) -> str | None:
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

        for rg in batch:
            release_mbid = _get_representative_release_mbid(rg)
            results.append(
                {
                    "release_group_mbid": rg.get("id"),
                    "artist_mbid": artist_mbid,
                    "title": rg.get("title"),
                    "type": rg.get("primary-type"),
                    "first_release_date": rg.get("first-release-date") or None,
                    "representative_release_mbid": release_mbid,
                }
            )

        offset += len(batch)
        logger.info("진행: %d / %d", offset, total)

        if offset >= total:
            break

    logger.info("릴리즈 수집 완료: artist_mbid=%s, 총 %d건", artist_mbid, len(results))
    return results
