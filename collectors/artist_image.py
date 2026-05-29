import logging
import os
import time
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_BASE_URL = "https://webservice.fanart.tv/v3/music"
_RATE_LIMIT_SLEEP = 1.1


def collect_artist_image(mbid: str) -> Optional[str]:
    """Fanart.tv에서 아티스트 프로필 이미지 URL을 수집한다. 없거나 오류 시 None 반환."""
    api_key = os.environ.get("FANART_TV_API_KEY")
    if not api_key:
        raise ValueError("FANART_TV_API_KEY 환경변수가 설정되지 않았습니다.")

    time.sleep(_RATE_LIMIT_SLEEP)
    try:
        response = requests.get(
            f"{_BASE_URL}/{mbid}",
            params={"api_key": api_key},
            timeout=30,
        )
        if response.status_code == 404:
            logger.info("Fanart.tv 이미지 없음: mbid=%s", mbid)
            return None
        response.raise_for_status()
        data = response.json()
        thumbs = data.get("artistthumb", [])
        if not thumbs:
            logger.info("artistthumb 없음: mbid=%s", mbid)
            return None
        return thumbs[0].get("url")
    except requests.RequestException as e:
        logger.warning("아티스트 이미지 수집 실패 mbid=%s: %s", mbid, e)
        raise
