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
    upsert_artist_url,
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
_IMAGE_FAILED_PATH = os.path.join(_CHECKPOINT_DIR, "image_failed.json")
_BAN_MARGIN_HOURS = 25  # Spotify 24h 밴 + 1h 마진
_IMAGE_RETRY_DAYS = 30  # 이미지 미해결 아티스트 재시도 주기

_scheduler: Optional[BackgroundScheduler] = None  # main()에서 데몬 실행 시에만 할당됨


def _progress_path(job_name: str) -> str:
    return os.path.join(_CHECKPOINT_DIR, f"{job_name}.json")


def _reschedule_on_ban_lift(job_func, banned_until: datetime) -> None:
    """밴 해제 시각에 job_func을 1회성으로 재실행하도록 스케줄러에 등록한다.

    CLI 단발 실행 등 데몬으로 뜨지 않은 경우(_scheduler가 None)는 아무 것도 하지 않는다.
    동일 잡에 대해 재밴이 걸려도 job id를 고정해 replace_existing으로 중복 등록을 막는다.
    """
    if _scheduler is None:
        return
    job_id = f"resume_{job_func.__name__}"
    _scheduler.add_job(job_func, "date", run_date=banned_until, id=job_id, replace_existing=True)
    logger.info("밴 해제 시각(%s)에 %s 재실행 예약", banned_until.isoformat(), job_func.__name__)


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


