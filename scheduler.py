import argparse
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List

from apscheduler.schedulers.background import BackgroundScheduler

from collectors import artist_image, kopis, musicbrainz, release, setlist, wikipedia
from db.repository import (
    get_active_concerts,
    get_all_aliases,
    get_all_artist_mbids,
    get_all_artists,
    get_artists_without_image,
    get_concert_by_kopis_id,
    get_concert_with_artist,
    get_existing_kopis_ids,
    get_matched_artist_mbids,
    get_release_groups_without_cover,
    get_unmatched_concerts,
    save_aliases,
    save_artists,
    save_concert_artists,
    save_concerts,
    save_releases,
    save_setlists,
    update_artist_image,
    update_artist_is_coming,
    update_concert_status,
    update_release_group_cover,
)
from matchers.artist_matcher import has_match, match_concert

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

_RELEASE_TYPE_ORDER = {"Album": 0, "EP": 1, "Single": 2}


def _sort_releases(releases: List[dict]) -> List[dict]:
    return sorted(releases, key=lambda r: _RELEASE_TYPE_ORDER.get(r.get("type", ""), 9))


def run_initial_collect(
    skip_artists: bool = False,
    force_artists: bool = False,
    skip_kopis: bool = False,
    skip_wikipedia: bool = False,
    skip_releases: bool = False,
    skip_cover_art: bool = False,
    skip_artist_image: bool = False,
    skip_setlist: bool = False,
) -> None:
    """초기 수집 (1회성 CLI): 아티스트 → KOPIS 매칭 → 매칭 아티스트 릴리즈 순으로 수집.

    재개 지원: 이미 DB에 저장된 아티스트는 건너뛴다.
    force_artists=True 시 기존 DB 아티스트를 건너뛰지 않고 전체 재수집한다.
    skip_kopis=True 시 KOPIS 수집·매칭을 건너뛰고 릴리즈 수집으로 진행한다.
    skip_wikipedia=True 시 Wikipedia alias 수집을 건너뛴다.
    skip_releases=True 시 릴리즈 수집을 건너뛴다.
    skip_cover_art=True 시 커버아트 수집을 건너뛴다.
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
        run_status_update()

    if skip_releases:
        logger.info("--skip-releases 플래그 감지 — 릴리즈 수집 건너뜀")
    else:
        matched_mbids = get_matched_artist_mbids()
        logger.info("매칭 아티스트 %d건 릴리즈 수집 시작", len(matched_mbids))
        for mbid in matched_mbids:
            releases = _sort_releases(release.collect_releases(mbid))
            save_releases(releases)

    if skip_cover_art:
        logger.info("--skip-cover-art 플래그 감지 — 커버아트 수집 건너뜀")
    else:
        run_cover_art_update()

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
    """Wikipedia 한국어 alias 수집 (초기 1회 + 주 1회, 목요일)."""
    logger.info("=== Wikipedia 한국어 alias 수집 잡 시작 ===")
    artists = get_all_artists()
    aliases = wikipedia.collect_korean_aliases(artists)
    if aliases:
        save_aliases(aliases)
    logger.info("=== Wikipedia 한국어 alias 수집 잡 완료 ===")



def run_status_update() -> None:
    """공연 상태 갱신 + 신규 공연 저장·매칭 + is_coming 동기화 (매일)."""
    logger.info("=== 공연 상태 갱신 잡 시작 ===")

    # ① 상태 갱신: DB의 진행 중 공연을 개별 API로 최신 상태 갱신
    active = get_active_concerts()
    if active:
        logger.info("활성 공연 %d건 상태 갱신 시작", len(active))
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(kopis.collect_by_id, c["kopis_id"]): c["kopis_id"] for c in active}
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

    # ② 신규 발견: 180일 lookback으로 신규 공연 탐지·저장
    concerts = kopis.collect()
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
            save_concert_artists(all_matches)

    update_artist_is_coming()
    logger.info("=== 공연 상태 갱신 잡 완료 ===")


def run_cover_art_update() -> None:
    """cover_url 미수집 릴리즈 그룹의 커버아트를 수집한다 (주 1회, 수요일)."""
    logger.info("=== 커버아트 수집 잡 시작 ===")
    mbids = get_release_groups_without_cover()
    logger.info("커버아트 미수집 릴리즈 그룹: %d건", len(mbids))
    for mbid in mbids:
        cover_url = release.collect_cover_art(mbid)
        if cover_url:
            update_release_group_cover(mbid, cover_url)
    logger.info("=== 커버아트 수집 잡 완료 ===")


def run_artist_image_update() -> None:
    """image_url 미수집 아티스트의 프로필 이미지를 수집한다 (주 1회, 목요일)."""
    logger.info("=== 아티스트 이미지 수집 잡 시작 ===")
    artists = get_artists_without_image()
    logger.info("이미지 미수집 아티스트: %d건", len(artists))
    for a in artists:
        try:
            image_url = artist_image.collect_artist_image(a["mbid"])
        except Exception as e:
            logger.warning("아티스트 이미지 수집 실패 mbid=%s: %s", a["mbid"], e)
            continue
        if image_url:
            update_artist_image(a["id"], image_url)
    logger.info("=== 아티스트 이미지 수집 잡 완료 ===")


def run_release_update() -> None:
    """릴리즈 갱신 (주 1회, 화요일). 신규 항목만 INSERT."""
    logger.info("=== 릴리즈 갱신 잡 시작 ===")
    for mbid in get_all_artist_mbids():
        releases = _sort_releases(release.collect_releases(mbid))
        save_releases(releases)
    logger.info("=== 릴리즈 갱신 잡 완료 ===")


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

    save_concerts([concert])

    concert_row = get_concert_by_kopis_id(kopis_id)
    if concert_row:
        matches, _ = match_concert(concert_row, aliases)
        if matches:
            save_concert_artists(matches)
            update_artist_is_coming()

    logger.info("단건 공연 수집 완료: kopis_id=%s", kopis_id)
    return True


def collect_and_save_release_group(release_group_mbid: str, artist_mbid: str) -> bool:
    """단건 릴리즈 그룹을 수집해 DB에 저장한다. 성공 시 True 반환."""
    rg = release.collect_release_group(release_group_mbid, artist_mbid)
    if rg is None:
        logger.warning("릴리즈 그룹 수집 실패: mbid=%s", release_group_mbid)
        return False
    save_releases([rg])
    logger.info("단건 릴리즈 그룹 수집 완료: mbid=%s", release_group_mbid)
    return True


def collect_and_save_cover_art(release_group_mbid: str) -> bool:
    """단건 릴리즈 그룹의 커버아트를 수집해 DB에 갱신한다. 성공 시 True 반환."""
    cover_url = release.collect_cover_art(release_group_mbid)
    if not cover_url:
        logger.info("커버아트 없음: mbid=%s", release_group_mbid)
        return False
    update_release_group_cover(release_group_mbid, cover_url)
    logger.info("단건 커버아트 수집 완료: mbid=%s", release_group_mbid)
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
    scheduler.add_job(run_release_update, "cron", day_of_week="tue", hour=5)
    scheduler.add_job(run_cover_art_update, "cron", day_of_week="wed", hour=5)
    scheduler.add_job(run_wikipedia_collect, "cron", day_of_week="thu", hour=3)
    scheduler.add_job(run_artist_image_update, "cron", day_of_week="thu", hour=5)
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
        "--skip-cover-art",
        action="store_true",
        help="커버아트 수집을 건너뜀 (init 전용)",
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
    args = parser.parse_args()

    if args.command == "init":
        run_initial_collect(
            skip_artists=args.skip_artists,
            force_artists=args.force_artists,
            skip_kopis=args.skip_kopis,
            skip_wikipedia=args.skip_wikipedia,
            skip_releases=args.skip_releases,
            skip_cover_art=args.skip_cover_art,
            skip_artist_image=args.skip_artist_image,
            skip_setlist=args.skip_setlist,
        )
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
