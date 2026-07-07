import logging
import os

import requests

logger = logging.getLogger(__name__)

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")


def notify_new_concert(title: str, artist_names: list) -> None:
    """신규 수집 공연 1건에 대해 디스코드 웹훅으로 알림을 보낸다.

    DISCORD_WEBHOOK_URL 미설정 시 경고 로그만 남기고 종료한다 (KOPIS_API_KEY 등과 달리
    선택 값이므로 ValueError를 던지지 않는다). 전송 실패도 예외를 절대 전파하지 않는다 —
    알림 실패가 수집 파이프라인을 중단시키면 안 되기 때문이다.
    """
    if not DISCORD_WEBHOOK_URL:
        logger.warning("DISCORD_WEBHOOK_URL 미설정 — 알림 생략: %s", title)
        return
    content = f"{title} - {', '.join(artist_names)}"
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=10)
    except Exception as e:
        logger.warning("디스코드 알림 전송 실패: %s", e)
