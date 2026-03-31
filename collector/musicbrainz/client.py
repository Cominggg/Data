import logging
import time

import requests

from collector.config import settings

logger = logging.getLogger(__name__)

_RATE_LIMIT_SLEEP = 1.1  # MusicBrainz 정책: 초당 1 요청 이하


class MusicBrainzClient:
    """MusicBrainz Web API 클라이언트.

    모든 요청 후 1.1초 sleep을 강제해 rate limit을 준수한다.
    """

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": (
                    f"{settings.musicbrainz_app_name}/{settings.musicbrainz_app_version}"
                    f" ( {settings.musicbrainz_contact} )"
                ),
                "Accept": "application/json",
            }
        )

    def _get(self, endpoint: str, params: dict) -> dict:
        url = f"{settings.musicbrainz_base_url}/{endpoint}"
        logger.debug("MusicBrainz GET %s params=%s", url, params)
        response = self._session.get(url, params=params, timeout=30)
        response.raise_for_status()
        time.sleep(_RATE_LIMIT_SLEEP)
        return response.json()

    def search_artists(self, query: str, limit: int = 25, offset: int = 0) -> dict:
        """아티스트 이름으로 검색한다."""
        return self._get(
            "artist",
            {"query": query, "limit": limit, "offset": offset, "fmt": "json"},
        )

    def get_artist(self, mbid: str, includes: list[str] | None = None) -> dict:
        """mbid로 아티스트 상세 정보를 가져온다."""
        params: dict = {"fmt": "json"}
        if includes:
            params["inc"] = "+".join(includes)
        return self._get(f"artist/{mbid}", params)
