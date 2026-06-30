import logging
import os
import time
from typing import Optional, Tuple

import requests
from dotenv import load_dotenv

from collectors.spotify_client import spotify_get

load_dotenv()

logger = logging.getLogger(__name__)

_MB_BASE_URL = "https://musicbrainz.org/ws/2"
_MB_RATE_LIMIT_SLEEP = 1.1


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


def _search_spotify_artist(name: str) -> Optional[str]:
    """Spotify 이름 검색으로 아티스트 ID를 반환한다 (fallback)."""
    data = spotify_get("/search", {"q": name, "type": "artist", "limit": 1})
    items = data.get("artists", {}).get("items", [])
    if not items:
        return None
    return items[0]["id"]


def _get_artist_image_url(spotify_id: str) -> Optional[str]:
    """Spotify 아티스트 ID로 가장 큰 이미지 URL을 반환한다."""
    try:
        data = spotify_get(f"/artists/{spotify_id}")
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return None
        raise
    images = data.get("images", [])
    if not images:
        return None
    return images[0]["url"]


def spotify_artist_url(spotify_id: str) -> str:
    """Spotify 아티스트 ID로 아티스트 페이지 URL을 구성한다."""
    return f"https://open.spotify.com/artist/{spotify_id}"


def collect_artist_image(
    mbid: str,
    spotify_url: Optional[str] = None,
    name: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Spotify Web API에서 아티스트 프로필 이미지 URL을 수집한다.

    spotify_url: DB artist_url에 저장된 Spotify URL (있으면 MB API 호출 생략)
    name: 아티스트 이름 (spotify_url 없을 때 이름 검색 fallback에 사용, MB API 호출 생략)
    둘 다 없으면 MusicBrainz API를 직접 조회한다 (기존 동작).

    Returns:
        (image_url, spotify_id) 튜플. image_url은 이미지가 없거나 조회 오류 시 None.
        spotify_id는 resolve에 성공한 경우 이미지 유무와 무관하게 반환되며,
        호출부가 fallback으로 새로 찾은 Spotify 연결을 DB에 백필하는 데 사용한다.
        spotify_id조차 못 찾으면 (None, None).
    """
    spotify_id: Optional[str] = None

    if spotify_url:
        spotify_id = spotify_url.rstrip("/").split("/")[-1]
    elif name:
        spotify_id = _search_spotify_artist(name)
    else:
        mb_name, spotify_id = _get_mb_artist_info(mbid)
        if not spotify_id:
            if not mb_name:
                logger.info("MusicBrainz 아티스트 정보 없음: mbid=%s", mbid)
                return None, None
            logger.info("MB URL relations에 Spotify 없음 — 이름 검색 fallback: mbid=%s name=%s",
                        mbid, mb_name)
            spotify_id = _search_spotify_artist(mb_name)

    if not spotify_id:
        logger.info("Spotify ID 조회 실패: mbid=%s", mbid)
        return None, None

    return _get_artist_image_url(spotify_id), spotify_id
