import logging
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def upsert_concert(session: Session, concert: dict) -> None:
    """공연을 DB에 저장한다. kopis_id 기준으로 중복 시 업데이트."""
    sql = """
        INSERT INTO concerts (kopis_id, title, start_date, end_date, venue, venue_area, artist_id)
        VALUES (:kopis_id, :title, :start_date, :end_date, :venue, :venue_area, :artist_id)
        ON CONFLICT (kopis_id) DO UPDATE SET
            title      = EXCLUDED.title,
            start_date = EXCLUDED.start_date,
            end_date   = EXCLUDED.end_date,
            venue      = EXCLUDED.venue,
            venue_area = EXCLUDED.venue_area,
            artist_id  = EXCLUDED.artist_id,
            updated_at = NOW()
    """
    session.execute(sql, concert)
    logger.debug("공연 upsert 완료: kopis_id=%s title=%s", concert["kopis_id"], concert["title"])


def find_concert_by_kopis_id(session: Session, kopis_id: str) -> Optional[dict]:
    """kopis_id로 공연을 조회한다."""
    sql = "SELECT * FROM concerts WHERE kopis_id = :kopis_id"
    row = session.execute(sql, {"kopis_id": kopis_id}).fetchone()
    return dict(row) if row else None
