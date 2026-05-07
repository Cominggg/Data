from __future__ import annotations

import logging
import time

import requests

logger = logging.getLogger(__name__)

_API_URL = "https://ko.wikipedia.org/w/api.php"
_RATE_LIMIT_SLEEP = 0.5
_KOREAN_RANGE = range(0xAC00, 0xD7A4)  # 가–힣


def _is_korean(text: str) -> bool:
    return any(ord(c) in _KOREAN_RANGE for c in text)


def _fetch_redirects(name: str) -> list[str]:
    """Korean Wikipedia에서 name 페이지로 리다이렉트되는 페이지 제목 목록을 반환한다."""
    params = {
        "action": "query",
        "titles": name,
        "prop": "redirects",
        "rdlimit": "500",
        "format": "json",
    }
    try:
        time.sleep(_RATE_LIMIT_SLEEP)
        resp = requests.get(_API_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.warning("Wikipedia API 요청 실패 — name=%s: %s", name, e)
        return []

    pages = data.get("query", {}).get("pages", {})
    redirects = []
    for page in pages.values():
        for rd in page.get("redirects", []):
            title = rd.get("title", "")
            if title:
                redirects.append(title)
    return redirects


def collect_korean_aliases(artists: list[dict]) -> list[dict]:
    """아티스트 목록을 받아 Korean Wikipedia redirect 기반 한국어 alias를 반환한다.

    artists: [{"artist_id": int, "name": str}]
    반환: [{"artist_id": int, "name": str, "locale": "ko"}]
    """
    result: list[dict] = []
    logger.info("Wikipedia 한국어 alias 수집 시작: %d건", len(artists))

    for artist in artists:
        artist_id = artist["artist_id"]
        name = artist["name"]
        redirects = _fetch_redirects(name)
        korean = [r for r in redirects if _is_korean(r)]
        for alias_name in korean:
            result.append({"artist_id": artist_id, "name": alias_name, "locale": "ko"})
        if korean:
            logger.debug("alias 수집: %s → %s", name, korean)

    logger.info("Wikipedia 한국어 alias 수집 완료: %d건", len(result))
    return result
