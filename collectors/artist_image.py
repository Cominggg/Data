import base64
import logging
import os
import time
from typing import Optional, Tuple

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_MB_BASE_URL = "https://musicbrainz.org/ws/2"
_SPOTIFY_AUTH_URL = "https://accounts.spotify.com/api/token"
_SPOTIFY_API_URL = "https://api.spotify.com/v1"
_MB_RATE_LIMIT_SLEEP = 1.1

_token_cache: dict = {"token": None, "expires_at": 0.0}


def _get_access_token(client_id: str, client_secret: str) -> str:
    """Spotify Client Credentials Flow로 access_token을 발급한다 (모듈 레벨 1h 캐시)."""
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


def _get_mb_artist_info(mbid: str) -> Tuple[Optional[str], Optional[str]]:
    """MusicBrainz URL relations에서 아티스트 이름과 Spotify ID를 조회한다.

    Returns:
        (artist_name, spotify_id) 튜플. 각 항목은 없으면 None.
    """
    time.sleep(_MB_RATE_LIMIT_SLEEP)
    user_agent = os.environ.get("MUSICBRAINZ_USER_AGENT", "coming/1.0")
    response = requests.get(
        f"{_MB_BASE_URL}/artist/{mbid}",
        params={"fmt": "json", "inc": "url-rels"},
        headers={"User-Agent": user_agent},
        timeout=30,
    )
    if response.status_code == 404:
        return None, None
    response.raise_for_status()
    data = response.json()

    artist_name: Optional[str] = data.get("name")
    spotify_id: Optional[str] = None
    for rel in data.get("relations", []):
        url = rel.get("url", {}).get("resource", "")
        if "open.spotify.com/artist/" in url:
            spotify_id = url.rstrip("/").split("/")[-1]
            break

    return artist_name, spotify_id


def _search_spotify_artist(name: str, access_token: str) -> Optional[str]:
    """Spotify 이름 검색으로 아티스트 ID를 반환한다 (fallback)."""
    response = requests.get(
        f"{_SPOTIFY_API_URL}/search",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"q": name, "type": "artist", "limit": 1},
        timeout=10,
    )
    response.raise_for_status()
    items = response.json().get("artists", {}).get("items", [])
    if not items:
        return None
    return items[0]["id"]


def _get_artist_image_url(spotify_id: str, access_token: str) -> Optional[str]:
    """Spotify 아티스트 ID로 가장 큰 이미지 URL을 반환한다."""
    response = requests.get(
        f"{_SPOTIFY_API_URL}/artists/{spotify_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    images = response.json().get("images", [])
    if not images:
        return None
    return images[0]["url"]


def collect_artist_image(
    mbid: str,
    spotify_url: Optional[str] = None,
    name: Optional[str] = None,
) -> Optional[str]:
    """Spotify Web API에서 아티스트 프로필 이미지 URL을 수집한다. 없거나 오류 시 None 반환.

    spotify_url: DB artist_url에 저장된 Spotify URL (있으면 MB API 호출 생략)
    name: 아티스트 이름 (spotify_url 없을 때 이름 검색 fallback에 사용, MB API 호출 생략)
    둘 다 없으면 MusicBrainz API를 직접 조회한다 (기존 동작).
    """
    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise ValueError("SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET 환경변수가 설정되지 않았습니다.")

    access_token = _get_access_token(client_id, client_secret)

    spotify_id: Optional[str] = None

    if spotify_url:
        spotify_id = spotify_url.rstrip("/").split("/")[-1]
    elif name:
        spotify_id = _search_spotify_artist(name, access_token)
    else:
        mb_name, spotify_id = _get_mb_artist_info(mbid)
        if not spotify_id:
            if not mb_name:
                logger.info("MusicBrainz 아티스트 정보 없음: mbid=%s", mbid)
                return None
            logger.info("MB URL relations에 Spotify 없음 — 이름 검색 fallback: mbid=%s name=%s",
                        mbid, mb_name)
            spotify_id = _search_spotify_artist(mb_name, access_token)

    if not spotify_id:
        logger.info("Spotify ID 조회 실패: mbid=%s", mbid)
        return None

    return _get_artist_image_url(spotify_id, access_token)
