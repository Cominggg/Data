import base64
import logging
import os
import time
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()


class SpotifyRateLimitError(requests.HTTPError):
    """Spotify 429 수신 시 발생. 호출부는 수집된 데이터를 저장하고 처리를 중단해야 한다."""

logger = logging.getLogger(__name__)

_SPOTIFY_AUTH_URL = "https://accounts.spotify.com/api/token"
_SPOTIFY_API_URL = "https://api.spotify.com/v1"

_token_cache: dict = {"token": None, "expires_at": 0.0}


def _get_access_token() -> str:
    """Spotify Client Credentials Flow로 access_token을 발급한다 (모듈 레벨 1h 캐시)."""
    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise ValueError("SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET 환경변수가 설정되지 않았습니다.")

    if _token_cache["token"] and time.time() < _token_cache["expires_at"] - 60:
        return _token_cache["token"]

    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    response = requests.post(
        _SPOTIFY_AUTH_URL,
        headers={"Authorization": f"Basic {credentials}"},
        data={"grant_type": "client_credentials"},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + data["expires_in"]
    return _token_cache["token"]


_REQUEST_INTERVAL = 2.0  # 0.5req/sec, 30초 윈도우 내 15req — 50% 안전 마진


def spotify_get(path: str, params: Optional[dict] = None) -> dict:
    """Spotify API GET 요청. 429 수신 시 즉시 SpotifyRateLimitError 발생."""
    time.sleep(_REQUEST_INTERVAL)
    token = _get_access_token()
    response = requests.get(
        f"{_SPOTIFY_API_URL}{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=10,
    )
    if response.status_code == 429:
        retry_after = int(response.headers.get("Retry-After", 0))
        logger.error(
            "Spotify 429 — 수집 중단 (Retry-After=%ds): %s", retry_after, path,
        )
        raise SpotifyRateLimitError(
            f"Spotify 429: Retry-After={retry_after}s, path={path}",
            response=response,
        )
    response.raise_for_status()
    return response.json()
