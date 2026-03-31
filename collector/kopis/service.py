import logging

from sqlalchemy.orm import Session

from collector.db.repositories.artist_repo import find_artist_by_name
from collector.db.repositories.concert_repo import upsert_concert
from collector.kopis.client import KopisClient
from collector.kopis.models import ConcertResult

logger = logging.getLogger(__name__)


def _match_artist(session: Session, title: str) -> int | None:
    """공연명에서 아티스트 이름을 추출해 DB에서 매핑을 시도한다.

    현재는 공연명과 아티스트명 단순 포함 여부로 판별한다.
    정밀도가 낮으면 별도 매핑 테이블 도입을 고려할 것.
    """
    row = find_artist_by_name(session, title)
    if row:
        return row["id"]
    return None


def collect_kopis_concerts(
    session: Session,
    client: KopisClient,
    start_date: str,
    end_date: str,
    max_pages: int = 10,
    rows: int = 100,
) -> int:
    """KOPIS에서 내한공연을 수집해 DB에 저장하고 저장된 건수를 반환한다.

    Args:
        start_date: 조회 시작일 (YYYYMMDD)
        end_date: 조회 종료일 (YYYYMMDD)
    """
    saved = 0
    for page in range(1, max_pages + 1):
        logger.info("KOPIS 공연 조회 page=%d start=%s end=%s", page, start_date, end_date)
        items = client.get_concerts(start_date=start_date, end_date=end_date, page=page, rows=rows)

        if not items:
            logger.info("더 이상 결과 없음. 종료.")
            break

        for raw in items:
            concert = ConcertResult.from_api_response(raw)
            concert.artist_id = _match_artist(session, concert.title)
            upsert_concert(session, concert.to_db_dict())
            saved += 1
            logger.info("저장: %s (%s) artist_id=%s", concert.title, concert.kopis_id, concert.artist_id)

    return saved
