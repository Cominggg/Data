import logging
import os
import time
from datetime import datetime
from typing import Optional

import requests
from dotenv import load_dotenv

from db.repository import get_completed_concerts, update_concert_fetch_attempted

load_dotenv()

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.setlist.fm/rest/1.0"
_API_KEY = os.environ.get("SETLISTFM_API_KEY")
if not _API_KEY:
    raise ValueError("SETLISTFM_API_KEY 환경변수가 설정되지 않았습니다.")

_HEADERS = {
    "x-api-key": _API_KEY,
    "Accept": "application/json",
}

_MAX_PAGES = 10


def _get(path: str, params: dict) -> dict:
    for attempt in range(1, 4):
        response = requests.get(f"{_BASE_URL}{path}", headers=_HEADERS, params=params, timeout=30)
        try:
            response.raise_for_status()
            time.sleep(1.0)
            return response.json()
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                raise
            if attempt == 3:
                raise
            logger.warning("setlist.fm HTTP 오류 재시도 %d/3: path=%s, %s", attempt, path, e)
            time.sleep(5 * attempt)
        except requests.RequestException as e:
            if attempt == 3:
                raise
            logger.warning("setlist.fm 네트워크 오류 재시도 %d/3: path=%s, %s", attempt, path, e)
            time.sleep(5 * attempt)


def _parse_tracks(sets_data: dict) -> list[dict]:
    tracks = []
    position = 1
    for s in sets_data.get("set", []):
        for song in s.get("song", []):
            tracks.append({
                "position": position,
                "song_name": song.get("name", ""),
                "info": song.get("info"),
            })
            position += 1
    return tracks


def _event_date_in_range(
    event_date_str: str, prfpdfrom: Optional[str], prfpdto: Optional[str]
) -> bool:
    """eventDate (dd-MM-yyyy) 가 공연 기간 (yyyy-MM-dd) 안에 포함되는지 확인."""
    try:
        event_dt = datetime.strptime(event_date_str, "%d-%m-%Y")
        if prfpdfrom and event_dt < datetime.strptime(prfpdfrom, "%Y-%m-%d"):
            return False
        if prfpdto and event_dt > datetime.strptime(prfpdto, "%Y-%m-%d"):
            return False
        return True
    except (ValueError, TypeError) as e:
        logger.warning(
            "날짜 파싱 실패: event_date=%s, from=%s, to=%s, %s",
            event_date_str, prfpdfrom, prfpdto, e,
        )
        return False


def collect_for_concert(concert: dict) -> Optional[dict]:
    """단건 공연의 셋리스트를 setlist.fm에서 수집한다.

    concert: {"concert_id": int, "artist_mbid": str, "start_date": str, "end_date": str}
    Returns: setlist dict, 또는 없으면 None
    """
    concert_id = concert["concert_id"]
    artist_mbid = concert["artist_mbid"]

    page = 1
    while True:
        try:
            data = _get(
                "/search/setlists",
                {"artistMbid": artist_mbid, "countryCode": "KR", "p": page},
            )
        except requests.RequestException as e:
            is_404 = (
                isinstance(e, requests.HTTPError)
                and e.response is not None
                and e.response.status_code == 404
            )
            if not is_404:
                logger.warning("setlist.fm API 오류: concert_id=%d, %s", concert_id, e)
            return None

        for item in data.get("setlist", []):
            event_date = item.get("eventDate", "")
            if not _event_date_in_range(event_date, concert["start_date"], concert["end_date"]):
                continue
            tracks = _parse_tracks(item.get("sets", {}))
            logger.info("셋리스트 수집: concert_id=%d, setlist_fm_id=%s, 트랙 %d개",
                        concert_id, item.get("id"), len(tracks))
            return {"concert_id": concert_id, "setlist_fm_id": item.get("id"), "tracks": tracks}

        total = int(data.get("total", 0))
        items_per_page = int(data.get("itemsPerPage", 20))
        if page * items_per_page >= total or page >= _MAX_PAGES:
            return None
        page += 1


def collect() -> list[dict]:
    """공연완료 상태 공연의 셋리스트를 setlist.fm에서 수집한다."""
    logger.info("setlist.fm 수집 시작")
    completed = get_completed_concerts()
    results: list[dict] = []
    seen_concert_ids: set[int] = set()

    for concert in completed:
        concert_id = concert["concert_id"]
        artist_mbid = concert["artist_mbid"]

        if concert_id in seen_concert_ids:
            continue

        logger.debug("셋리스트 조회: concert_id=%d, artist_mbid=%s", concert_id, artist_mbid)

        page = 1
        while True:
            try:
                data = _get(
                "/search/setlists",
                {"artistMbid": artist_mbid, "countryCode": "KR", "p": page},
            )
            except requests.RequestException as e:
                is_404 = (
                    isinstance(e, requests.HTTPError)
                    and e.response is not None
                    and e.response.status_code == 404
                )
                if is_404:
                    logger.debug("셋리스트 없음 — 건너뜀: concert_id=%d, page=%d", concert_id, page)
                else:
                    logger.warning(
                        "setlist.fm API 오류 (3회 실패): concert_id=%d, page=%d, %s",
                        concert_id, page, e,
                    )
                update_concert_fetch_attempted(concert_id)
                break

            setlist_items = data.get("setlist", [])
            if not setlist_items:
                update_concert_fetch_attempted(concert_id)
                break

            matched = False
            for item in setlist_items:
                event_date = item.get("eventDate", "")
                if not _event_date_in_range(event_date, concert["start_date"], concert["end_date"]):
                    continue

                tracks = _parse_tracks(item.get("sets", {}))
                results.append({
                    "concert_id": concert_id,
                    "setlist_fm_id": item.get("id"),
                    "tracks": tracks,
                })
                seen_concert_ids.add(concert_id)
                logger.info(
                    "셋리스트 수집: concert_id=%d, setlist_fm_id=%s, 트랙 %d개",
                    concert_id, item.get("id"), len(tracks),
                )
                update_concert_fetch_attempted(concert_id)
                matched = True
                break

            if matched:
                break

            total = int(data.get("total", 0))
            items_per_page = int(data.get("itemsPerPage", 20))
            if page * items_per_page >= total or page >= _MAX_PAGES:
                update_concert_fetch_attempted(concert_id)
                break
            page += 1

    logger.info("setlist.fm 수집 완료: 총 %d건", len(results))
    return results
