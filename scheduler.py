import argparse
import json
import logging
import logging.handlers
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import List, Optional, Set

from apscheduler.schedulers.background import BackgroundScheduler

from collectors import artist_image, kopis, musicbrainz, release, setlist, wikipedia
from collectors.spotify_client import SpotifyRateLimitError
from db.repository import (
    get_active_concerts,
    get_all_aliases,
    get_all_artist_mbids,
    get_all_artists_with_spotify,
    get_artist_by_mbid,
    get_artists_without_image,
    get_artists_without_ko_alias,
    get_artists_without_releases,
    get_concert_by_kopis_id,
    get_concert_with_artist,
    get_existing_kopis_ids,
    get_existing_release_spotify_ids,
    get_matched_artists_with_spotify,
    get_spotify_album_total,
    get_unmatched_concerts,
    save_aliases,
    save_artists,
    save_concert_artist_candidates,
    save_concert_artists,
    save_concerts,
    save_releases,
    save_setlists,
    update_artist_image,
    update_artist_is_coming,
    update_concert_status,
    update_spotify_album_total,
)
from matchers.artist_matcher import has_match, match_concert

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

_RELEASE_TYPE_ORDER = {"Album": 0, "Single": 1}
_CHECKPOINT_DIR = os.path.join(os.path.dirname(__file__), "checkpoints")
_BAN_PATH = os.path.join(_CHECKPOINT_DIR, "spotify_ban.json")
_STATUS_UPDATE_CHECKPOINT = os.path.join(_CHECKPOINT_DIR, "status_update.json")
_BAN_MARGIN_HOURS = 25  # Spotify 24h 밴 + 1h 마진


def _progress_path(job_name: str) -> str:
    return os.path.join(_CHECKPOINT_DIR, f"{job_name}.json")


def _is_banned() -> bool:
    """spotify_ban.json에 banned_until이 있고 현재 시각이 그 이전이면 True."""
    if not os.path.exists(_BAN_PATH):
        return False
    try:
        with open(_BAN_PATH, encoding="utf-8") as f:
            data = json.load(f)
        banned_until_str = data.get("banned_until")
        if not banned_until_str:
            return False
        return datetime.now() < datetime.fromisoformat(banned_until_str)
    except Exception:
        return False


