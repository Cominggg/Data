import logging
import re
from typing import List, Optional

import requests

from collectors.spotify_client import SpotifyRateLimitError, spotify_get

logger = logging.getLogger(__name__)

_ALBUM_TYPE_MAP = {"album": "Album", "single": "Single"}
_PAGE_LIMIT = 10        # 레이트리밋 예방을 위해 페이지당 10개로 제한
_ALBUM_BATCH_SIZE = 20  # /albums?ids=... 배치 최대 크기


def _parse_release_date(raw: Optional[str]) -> Optional[str]:
    """YYYY-MM-DD 형식만 유효로 인정. 부분 날짜(YYYY·YYYY-MM)는 None 반환."""
    if raw and re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return raw
    return None


def _parse_tracks(items: list) -> List[dict]:
    tracks = []
    for item in items:
        spotify_id = item.get("id")
        if not spotify_id:
            continue
        tracks.append(
            {
                "spotify_id": spotify_id,
                "title": item.get("name"),
                "position": item.get("track_number"),
                "disc_number": item.get("disc_number"),
                "length_ms": item.get("duration_ms"),
                "explicit": item.get("explicit", False),
            }
        )
    return tracks


def _fetch_album_ids(spotify_artist_id: str) -> List[str]:
    """아티스트의 앨범/싱글 Spotify ID 목록을 페이지네이션으로 수집."""
    album_ids: List[str] = []
    offset = 0

    while True:
        try:
            data = spotify_get(
                f"/artists/{spotify_artist_id}/albums",
                {
                    "include_groups": "album,single",
                    "limit": _PAGE_LIMIT,
                    "market": "JP",
                    "offset": offset,
                },
            )
        except SpotifyRateLimitError:
            raise
        except requests.RequestException as e:
            logger.warning("앨범 목록 조회 실패: artist_id=%s, %s", spotify_artist_id, e)
            break

        items = data.get("items") or []
        for item in items:
            album_id = item.get("id")
            if album_id:
                album_ids.append(album_id)

        total = data.get("total", 0)
        offset += len(items)
        if not items or offset >= total:
            break

    return album_ids


def _fetch_albums_batch(album_ids: List[str]) -> List[dict]:
    """20개 단위 배치로 앨범 상세 정보(트랙·레이블 포함)를 조회."""
    results: List[dict] = []
    for i in range(0, len(album_ids), _ALBUM_BATCH_SIZE):
        chunk = album_ids[i : i + _ALBUM_BATCH_SIZE]
        for album_id in chunk:
            try:
                data = spotify_get(f"/albums/{album_id}", {"market": "JP"})
                results.append(data)
            except SpotifyRateLimitError:
                raise
            except requests.RequestException as e:
                logger.warning("앨범 조회 실패 (id=%s): %s", album_id, e)
    return results


def collect_releases(
    spotify_artist_id: str,
    skip_spotify_ids: Optional[set] = None,
) -> List[dict]:
    """아티스트의 릴리즈(앨범·싱글) 수집. compilation은 제외.

    skip_spotify_ids: 이미 수집된 spotify_id 집합. 해당 앨범은 상세 API 호출을 건너뜀.
    """
    logger.info("릴리즈 수집 시작: spotify_artist_id=%s", spotify_artist_id)

    album_ids = _fetch_album_ids(spotify_artist_id)
    if not album_ids:
        logger.info("수집된 앨범 없음: spotify_artist_id=%s", spotify_artist_id)
        return []

    if skip_spotify_ids:
        before = len(album_ids)
        album_ids = [aid for aid in album_ids if aid not in skip_spotify_ids]
        skipped = before - len(album_ids)
        if skipped:
            logger.info(
                "기수집 릴리즈 %d건 건너뜀: spotify_artist_id=%s", skipped, spotify_artist_id
            )
    if not album_ids:
        logger.info("신규 릴리즈 없음: spotify_artist_id=%s", spotify_artist_id)
        return []

    albums = _fetch_albums_batch(album_ids)
    results: List[dict] = []
    for album in albums:
        if album is None:
            continue
        release_type = _ALBUM_TYPE_MAP.get(album.get("album_type", ""))
        if not release_type:
            continue

        tracks_data = (album.get("tracks") or {}).get("items") or []
        if (album.get("tracks") or {}).get("next"):
            logger.warning(
                "트랙 50개 초과 — 일부 누락 가능: spotify_id=%s", album.get("id")
            )

        images = album.get("images") or []
        results.append(
            {
                "spotify_id": album.get("id"),
                "title": album.get("name"),
                "type": release_type,
                "first_release_date": _parse_release_date(album.get("release_date")),
                "cover_url": images[0].get("url") if images else None,
                "label": album.get("label"),
                "total_tracks": album.get("total_tracks"),
                "tracks": _parse_tracks(tracks_data),
            }
        )

    logger.info(
        "릴리즈 수집 완료: spotify_artist_id=%s, 총 %d건", spotify_artist_id, len(results)
    )
    return results
