from __future__ import annotations

import logging
import os
import re
import time
from typing import Optional
from urllib.parse import urlparse

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
_MAX_ARTISTS = 10_000
_ALLOWED_URL_DOMAINS = {
    "instagram.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "youtu.be",
    "open.spotify.com",
    "music.apple.com",
}


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
            "query": "tag:j-pop AND country:JP AND (type:Group OR type:Person)",
            "fmt": "json",
            "limit": _PAGE_LIMIT,
            "offset": offset,
        },
    )


def _fetch_artist_detail(mbid: str) -> dict:
    return _get(
        f"/artist/{mbid}",
        {"inc": "aliases+url-rels", "fmt": "json"},
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
    result = []
    for rel in relations:
        if rel.get("target-type") != "url":
            continue
        resource = rel.get("url", {}).get("resource", "")
        netloc = urlparse(resource).netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        if netloc in _ALLOWED_URL_DOMAINS:
            result.append({"type": rel.get("type", ""), "url": resource})
    return result


def _parse_date(raw: Optional[str]) -> Optional[str]:
    """YYYY-MM-DD 형식만 유효로 인정하고, 그 외는 None 반환."""
    if raw and re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return raw
    return None


def _parse_artist(detail: dict) -> dict:
    relations = detail.get("relations", [])
    life_span = detail.get("life-span", {})

    return {
        "mbid": detail.get("id"),
        "name": detail.get("name"),
        "sort_name": detail.get("sort-name"),
        "aliases": _parse_aliases(detail.get("aliases", [])),
        "url_rels": _parse_url_rels(relations),
        "debut_date": _parse_date(life_span.get("begin")),
    }


def collect_artists(skip_mbids: set[str] | None = None) -> list[dict]:
    """country=JP, tag=j-pop 조건으로 아티스트 전체 수집 후 파싱된 리스트 반환.

    skip_mbids: 이미 DB에 저장된 MBID 집합. 상세 조회를 건너뛰어 재개 시 시간을 절약한다.
    """
    skip = skip_mbids or set()
    logger.info("MusicBrainz 아티스트 수집 시작 (건너뜀: %d건)", len(skip))
    artists = []
    offset = 0

    while True:
        logger.debug("아티스트 검색 offset=%d", offset)
        for attempt in range(1, 4):
            try:
                page = _search_artists(offset)
                break
            except requests.RequestException as e:
                if attempt == 3:
                    logger.error("페이지 수집 실패 (offset=%d), 3회 시도 후 중단: %s", offset, e)
                    return artists
                logger.warning("페이지 수집 실패 (offset=%d), %d/3회 재시도: %s", offset, attempt, e)
                time.sleep(5 * attempt)
        batch = page.get("artists", [])
        total = page.get("count", 0)

        if not batch:
            break

        for item in batch:
            mbid = item.get("id")
            if not mbid:
                continue
            if mbid in skip:
                logger.debug("건너뜀(기존): %s (%s)", item.get("name"), mbid)
                continue
            for attempt in range(1, 4):
                try:
                    detail = _fetch_artist_detail(mbid)
                    artists.append(_parse_artist(detail))
                    logger.info("수집 완료: %s (%s)", item.get("name"), mbid)
                    break
                except requests.RequestException as e:
                    if attempt == 3:
                        logger.warning("아티스트 상세 수집 실패 mbid=%s: %s", mbid, e)
                    else:
                        logger.debug("아티스트 상세 재시도 %d/3 mbid=%s: %s", attempt, mbid, e)
                        time.sleep(5 * attempt)

        offset += len(batch)
        logger.info("진행: %d / %d", offset, total)

        if offset >= total or offset >= _MAX_ARTISTS:
            if offset >= _MAX_ARTISTS:
                logger.warning("최대 수집 한도(%d)에 도달해 수집을 중단합니다.", _MAX_ARTISTS)
            break

    logger.info("MusicBrainz 아티스트 수집 완료: 총 %d건", len(artists))
    return artists
