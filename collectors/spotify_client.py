import base64
import logging
import os
import time
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

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


_MAX_RETRIES = 5
_REQUEST_INTERVAL = 0.5  # 2req/sec, 30초 윈도우 내 60req — 관측 상한(180req/min)의 33%


def spotify_get(path: str, params: Optional[dict] = None) -> dict:
    """Spotify API GET 요청.

    - 요청 간 0.3초 고정 딜레이로 레이트 리밋 예방
    - 429 수신 시 Retry-After 헤더 기준 대기 후 최대 5회 재시도
    """
    time.sleep(_REQUEST_INTERVAL)
    token = _get_access_token()
    response = None
    for attempt in range(_MAX_RETRIES):
        response = requests.get(
            f"{_SPOTIFY_API_URL}{path}",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=10,
        )
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 30))
            logger.warning(
                "Spotify 429 — %d초 대기 후 재시도 (%d/%d): %s",
                retry_after, attempt + 1, _MAX_RETRIES, path,
            )
            time.sleep(retry_after)
            continue
        response.raise_for_status()
        return response.json()
    response.raise_for_status()
    return {}
