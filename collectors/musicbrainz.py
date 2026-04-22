import logging
import time

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://musicbrainz.org/ws/2"
_HEADERS = {
    "User-Agent": "coming-data/0.1.0 (dbgur3315@gmail.com)",
    "Accept": "application/json",
}
_RATE_LIMIT_SLEEP = 1.1
_PAGE_LIMIT = 100


def _get(path: str, params: dict) -> dict:
    time.sleep(_RATE_LIMIT_SLEEP)
    url = f"{_BASE_URL}{path}"
    response = requests.get(url, headers=_HEADERS, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def _search_artists(offset: int) -> dict:
    return _get(
        "/artist/",
        {
            "query": "tag:j-pop AND country:JP",
            "fmt": "json",
            "limit": _PAGE_LIMIT,
            "offset": offset,
        },
    )


def _fetch_artist_detail(mbid: str) -> dict:
    return _get(
        f"/artist/{mbid}",
        {"inc": "aliases+url-rels+artist-rels", "fmt": "json"},
    )


def _parse_aliases(raw_aliases: list) -> list[dict]:
    locale_map = {"ko": "ko", "en": "en", "ja": "ja"}
    result = []
    for alias in raw_aliases:
        locale = alias.get("locale") or ""
        lang = locale.split("-")[0] if locale else ""
        if lang in locale_map:
            result.append({"name": alias.get("name", ""), "locale": lang})
    return result


def _parse_url_rels(relations: list) -> list[dict]:
    return [
        {"type": rel.get("type", ""), "url": rel.get("url", {}).get("resource", "")}
        for rel in relations
        if rel.get("target-type") == "url"
    ]


def _parse_members(relations: list) -> list[dict]:
    members = []
    for rel in relations:
        if rel.get("type") != "member of band":
            continue
        artist = rel.get("artist", {})
        members.append(
            {
                "mbid": artist.get("id"),
                "name": artist.get("name"),
                "sort_name": artist.get("sort-name"),
                "is_current": not rel.get("ended", False),
            }
        )
    return members


def _parse_artist(detail: dict) -> dict:
    relations = detail.get("relations", [])
    life_span = detail.get("life-span", {})

    return {
        "mbid": detail.get("id"),
        "name": detail.get("name"),
        "sort_name": detail.get("sort-name"),
        "aliases": _parse_aliases(detail.get("aliases", [])),
        "url_rels": _parse_url_rels(relations),
        "members": _parse_members(relations),
        "debut_date": life_span.get("begin"),
    }


def collect_artists() -> list[dict]:
    """country=JP, tag=j-pop 조건으로 아티스트 전체 수집 후 파싱된 리스트 반환."""
    logger.info("MusicBrainz 아티스트 수집 시작")
    artists = []
    offset = 0

    while True:
        logger.debug("아티스트 검색 offset=%d", offset)
        page = _search_artists(offset)
        batch = page.get("artists", [])
        total = page.get("count", 0)

        if not batch:
            break

        for item in batch:
            mbid = item.get("id")
            if not mbid:
                continue
            try:
                detail = _fetch_artist_detail(mbid)
                artists.append(_parse_artist(detail))
                logger.debug("수집 완료: %s (%s)", item.get("name"), mbid)
            except requests.HTTPError as e:
                logger.warning("아티스트 상세 수집 실패 mbid=%s: %s", mbid, e)

        offset += len(batch)
        logger.info("진행: %d / %d", offset, total)

        if offset >= total:
            break

    logger.info("MusicBrainz 아티스트 수집 완료: 총 %d건", len(artists))
    return artists
