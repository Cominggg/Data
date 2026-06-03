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


def spotify_get(path: str, params: Optional[dict] = None) -> dict:
    """Spotify API GET 요청. Bearer 토큰을 자동으로 주입한다."""
    token = _get_access_token()
    response = requests.get(
        f"{_SPOTIFY_API_URL}{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=10,
    )
    response.raise_for_status()
    return response.json()
