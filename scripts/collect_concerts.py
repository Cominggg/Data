"""KOPIS 내한공연 수집 스크립트.

사용법:
    python scripts/collect_concerts.py --start 20240101 --end 20241231
"""
import argparse
import logging
import sys

from collector.db.connection import get_session
from collector.kopis.client import KopisClient
from collector.kopis.service import collect_kopis_concerts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="KOPIS 내한공연 수집")
    parser.add_argument("--start", required=True, help="조회 시작일 (YYYYMMDD)")
    parser.add_argument("--end", required=True, help="조회 종료일 (YYYYMMDD)")
    parser.add_argument("--max-pages", type=int, default=10, help="최대 페이지 수")
    parser.add_argument("--rows", type=int, default=100, help="페이지 당 결과 수")
    args = parser.parse_args()

    client = KopisClient()
    with get_session() as session:
        saved = collect_kopis_concerts(
            session=session,
            client=client,
            start_date=args.start,
            end_date=args.end,
            max_pages=args.max_pages,
            rows=args.rows,
        )
    logger.info("완료: 총 %d건 저장", saved)


if __name__ == "__main__":
    main()
