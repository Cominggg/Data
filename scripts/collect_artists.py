"""JPOP 아티스트 수집 스크립트.

사용법:
    python scripts/collect_artists.py
    python scripts/collect_artists.py --query "tag:j-pop" --max-pages 5
"""
import argparse
import logging
import sys

from collector.db.connection import get_session
from collector.musicbrainz.client import MusicBrainzClient
from collector.musicbrainz.service import collect_jpop_artists

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="MusicBrainz JPOP 아티스트 수집")
    parser.add_argument("--query", default="tag:j-pop", help="MusicBrainz 검색 쿼리")
    parser.add_argument("--max-pages", type=int, default=10, help="최대 페이지 수")
    parser.add_argument("--limit", type=int, default=25, help="페이지 당 결과 수")
    args = parser.parse_args()

    client = MusicBrainzClient()
    with get_session() as session:
        saved = collect_jpop_artists(
            session=session,
            client=client,
            query=args.query,
            limit=args.limit,
            max_pages=args.max_pages,
        )
    logger.info("완료: 총 %d건 저장", saved)


if __name__ == "__main__":
    main()