def _save_ban() -> None:
    """Spotify 429 발생 시 ban 해제 시각을 spotify_ban.json에 저장한다."""
    os.makedirs(_CHECKPOINT_DIR, exist_ok=True)
    data = {
        "banned_until": (datetime.now() + timedelta(hours=_BAN_MARGIN_HOURS)).isoformat(
            timespec="seconds"
        )
    }
    try:
        with open(_BAN_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as e:
        logger.warning("ban 파일 저장 실패: %s", e)


def _load_progress(job_name: str) -> Set[int]:
    """잡별 체크포인트에서 완료된 artist_id 집합을 로드한다. 없거나 오류 시 빈 집합 반환."""
    path = _progress_path(job_name)
    if not os.path.exists(path):
        return set()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return set(data)
        return set()
    except Exception as e:
        logger.warning("진행 체크포인트 로드 실패 (%s) — 초기화: %s", job_name, e)
        return set()


def _save_progress(job_name: str, completed_ids: Set[int]) -> None:
    """잡별 완료된 artist_id 집합을 체크포인트 파일에 저장한다."""
    os.makedirs(_CHECKPOINT_DIR, exist_ok=True)
    try:
        with open(_progress_path(job_name), "w", encoding="utf-8") as f:
            json.dump(list(completed_ids), f)
    except Exception as e:
        logger.warning("진행 체크포인트 저장 실패 (%s): %s", job_name, e)


def _load_last_collect_date() -> Optional[str]:
    """status_update 체크포인트에서 마지막 성공 수집일(YYYYMMDD)을 로드한다. 없으면 None."""
    if not os.path.exists(_STATUS_UPDATE_CHECKPOINT):
        return None
    try:
        with open(_STATUS_UPDATE_CHECKPOINT, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("last_collect_date") or None
    except Exception as e:
        logger.warning("status_update 체크포인트 로드 실패 — 전체 스캔으로 대체: %s", e)
        return None


def _save_last_collect_date(date_str: str) -> None:
    """status_update 체크포인트에 마지막 성공 수집일(YYYYMMDD)을 저장한다."""
    os.makedirs(_CHECKPOINT_DIR, exist_ok=True)
    try:
        with open(_STATUS_UPDATE_CHECKPOINT, "w", encoding="utf-8") as f:
            json.dump({"last_collect_date": date_str}, f)
    except Exception as e:
        logger.warning("status_update 체크포인트 저장 실패: %s", e)


def _clear_progress(job_name: str) -> None:
    """정상 완료 후 잡별 체크포인트 파일을 삭제한다."""
    path = _progress_path(job_name)
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception as e:
            logger.warning("진행 체크포인트 삭제 실패 (%s): %s", job_name, e)


def _attach_file_handler(log_path: str, rotating: bool = False) -> None:
    """루트 로거에 FileHandler를 부착한다. 디렉토리가 없으면 생성한다.

    rotating=True이면 TimedRotatingFileHandler(자정 교체, 30일 보관)를 사용한다.
    """
    os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    if rotating:
        fh = logging.handlers.TimedRotatingFileHandler(
            log_path, when="midnight", backupCount=30, encoding="utf-8"
        )
    else:
        fh = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logging.getLogger().addHandler(fh)
    logger.info("로그 파일: %s", log_path)


def _migrate_legacy_checkpoint() -> None:
    """release_sync.json을 spotify_ban.json + 잡별 파일로 분리 이전한다."""
    legacy = os.path.join(_CHECKPOINT_DIR, "release_sync.json")
    if not os.path.exists(legacy):
        return
    try:
        with open(legacy, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            banned_until = data.get("banned_until")
            if banned_until:
                os.makedirs(_CHECKPOINT_DIR, exist_ok=True)
                with open(_BAN_PATH, "w", encoding="utf-8") as f:
                    json.dump({"banned_until": banned_until}, f)
            completed = data.get("completed_artist_ids", [])
            if completed:
                _save_progress("release_update", set(completed))
        os.remove(legacy)
        logger.info("레거시 체크포인트 마이그레이션 완료: release_sync.json → 분리 저장")
    except Exception as e:
        logger.warning("레거시 체크포인트 마이그레이션 실패: %s", e)


def _sort_releases(releases: List[dict]) -> List[dict]:
    return sorted(releases, key=lambda r: _RELEASE_TYPE_ORDER.get(r.get("type", ""), 9))


def _extract_spotify_id(spotify_url: str) -> str:
    return spotify_url.rstrip("/").split("/")[-1]


def run_initial_collect(
    skip_artists: bool = False,
    force_artists: bool = False,
    skip_kopis: bool = False,
    skip_wikipedia: bool = False,
    skip_releases: bool = False,
    skip_artist_image: bool = False,
    skip_setlist: bool = False,
) -> None:
    """초기 수집 (1회성 CLI): 아티스트 → KOPIS 매칭 → 매칭 아티스트 릴리즈 순으로 수집.

    재개 지원: 이미 DB에 저장된 아티스트는 건너뛴다.
    force_artists=True 시 기존 DB 아티스트를 건너뛰지 않고 전체 재수집한다.
    skip_kopis=True 시 KOPIS 수집·매칭을 건너뛰고 릴리즈 수집으로 진행한다.
    skip_wikipedia=True 시 Wikipedia alias 수집을 건너뛴다.
    skip_releases=True 시 릴리즈 수집을 건너뛴다.
    skip_artist_image=True 시 아티스트 이미지 수집을 건너뛴다.
    skip_setlist=True 시 setlist.fm 수집을 건너뛴다.
    나머지 아티스트 릴리즈는 주간 배치(run_release_update)가 점진적으로 채운다.
    """
    logger.info("=== 초기 수집 시작 ===")

    if skip_artists:
        logger.info("--skip-artists 플래그 감지 — 아티스트 수집 건너뜀")
    else:
        if force_artists:
            saved_mbids: set = set()
            logger.info("--force-artists 플래그 감지 — 기존 아티스트 건너뜀 없이 전체 재수집")
        else:
            saved_mbids = set(get_all_artist_mbids())
            if saved_mbids:
                logger.info("기존 저장 아티스트 %d건 건너뜀 — 재개 모드", len(saved_mbids))
        artists = musicbrainz.collect_artists(skip_mbids=saved_mbids)
        save_artists(artists)

    if skip_wikipedia:
        logger.info("--skip-wikipedia 플래그 감지 — Wikipedia alias 수집 건너뜀")
    else:
        run_wikipedia_collect()

    if skip_kopis:
        logger.info("--skip-kopis 플래그 감지 — KOPIS 수집·매칭 건너뜀")
    else:
        # KOPIS 수집 + 매칭으로 내한 확정 아티스트를 먼저 파악한다.
        logger.info("KOPIS 수집·매칭 실행 — 릴리즈 우선 수집 대상 결정")
        run_status_update(stdate="20200101")

    if skip_releases:
        logger.info("--skip-releases 플래그 감지 — 릴리즈 수집 건너뜀")
    elif _is_banned():
        logger.warning("Spotify 429 밴 유효 — 릴리즈 수집 건너뜀")
    else:
        matched_artists = get_matched_artists_with_spotify()
        logger.info("내한 공연 매칭 아티스트 %d건 릴리즈 수집 시작", len(matched_artists))
        completed_ids = _load_progress("initial_collect")
        for a in matched_artists:
            artist_id = a["artist_id"]
            if artist_id in completed_ids:
                logger.info("체크포인트 — 완료 아티스트 건너뜀: artist_id=%d", artist_id)
                continue
            try:
                spotify_id = _extract_spotify_id(a["spotify_url"])
                cached_total = get_spotify_album_total(artist_id)
                existing_ids = get_existing_release_spotify_ids(artist_id)
                raw, spotify_total = release.collect_releases(
                    spotify_id, skip_spotify_ids=existing_ids, cached_total=cached_total
                )
                if spotify_total > 0 and spotify_total != cached_total:
                    update_spotify_album_total(artist_id, spotify_total)
                if raw:
                    save_releases(artist_id, _sort_releases(raw))
                completed_ids.add(artist_id)
            except SpotifyRateLimitError:
                logger.error("Spotify 429 — 릴리즈 수집 중단 (artist_id=%d)", artist_id)
                _save_ban()
                _save_progress("initial_collect", completed_ids)
                break
            except Exception as e:
                logger.error("릴리즈 수집 실패 — artist_id=%d: %s", artist_id, e)
        else:
            _clear_progress("initial_collect")

    if skip_artist_image:
        logger.info("--skip-artist-image 플래그 감지 — 아티스트 이미지 수집 건너뜀")
    else:
        run_artist_image_update()

    if skip_setlist:
        logger.info("--skip-setlist 플래그 감지 — setlist 수집 건너뜀")
    else:
        run_setlist_collect()

    logger.info("=== 초기 수집 완료 ===")


def run_wikipedia_collect() -> None:
    """Wikipedia 한국어 alias 수집 (초기 1회 + 주 1회, 목요일).

    locale='ko' alias가 이미 존재하는 아티스트는 건너뛴다.
    """
    logger.info("=== Wikipedia 한국어 alias 수집 잡 시작 ===")
    artists = get_artists_without_ko_alias()
    logger.info("한국어 alias 미수집 아티스트: %d건", len(artists))
    if not artists:
        logger.info("=== Wikipedia 한국어 alias 수집 잡 완료 (대상 없음) ===")
        return
    aliases = wikipedia.collect_korean_aliases(artists)
    if aliases:
        save_aliases(aliases)
    logger.info("=== Wikipedia 한국어 alias 수집 잡 완료 ===")



def run_status_update(stdate: Optional[str] = None) -> None:
    """공연 상태 갱신 + 신규 공연 저장·매칭 + is_coming 동기화 (매일).

    stdate 미전달 시 kopis.collect() 기본값(20250101)을 사용한다.
    초기 수집 시에는 stdate="20200101"을 전달해 전체 기간을 탐색한다.
    """
    logger.info("=== 공연 상태 갱신 잡 시작 ===")

    # ① 상태 갱신: DB의 진행 중 공연을 개별 API로 최신 상태 갱신
    active = get_active_concerts()
    if active:
        logger.info("활성 공연 %d건 상태 갱신 시작", len(active))
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {
                pool.submit(kopis.collect_by_id, c["kopis_id"]): c["kopis_id"]
                for c in active
            }
        fetched = []
        for future, kopis_id in futures.items():
            try:
                result = future.result()
                if result is not None:
                    fetched.append(result)
            except Exception as e:
                logger.warning("상태 갱신 API 실패 kopis_id=%s: %s", kopis_id, e)
        if fetched:
            update_concert_status(fetched)

    # ② 신규 발견: 마지막 수집일 이후 등록·수정된 공연만 증분 탐지
    last_date = _load_last_collect_date()
    if last_date:
        logger.info("증분 스캔 — afterdate=%s", last_date)
    else:
        logger.info("초기 전체 스캔 (체크포인트 없음, stdate=%s)", stdate or "20250101")
    concerts = kopis.collect(stdate=stdate, afterdate=last_date)
    existing_ids = get_existing_kopis_ids()
    aliases = get_all_aliases()
    new_concerts = [
        c for c in concerts
        if c["kopis_id"] not in existing_ids and has_match(c, aliases)
    ]
    if new_concerts:
        logger.info("신규 공연 %d건 저장 시작", len(new_concerts))
        save_concerts(new_concerts)
        unmatched = get_unmatched_concerts()
        all_matches: list[dict] = []
        for concert in unmatched:
            matches, _ = match_concert(concert, aliases)
            all_matches.extend(matches)
        if all_matches:
            save_concert_artist_candidates(all_matches)

    update_artist_is_coming()
    _save_last_collect_date(datetime.now().strftime("%Y%m%d"))
    logger.info("=== 공연 상태 갱신 잡 완료 ===")



def run_artist_image_update() -> None:
    """image_url 미수집 아티스트의 프로필 이미지를 수집한다 (주 1회, 목요일)."""
    logger.info("=== 아티스트 이미지 수집 잡 시작 ===")
    if _is_banned():
        logger.warning("Spotify 429 밴 유효 — 이미지 수집 건너뜀")
        return
    artists = get_artists_without_image()
    logger.info("이미지 미수집 아티스트: %d건", len(artists))
    for a in artists:
        try:
            image_url = artist_image.collect_artist_image(
                a["mbid"],
                spotify_url=a.get("spotify_url"),
                name=a.get("name"),
            )
        except Exception as e:
            logger.warning("아티스트 이미지 수집 실패 mbid=%s: %s", a["mbid"], e)
            continue
        if image_url:
            update_artist_image(a["id"], image_url)
    logger.info("=== 아티스트 이미지 수집 잡 완료 ===")


def run_release_update() -> None:
    """릴리즈 갱신 (매일). 내한 공연 매칭 아티스트만 대상."""
    logger.info("=== 릴리즈 갱신 잡 시작 ===")
    if _is_banned():
        logger.warning("Spotify 429 밴 유효 — 릴리즈 갱신 건너뜀")
        return
    completed_ids = _load_progress("release_update")
    for a in get_matched_artists_with_spotify():
        artist_id = a["artist_id"]
        if artist_id in completed_ids:
            logger.info("체크포인트 — 완료 아티스트 건너뜀: artist_id=%d", artist_id)
            continue
        try:
            spotify_id = _extract_spotify_id(a["spotify_url"])
            cached_total = get_spotify_album_total(artist_id)
            existing_ids = get_existing_release_spotify_ids(artist_id)
            raw, spotify_total = release.collect_releases(
                spotify_id, skip_spotify_ids=existing_ids, cached_total=cached_total
            )
            if spotify_total > 0 and spotify_total != cached_total:
                update_spotify_album_total(artist_id, spotify_total)
            if raw:
                save_releases(artist_id, _sort_releases(raw))
            completed_ids.add(artist_id)
        except SpotifyRateLimitError:
            logger.error("Spotify 429 — 릴리즈 갱신 중단 (artist_id=%d)", artist_id)
            _save_ban()
            _save_progress("release_update", completed_ids)
            break
        except Exception as e:
            logger.error("릴리즈 수집 실패 — artist_id=%d: %s", artist_id, e)
    else:
        _clear_progress("release_update")
    logger.info("=== 릴리즈 갱신 잡 완료 ===")


def run_missing_release_update() -> None:
    """릴리즈가 없는 아티스트만 대상으로 릴리즈를 수집한다 (복구 전용)."""
    logger.info("=== 누락 릴리즈 수집 잡 시작 ===")
    if _is_banned():
        logger.warning("Spotify 429 밴 유효 — 누락 릴리즈 수집 건너뜀")
        return
    artists = get_artists_without_releases()
    logger.info("릴리즈 미수집 아티스트: %d건", len(artists))
    completed_ids = _load_progress("missing_release")
    for a in artists:
        artist_id = a["artist_id"]
        if artist_id in completed_ids:
            logger.info("체크포인트 — 완료 아티스트 건너뜀: artist_id=%d", artist_id)
            continue
        try:
            spotify_id = _extract_spotify_id(a["spotify_url"])
            cached_total = get_spotify_album_total(artist_id)
            existing_ids = get_existing_release_spotify_ids(artist_id)
            raw, spotify_total = release.collect_releases(
                spotify_id, skip_spotify_ids=existing_ids, cached_total=cached_total
            )
            if spotify_total > 0 and spotify_total != cached_total:
                update_spotify_album_total(artist_id, spotify_total)
            if raw:
                save_releases(artist_id, _sort_releases(raw))
            completed_ids.add(artist_id)
        except SpotifyRateLimitError:
            logger.error("Spotify 429 — 누락 릴리즈 수집 중단 (artist_id=%d)", artist_id)
            _save_ban()
            _save_progress("missing_release", completed_ids)
            break
        except Exception as e:
            logger.error("릴리즈 수집 실패 — artist_id=%d: %s", artist_id, e)
    else:
        _clear_progress("missing_release")
    logger.info("=== 누락 릴리즈 수집 잡 완료 ===")


def run_recover(skip_releases: bool = False, skip_artist_image: bool = False) -> None:
    """이전 수집 실패(429 등)로 누락된 이미지·릴리즈만 재수집한다."""
    logger.info("=== 복구 수집 시작 ===")
    if skip_artist_image:
        logger.info("--skip-artist-image 플래그 감지 — 이미지 수집 건너뜀")
    else:
        run_artist_image_update()
    if skip_releases:
        logger.info("--skip-releases 플래그 감지 — 릴리즈 수집 건너뜀")
    else:
        run_missing_release_update()
    logger.info("=== 복구 수집 완료 ===")


def register_artist_by_mbid(mbid: str) -> bool:
    """어드민 요청으로 단일 아티스트를 등록한다.

    1) MusicBrainz에서 아티스트 상세 수집 후 DB 저장
    2) Spotify URL이 있으면 이미지·릴리즈 수집
    Last.fm 리스너 수 필터를 적용하지 않는다.
    성공 시 True, 수집 실패 시 False 반환.

    관리자가 명시적으로 호출하는 단건 작업이므로 ban 상태와 무관하게 실행한다.
    """
    logger.info("어드민 아티스트 등록 시작: mbid=%s", mbid)

    artist = musicbrainz.collect_single_artist(mbid)
    if artist is None:
        logger.error("아티스트 수집 실패 — 등록 중단: mbid=%s", mbid)
        return False

    save_artists([artist])

    saved = get_artist_by_mbid(mbid)
    if saved is None:
        logger.error("아티스트 DB 조회 실패 — 이후 수집 건너뜀: mbid=%s", mbid)
        return False

    artist_id = saved["id"]
    spotify_url = saved.get("spotify_url")

    if spotify_url:
        try:
            image_url = artist_image.collect_artist_image(
                mbid, spotify_url=spotify_url, name=saved.get("name")
            )
            if image_url:
                update_artist_image(artist_id, image_url)
        except Exception as e:
            logger.warning("아티스트 이미지 수집 실패 mbid=%s: %s", mbid, e)

        try:
            spotify_id = _extract_spotify_id(spotify_url)
            raw, _ = release.collect_releases(spotify_id)
            releases = _sort_releases(raw)
            save_releases(artist_id, releases)
        except SpotifyRateLimitError:
            logger.error("Spotify 429 — 릴리즈 수집 중단 (artist_id=%s)", artist_id)
        except Exception as e:
            logger.warning("릴리즈 수집 실패 — artist_id=%s: %s", artist_id, e)
    else:
        logger.info("Spotify URL 없음 — 이미지·릴리즈 수집 건너뜀: mbid=%s", mbid)

    logger.info("어드민 아티스트 등록 완료: mbid=%s, artist_id=%s", mbid, artist_id)
    return True


def run_setlist_collect() -> None:
    """setlist.fm 수집 (매일)."""
    logger.info("=== setlist 수집 잡 시작 ===")
    setlists = setlist.collect()
    save_setlists(setlists)
    logger.info("=== setlist 수집 잡 완료 ===")


def collect_and_save_concert(kopis_id: str) -> bool:
    """단건 KOPIS 공연을 수집해 alias 매칭 후 DB에 저장한다. 성공 시 True 반환."""
    concert = kopis.collect_by_id(kopis_id)
    if concert is None:
        logger.warning("KOPIS 공연 데이터 없음: kopis_id=%s", kopis_id)
        return False
    if concert.get("visit") != "Y":
        logger.info("내한 공연 아님 — 저장 건너뜀: kopis_id=%s", kopis_id)
        return False

    aliases = get_all_aliases()
    if not has_match(concert, aliases):
        logger.info("alias 매칭 없음 — 저장 건너뜀: kopis_id=%s", kopis_id)
        return False

    save_concerts([concert], use_prfstate=True)

    concert_row = get_concert_by_kopis_id(kopis_id)
    if concert_row:
        matches, _ = match_concert(concert_row, aliases)
        if matches:
            save_concert_artists(matches)
            update_artist_is_coming()

    logger.info("단건 공연 수집 완료: kopis_id=%s", kopis_id)
    return True



def collect_and_save_releases_for_artist(artist_id: int) -> bool:
    """단건 아티스트의 릴리즈를 수집해 DB에 저장한다. 성공 시 True 반환.

    관리자가 명시적으로 호출하는 단건 작업이므로 ban 상태와 무관하게 실행한다.
    """
    artists = get_matched_artists_with_spotify()
    target = next((a for a in artists if a["artist_id"] == artist_id), None)
    if target is None:
        all_sp = get_all_artists_with_spotify()
        target = next((a for a in all_sp if a["artist_id"] == artist_id), None)
    if target is None:
        logger.warning("Spotify URL 없는 아티스트 — 건너뜀: artist_id=%d", artist_id)
        return False
    try:
        spotify_id = _extract_spotify_id(target["spotify_url"])
        existing_ids = get_existing_release_spotify_ids(artist_id)
        raw, _ = release.collect_releases(spotify_id, skip_spotify_ids=existing_ids)
        releases = _sort_releases(raw)
        save_releases(artist_id, releases)
    except SpotifyRateLimitError:
        logger.error("Spotify 429 — 릴리즈 수집 중단 (artist_id=%d)", artist_id)
        return False
    except Exception as e:
        logger.error("릴리즈 수집 실패 — artist_id=%d: %s", artist_id, e)
        return False
    logger.info("단건 릴리즈 수집 완료: artist_id=%d, %d건", artist_id, len(releases))
    return True


def collect_and_save_setlist(concert_id: int) -> bool:
    """단건 공연의 셋리스트를 수집해 DB에 저장한다. 성공 시 True 반환."""
    concert = get_concert_with_artist(concert_id)
    if concert is None:
        logger.warning("공연 조회 실패: concert_id=%d", concert_id)
        return False
    result = setlist.collect_for_concert(concert)
    if result is None:
        logger.info("셋리스트 없음: concert_id=%d", concert_id)
        return False
    save_setlists([result])
    logger.info("단건 셋리스트 수집 완료: concert_id=%d", concert_id)
    return True


def _build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Seoul")
    scheduler.add_job(run_status_update, "cron", hour=4)
    scheduler.add_job(run_release_update, "cron", hour=2)
    scheduler.add_job(run_wikipedia_collect, "cron", day_of_week="thu", hour=3)
    scheduler.add_job(run_artist_image_update, "cron", day_of_week="thu", hour=5)
    scheduler.add_job(run_setlist_collect, "cron", hour=6)
    return scheduler


def main() -> None:
    _migrate_legacy_checkpoint()
    parser = argparse.ArgumentParser(description="Coming Data Pipeline")
    parser.add_argument(
        "command",
        nargs="?",
        choices=["init", "recover", "collect-release", "collect-setlist", "run-job"],
        help=(
            "init: 초기 아티스트·릴리즈 수집 후 종료 / "
            "recover: 누락 이미지·릴리즈 재수집 / "
            "collect-release: 단건 아티스트 릴리즈 수집 / "
            "collect-setlist: 공연완료 공연 셋리스트 수집 / "
            "run-job: 단일 잡 즉시 실행 (--job으로 잡 선택)"
        ),
    )
    parser.add_argument(
        "--skip-artists",
        action="store_true",
        help="아티스트 수집을 건너뛰고 릴리즈 수집만 수행 (init 전용)",
    )
    parser.add_argument(
        "--force-artists",
        action="store_true",
        help="기존 DB 아티스트를 건너뛰지 않고 변경된 쿼리 기준으로 전체 재수집 (init 전용)",
    )
    parser.add_argument(
        "--skip-kopis",
        action="store_true",
        help="KOPIS 수집·매칭을 건너뛰고 릴리즈 수집으로 바로 진행 (init 전용)",
    )
    parser.add_argument(
        "--skip-wikipedia",
        action="store_true",
        help="Wikipedia alias 수집을 건너뜀 (init 전용)",
    )
    parser.add_argument(
        "--skip-releases",
        action="store_true",
        help="릴리즈 수집을 건너뜀 (init 전용)",
    )
    parser.add_argument(
        "--skip-artist-image",
        action="store_true",
        help="아티스트 이미지 수집을 건너뜀 (init 전용)",
    )
    parser.add_argument(
        "--skip-setlist",
        action="store_true",
        help="setlist.fm 수집을 건너뜀 (init 전용)",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        help="기존 로그 파일에 이어쓰기 (init 전용, 미지정 시 타임스탬프 파일 신규 생성)",
    )
    parser.add_argument(
        "--artist-id",
        type=int,
        help="단건 릴리즈 수집 대상 artist.id (collect-release 전용)",
    )
    parser.add_argument(
        "--job",
        choices=["status-update", "release-update", "wikipedia", "artist-image", "setlist"],
        help="즉시 실행할 잡 이름 (run-job 전용)",
    )
    args = parser.parse_args()

    if args.command == "init":
        if args.log_file:
            _log_path = args.log_file
        else:
            _ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            _log_path = os.path.join(os.path.dirname(__file__), "logs", f"release_init_{_ts}.log")
        _attach_file_handler(_log_path)
        run_initial_collect(
            skip_artists=args.skip_artists,
            force_artists=args.force_artists,
            skip_kopis=args.skip_kopis,
            skip_wikipedia=args.skip_wikipedia,
            skip_releases=args.skip_releases,
            skip_artist_image=args.skip_artist_image,
            skip_setlist=args.skip_setlist,
        )
        return

    if args.command == "recover":
        _ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        _log_path = os.path.join(os.path.dirname(__file__), "logs", f"recover_{_ts}.log")
        _attach_file_handler(_log_path)
        run_recover(
            skip_releases=args.skip_releases,
            skip_artist_image=args.skip_artist_image,
        )
        return

    if args.command == "collect-release":
        if not args.artist_id:
            parser.error("collect-release 커맨드는 --artist-id 가 필요합니다.")
        _ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        _log_path = os.path.join(os.path.dirname(__file__), "logs", f"collect_release_{_ts}.log")
        _attach_file_handler(_log_path)
        collect_and_save_releases_for_artist(args.artist_id)
        return

    if args.command == "collect-setlist":
        _ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        _log_path = os.path.join(os.path.dirname(__file__), "logs", f"setlist_{_ts}.log")
        _attach_file_handler(_log_path)
        run_setlist_collect()
        return

    if args.command == "run-job":
        if not args.job:
            parser.error("run-job 커맨드는 --job 이 필요합니다.")
        _job_map = {
            "status-update": run_status_update,
            "release-update": run_release_update,
            "wikipedia": run_wikipedia_collect,
            "artist-image": run_artist_image_update,
            "setlist": run_setlist_collect,
        }
        _ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        _log_path = os.path.join(
            os.path.dirname(__file__), "logs", f"run_job_{args.job}_{_ts}.log"
        )
        _attach_file_handler(_log_path)
        _job_map[args.job]()
        return

    import uvicorn

    _daemon_log = os.path.join(os.path.dirname(__file__), "logs", "scheduler.log")
    _attach_file_handler(_daemon_log, rotating=True)
    logger.info("데몬 로그 파일: %s", _daemon_log)

    api_host = os.environ.get("API_HOST", "0.0.0.0")
    api_port = int(os.environ.get("API_PORT", "8000"))

    api_thread = threading.Thread(
        target=uvicorn.run,
        args=("api:app",),
        kwargs={"host": api_host, "port": api_port, "log_level": "warning"},
        daemon=True,
    )
    api_thread.start()
    logger.info("API 서버 시작: http://%s:%d", api_host, api_port)

    scheduler = _build_scheduler()
    scheduler.start()
    logger.info("스케줄러 시작 (종료: Ctrl+C)")
    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("스케줄러 종료")


if __name__ == "__main__":
    main()
