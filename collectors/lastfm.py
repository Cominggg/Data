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


def get_monthly_listeners(mbid: str) -> Optional[int]:
    """MusicBrainz MBID로 Last.fm 월간 리스너 수를 반환한다. 조회 실패 시 None 반환."""
    if not _API_KEY:
        logger.warning("LASTFM_API_KEY 환경변수가 설정되지 않아 리스너 수 조회를 건너뜁니다.")
        return None

    try:
        response = requests.get(
            _API_URL,
            params={
                "method": "artist.getInfo",
                "mbid": mbid,
                "api_key": _API_KEY,
                "format": "json",
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        if "error" in data:
            logger.debug("Last.fm API 오류 — mbid=%s, code=%s", mbid, data.get("error"))
            return None

        listeners = data.get("artist", {}).get("stats", {}).get("listeners")
        if listeners is None:
            return None
        return int(listeners)

    except (requests.RequestException, ValueError) as e:
        logger.debug("Last.fm 리스너 조회 실패 — mbid=%s: %s", mbid, e)
        return None
