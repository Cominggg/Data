import logging

from sqlalchemy import text

from db.connection import get_session

logger = logging.getLogger(__name__)


def save_releases(releases: list[dict]) -> None:
    """수집된 릴리즈 목록을 DB에 저장한다. first_release_date 기준 미존재 항목만 INSERT."""
    with get_session() as session:
        for release in releases:
            artist_row = session.execute(
                text("SELECT id FROM artist WHERE mbid = :mbid"),
                {"mbid": release["artist_mbid"]},
            ).fetchone()
            if not artist_row:
                logger.warning("아티스트 미존재 — 저장 건너뜀: artist_mbid=%s", release["artist_mbid"])
                continue
            artist_id = artist_row[0]

            session.execute(
                text("""
                    INSERT INTO release_group
                        (mbid, artist_id, title, type, first_release_date, cover_url)
                    VALUES
                        (:mbid, :artist_id, :title, :type, :first_release_date, :cover_url)
                    ON CONFLICT (mbid) DO NOTHING
                """),
                {
                    "mbid": release["release_group_mbid"],
                    "artist_id": artist_id,
                    "title": release["title"],
                    "type": release["type"],
                    "first_release_date": release["first_release_date"],
                    "cover_url": release["cover_url"],
                },
            )

            if not release.get("tracks"):
                continue

            rg_row = session.execute(
                text("SELECT id FROM release_group WHERE mbid = :mbid"),
                {"mbid": release["release_group_mbid"]},
            ).fetchone()
            if not rg_row:
                continue
            rg_id = rg_row[0]

            for track in release["tracks"]:
                session.execute(
                    text("""
                        INSERT INTO track
                            (release_group_id, mbid, title, position, length_ms)
                        VALUES
                            (:release_group_id, :mbid, :title, :position, :length_ms)
                        ON CONFLICT (mbid) DO NOTHING
                    """),
                    {
                        "release_group_id": rg_id,
                        "mbid": track["mbid"],
                        "title": track["title"],
                        "position": track["position"],
                        "length_ms": track["length_ms"],
                    },
                )

        logger.info("릴리즈 저장 완료: %d건 처리", len(releases))
