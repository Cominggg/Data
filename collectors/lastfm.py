from __future__ import annotations

import logging
import os
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_API_URL = "https://ws.audioscrobbler.com/2.0/"
_API_KEY = os.environ.get("LASTFM_API_KEY")


def _query_listeners(params: dict) -> Optional[int]:
    """Last.fm API를 호출해 월간 리스너 수를 반환한다. 실패 시 None 반환."""
    try:
        response = requests.get(
            _API_URL,
            params={"method": "artist.getInfo", "api_key": _API_KEY, "format": "json", **params},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            logger.debug("Last.fm API 오류 — params=%s, code=%s", params, data.get("error"))
            return None
        listeners = data.get("artist", {}).get("stats", {}).get("listeners")
        if listeners is None:
            return None
        return int(listeners)
    except (requests.RequestException, ValueError) as e:
        logger.debug("Last.fm 리스너 조회 실패 — params=%s: %s", params, e)
        return None


def get_monthly_listeners(mbid: str, names: Optional[list[str]] = None) -> Optional[int]:
    """MBID와 후보 이름 목록을 모두 조회해 최댓값 반환."""
    if not _API_KEY:
        logger.warning("LASTFM_API_KEY 환경변수가 설정되지 않아 리스너 수 조회를 건너뜁니다.")
        return None

    results = []

    result = _query_listeners({"mbid": mbid})
    if result is not None:
        results.append(result)

    for name in (names or []):
        result = _query_listeners({"artist": name})
        if result is not None:
            logger.debug("Last.fm 이름 조회 — name=%s, listeners=%d", name, result)
            results.append(result)

    return max(results) if results else None