def _save_ban(retry_after_seconds: int = 0) -> datetime:
    """Spotify 429 발생 시 ban 해제 시각을 spotify_ban.json에 저장하고 반환한다.

    retry_after_seconds가 양수면 실측 Retry-After 값(+5초 안전 마진) 기준으로,
    아니면 기존 고정 _BAN_MARGIN_HOURS 기준으로 밴 해제 시각을 계산한다.
    """
    os.makedirs(_CHECKPOINT_DIR, exist_ok=True)
    if retry_after_seconds > 0:
        banned_until = datetime.now() + timedelta(seconds=retry_after_seconds + 5)
    else:
        banned_until = datetime.now() + timedelta(hours=_BAN_MARGIN_HOURS)
    data = {"banned_until": banned_until.isoformat(timespec="seconds")}
    try:
        with open(_BAN_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as e:
        logger.warning("ban 파일 저장 실패: %s", e)
    return banned_until


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


def _load_failed_image_artists() -> dict:
    """image_failed 체크포인트에서 {artist_id: 마지막 실패일(YYYYMMDD)} 맵을 로드한다."""
    if not os.path.exists(_IMAGE_FAILED_PATH):
        return {}
    try:
        with open(_IMAGE_FAILED_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {int(k): v for k, v in data.items()}
        return {}
    except Exception as e:
        logger.warning("image_failed 체크포인트 로드 실패 — 초기화: %s", e)
        return {}


def _save_failed_image_artists(failed: dict) -> None:
    """{artist_id: 마지막 실패일(YYYYMMDD)} 맵을 image_failed 체크포인트에 저장한다."""
    os.makedirs(_CHECKPOINT_DIR, exist_ok=True)
    try:
        with open(_IMAGE_FAILED_PATH, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in failed.items()}, f)
    except Exception as e:
        logger.warning("image_failed 체크포인트 저장 실패: %s", e)


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
        # use_prfstate=True — 초기 수집은 검수 큐(PENDING) 없이 실제 KOPIS 상태로 저장한다.
        logger.info("KOPIS 수집·매칭 실행 — 릴리즈 우선 수집 대상 결정")
        run_new_concert_collect(stdate="20230101", use_prfstate=True)

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



def run_concert_status_update() -> None:
    """활성 공연 상태 갱신 (매일). DB의 진행 중 공연을 개별 API로 최신 상태로 갱신한다."""
    logger.info("=== 공연 상태 갱신 잡 시작 ===")

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

    update_artist_is_coming()
    logger.info("=== 공연 상태 갱신 잡 완료 ===")


def run_new_concert_collect(stdate: Optional[str] = None, use_prfstate: bool = False) -> None:
    """신규 공연 탐지·저장·매칭 + is_coming 동기화 (매일).

    마지막 수집일 이후 등록·수정된 공연만 증분 탐지한다.
    stdate 미전달 시 kopis.collect() 기본값(20250101)을 사용한다.
    초기 수집 시에는 stdate="20230101"을 전달해 전체 기간을 탐색한다.

    use_prfstate=False(기본, 스케줄러 잡)이면 status='PENDING'으로 저장해
    어드민 검수 큐로 보낸다. use_prfstate=True(초기 수집 전용)이면 KOPIS
    prfstate를 그대로 반영해 검수 없이 실제 상태로 저장한다.
    """
    logger.info("=== 신규 공연 탐지 잡 시작 ===")

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
        save_concerts(new_concerts, use_prfstate=use_prfstate)
        unmatched = get_unmatched_concerts()
        all_matches: list[dict] = []
        for concert in unmatched:
            matches, _ = match_concert(concert, aliases)
            all_matches.extend(matches)
        if all_matches:
            save_concert_artist_candidates(all_matches)

    update_artist_is_coming()
    _save_last_collect_date(datetime.now().strftime("%Y%m%d"))
    logger.info("=== 신규 공연 탐지 잡 완료 ===")



def run_artist_image_update() -> None:
    """image_url 미수집 아티스트의 프로필 이미지를 수집한다 (주 1회, 목요일).

    한 번 실패(Spotify 미매칭·이미지 없음)한 아티스트는 image_failed 체크포인트에
    마지막 실패일을 기록해두고, _IMAGE_RETRY_DAYS가 지나기 전까지는 재시도 대상에서
    제외한다 — 매주 동일한 잔여 아티스트로 Spotify API를 반복 호출하지 않기 위함.
    """
    logger.info("=== 아티스트 이미지 수집 잡 시작 ===")
    if _is_banned():
        logger.warning("Spotify 429 밴 유효 — 이미지 수집 건너뜀")
        return
    artists = get_artists_without_image()
    failed = _load_failed_image_artists()
    cutoff = (datetime.now() - timedelta(days=_IMAGE_RETRY_DAYS)).strftime("%Y%m%d")
    targets = [a for a in artists if failed.get(a["id"], "") < cutoff]
    skipped = len(artists) - len(targets)
    if skipped:
        logger.info("최근 %d일 내 실패 기록 — 재시도 보류: %d건", _IMAGE_RETRY_DAYS, skipped)
    logger.info("이미지 수집 시도 대상: %d건", len(targets))

    today = datetime.now().strftime("%Y%m%d")
    for a in targets:
        try:
            image_url, spotify_id = artist_image.collect_artist_image(
                a["mbid"],
                spotify_url=a.get("spotify_url"),
                name=a.get("name"),
            )
        except SpotifyRateLimitError as e:
            logger.error("Spotify 429 — 이미지 수집 중단 (artist_id=%d)", a["id"])
            banned_until = _save_ban(getattr(e, "retry_after", 0))
            _reschedule_on_ban_lift(run_artist_image_update, banned_until)
            break
        except Exception as e:
            logger.warning("아티스트 이미지 수집 실패 mbid=%s: %s", a["mbid"], e)
            continue
        if image_url:
            update_artist_image(a["id"], image_url)
            failed.pop(a["id"], None)
        else:
            failed[a["id"]] = today
        if not a.get("spotify_url") and spotify_id:
            upsert_artist_url(a["id"], "Spotify", artist_image.spotify_artist_url(spotify_id))
    _save_failed_image_artists(failed)
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
        except SpotifyRateLimitError as e:
            logger.error("Spotify 429 — 릴리즈 갱신 중단 (artist_id=%d)", artist_id)
            banned_until = _save_ban(getattr(e, "retry_after", 0))
            _save_progress("release_update", completed_ids)
            _reschedule_on_ban_lift(run_release_update, banned_until)
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


def register_artist_by_mbid(mbid: str) -> dict:
    """어드민 요청으로 단일 아티스트를 등록한다.

    1) MusicBrainz에서 아티스트 상세 수집 후 DB 저장
    2) Spotify URL이 있으면 이미지 수집 (릴리즈 수집은 별도 엔드포인트에서 수행)
    Last.fm 리스너 수 필터를 적용하지 않는다.

    MusicBrainz에 아티스트가 없으면 {"status": "not_found"}, 성공 시
    {"status": "ok", "artist_id", "mbid", "name", "image_url", "aliases"}를 반환한다.
    저장 직후 재조회에 실패하면 (있어선 안 되는 내부 불일치) RuntimeError를 발생시킨다.

    관리자가 명시적으로 호출하는 단건 작업이므로 ban 상태와 무관하게 실행한다.
    """
    logger.info("어드민 아티스트 등록 시작: mbid=%s", mbid)

    artist = musicbrainz.collect_single_artist(mbid)
    if artist is None:
        logger.error("아티스트 수집 실패 — 등록 중단: mbid=%s", mbid)
        return {"status": "not_found"}

    save_artists([artist])

    saved = get_artist_by_mbid(mbid)
    if saved is None:
        raise RuntimeError(f"아티스트 저장 후 조회 실패: mbid={mbid}")

    artist_id = saved["id"]
    spotify_url = saved.get("spotify_url")
    image_url = None

    if spotify_url:
        try:
            image_url, _ = artist_image.collect_artist_image(
                mbid, spotify_url=spotify_url, name=saved.get("name")
            )
            if image_url:
                update_artist_image(artist_id, image_url)
        except Exception as e:
            logger.warning("아티스트 이미지 수집 실패 mbid=%s: %s", mbid, e)
    else:
        logger.info("Spotify URL 없음 — 이미지 수집 건너뜀: mbid=%s", mbid)

    logger.info("어드민 아티스트 등록 완료: mbid=%s, artist_id=%s", mbid, artist_id)
    return {
        "status": "ok",
        "artist_id": artist_id,
        "mbid": mbid,
        "name": saved.get("name"),
        "image_url": image_url,
        "aliases": artist.get("aliases", []),
    }


def run_setlist_collect() -> None:
    """setlist.fm 수집 (매일)."""
    logger.info("=== setlist 수집 잡 시작 ===")
    setlists = setlist.collect()
    save_setlists(setlists)
    logger.info("=== setlist 수집 잡 완료 ===")


def collect_and_save_concert(kopis_id: str) -> dict:
    """단건 KOPIS 공연을 수집해 alias 매칭 후 DB에 저장한다.

    KOPIS에 데이터가 없으면 {"status": "not_found"}, 내한 공연이 아니거나
    alias 매칭이 없으면 {"status": "skipped", "reason": ...}, 성공 시
    {"status": "ok", "concert_id", "title", "matched_artists"}를 반환한다.
    저장 직후 재조회에 실패하면 (있어선 안 되는 내부 불일치) RuntimeError를 발생시킨다.
    """
    concert = kopis.collect_by_id(kopis_id)
    if concert is None:
        logger.warning("KOPIS 공연 데이터 없음: kopis_id=%s", kopis_id)
        return {"status": "not_found"}
    if concert.get("visit") != "Y":
        logger.info("내한 공연 아님 — 저장 건너뜀: kopis_id=%s", kopis_id)
        return {"status": "skipped", "reason": "not_touring"}

    aliases = get_all_aliases()
    if not has_match(concert, aliases):
        logger.info("alias 매칭 없음 — 저장 건너뜀: kopis_id=%s", kopis_id)
        return {"status": "skipped", "reason": "no_alias_match"}

    save_concerts([concert], use_prfstate=True)

    concert_row = get_concert_by_kopis_id(kopis_id)
    if concert_row is None:
        raise RuntimeError(f"공연 저장 후 조회 실패: kopis_id={kopis_id}")

    matched_artists = []
    matches, _ = match_concert(concert_row, aliases)
    if matches:
        save_concert_artists(matches)
        update_artist_is_coming()
        name_by_artist_id = {a["artist_id"]: a["name"] for a in aliases}
        matched_artists = [
            {"artist_id": m["artist_id"], "name": name_by_artist_id.get(m["artist_id"])}
            for m in matches
        ]

    logger.info("단건 공연 수집 완료: kopis_id=%s", kopis_id)
    return {
        "status": "ok",
        "concert_id": concert_row["concert_id"],
        "title": concert_row["title"],
        "matched_artists": matched_artists,
    }



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


def collect_and_save_setlist(concert_id: int) -> dict:
    """단건 공연의 셋리스트를 수집해 DB에 저장한다.

    공연이 없으면 {"status": "not_found"}, 셋리스트가 없으면
    {"status": "skipped", "reason": "no_setlist_found"}, 성공 시
    {"status": "ok", "concert_id", "setlist_fm_id", "attribution_url", "tracks"}를 반환한다.
    """
    concert = get_concert_with_artist(concert_id)
    if concert is None:
        logger.warning("공연 조회 실패: concert_id=%d", concert_id)
        return {"status": "not_found"}
    result = setlist.collect_for_concert(concert)
    if result is None:
        logger.info("셋리스트 없음: concert_id=%d", concert_id)
        return {"status": "skipped", "reason": "no_setlist_found"}
    save_setlists([result])
    logger.info("단건 셋리스트 수집 완료: concert_id=%d", concert_id)
    return {
        "status": "ok",
        "concert_id": result["concert_id"],
        "setlist_fm_id": result["setlist_fm_id"],
        "attribution_url": result.get("attribution_url"),
        "tracks": result.get("tracks", []),
    }


def _build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Seoul")
    scheduler.add_job(run_concert_status_update, "cron", hour=4, minute=0)
    scheduler.add_job(run_new_concert_collect, "cron", hour=4, minute=30)
    scheduler.add_job(run_release_update, "cron", hour=5)
    scheduler.add_job(run_wikipedia_collect, "cron", day_of_week="thu", hour=3)
    scheduler.add_job(run_artist_image_update, "cron", day_of_week="thu", hour=2)
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
        choices=[
            "concert-status-update",
            "new-concert-collect",
            "release-update",
            "wikipedia",
            "artist-image",
            "setlist",
        ],
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
            "concert-status-update": run_concert_status_update,
            "new-concert-collect": run_new_concert_collect,
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

    global _scheduler
    _scheduler = _build_scheduler()
    _scheduler.start()
    logger.info("스케줄러 시작 (종료: Ctrl+C)")
    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        _scheduler.shutdown()
        logger.info("스케줄러 종료")


if __name__ == "__main__":
    main()
