import argparse
import logging
import time

from apscheduler.schedulers.background import BackgroundScheduler

from collectors import kopis, musicbrainz, release, setlist
from db.repository import (
    get_all_aliases,
    get_all_artist_mbids,
    get_unmatched_concerts,
    save_artists,
    save_concert_artists,
    save_concerts,
    save_releases,
    save_setlists,
    save_to_review_queue,
    update_artist_is_coming,
    update_concert_status,
)
from matchers.artist_matcher import match_concert

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_initial_collect() -> None:
    """초기 아티스트 + 릴리즈 수집 (1회성 CLI).

    재개 지원: 이미 DB에 저장된 아티스트는 건너뛰고, 릴리즈는 DB 기준 mbid 목록을 사용한다.
    중단 후 재실행해도 처음부터 다시 수집하지 않는다.
    """
    logger.info("=== 초기 수집 시작 ===")

    saved_mbids = set(get_all_artist_mbids())
    if saved_mbids:
        logger.info("기존 저장 아티스트 %d건 건너뜀 — 재개 모드", len(saved_mbids))

    artists = musicbrainz.collect_artists(skip_mbids=saved_mbids)
    save_artists(artists)

    # 재개 시 기존 아티스트도 포함해야 하므로 저장 완료 후 DB에서 전체 MBID를 재조회한다.
    for mbid in get_all_artist_mbids():
        releases = release.collect_releases(mbid)
        save_releases(releases)

    logger.info("=== 초기 수집 완료 ===")


def run_kopis_collect_and_match() -> None:
    """KOPIS 수집 + 공연-아티스트 매칭 (주 1회, 월요일)."""
    logger.info("=== KOPIS 수집·매칭 잡 시작 ===")
    concerts = kopis.collect()
    save_concerts(concerts)

    aliases = get_all_aliases()
    unmatched = get_unmatched_concerts()

    all_matches: list[dict] = []
    all_failures: list[dict] = []
    for concert in unmatched:
        matches, failures = match_concert(concert, aliases)
        all_matches.extend(matches)
        all_failures.extend(failures)

    if all_matches:
        save_concert_artists(all_matches)
        update_artist_is_coming()

    if all_failures:
        save_to_review_queue(all_failures)

    logger.info("=== KOPIS 수집·매칭 잡 완료 ===")


def run_status_update() -> None:
    """공연 상태 갱신 + is_coming 동기화 (매일)."""
    logger.info("=== 공연 상태 갱신 잡 시작 ===")
    concerts = kopis.collect()
    update_concert_status(concerts)
    update_artist_is_coming()
    logger.info("=== 공연 상태 갱신 잡 완료 ===")


def run_release_update() -> None:
    """릴리즈 갱신 (주 1회, 화요일). 신규 항목만 INSERT."""
    logger.info("=== 릴리즈 갱신 잡 시작 ===")
    for mbid in get_all_artist_mbids():
        releases = release.collect_releases(mbid)
        save_releases(releases)
    logger.info("=== 릴리즈 갱신 잡 완료 ===")


def run_setlist_collect() -> None:
    """setlist.fm 수집 (매일)."""
    logger.info("=== setlist 수집 잡 시작 ===")
    setlists = setlist.collect()
    save_setlists(setlists)
    logger.info("=== setlist 수집 잡 완료 ===")


def _build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Seoul")
    scheduler.add_job(run_kopis_collect_and_match, "cron", day_of_week="mon", hour=3)
    scheduler.add_job(run_status_update, "cron", hour=4)
    scheduler.add_job(run_release_update, "cron", day_of_week="tue", hour=5)
    scheduler.add_job(run_setlist_collect, "cron", hour=6)
    return scheduler


def main() -> None:
    parser = argparse.ArgumentParser(description="Coming Data Pipeline")
    parser.add_argument(
        "command",
        nargs="?",
        choices=["init"],
        help="init: 초기 아티스트·릴리즈 수집 후 종료",
    )
    args = parser.parse_args()

    if args.command == "init":
        run_initial_collect()
        return

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
