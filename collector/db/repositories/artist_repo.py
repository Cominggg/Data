import logging
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def upsert_artist(session: Session, artist: dict) -> None:
    """아티스트를 DB에 저장한다. mbid 기준으로 중복 시 업데이트."""
    sql = """
        INSERT INTO artists (mbid, name, sort_name, country, area, begin_date, end_date, artist_type)
        VALUES (:mbid, :name, :sort_name, :country, :area, :begin_date, :end_date, :artist_type)
        ON CONFLICT (mbid) DO UPDATE SET
            name       = EXCLUDED.name,
            sort_name  = EXCLUDED.sort_name,
            country    = EXCLUDED.country,
            area       = EXCLUDED.area,
            begin_date = EXCLUDED.begin_date,
            end_date   = EXCLUDED.end_date,
            artist_type = EXCLUDED.artist_type,
            updated_at = NOW()
    """
    session.execute(sql, artist)
    logger.debug("아티스트 upsert 완료: mbid=%s name=%s", artist["mbid"], artist["name"])


def find_artist_by_mbid(session: Session, mbid: str) -> Optional[dict]:
    """mbid로 아티스트를 조회한다."""
    sql = "SELECT * FROM artists WHERE mbid = :mbid"
    row = session.execute(sql, {"mbid": mbid}).fetchone()
    return dict(row) if row else None


def find_artist_by_name(session: Session, name: str) -> Optional[dict]:
    """이름으로 아티스트를 조회한다 (정확히 일치)."""
    sql = "SELECT * FROM artists WHERE name = :name LIMIT 1"
    row = session.execute(sql, {"name": name}).fetchone()
    return dict(row) if row else None
