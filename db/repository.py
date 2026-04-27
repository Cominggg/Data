import json
import logging

from sqlalchemy import text

from db.connection import get_session

logger = logging.getLogger(__name__)


def save_releases(releases: list[dict]) -> None:
    """수집된 릴리즈 목록을 DB에 저장한다. first_release_date 기준 미존재 항목만 INSERT."""
    with get_session() as session:
        artist_id_cache: dict = {}
        for release in releases:
            artist_mbid = release["artist_mbid"]
            if artist_mbid not in artist_id_cache:
                artist_row = session.execute(
                    text("SELECT id FROM artist WHERE mbid = :mbid"),
                    {"mbid": artist_mbid},
                ).fetchone()
                if not artist_row:
                    logger.warning("아티스트 미존재 — 저장 건너뜀: artist_mbid=%s", artist_mbid)
                    artist_id_cache[artist_mbid] = None
                else:
                    artist_id_cache[artist_mbid] = artist_row[0]

            artist_id = artist_id_cache[artist_mbid]
            if artist_id is None:
                continue

            rg_row = session.execute(
                text("""
                    INSERT INTO release_group
                        (mbid, artist_id, title, type, first_release_date, cover_url)
                    VALUES
                        (:mbid, :artist_id, :title, :type, :first_release_date, :cover_url)
                    ON CONFLICT (mbid) DO UPDATE SET mbid = EXCLUDED.mbid
                    RETURNING id
                """),
                {
                    "mbid": release["release_group_mbid"],
                    "artist_id": artist_id,
                    "title": release["title"],
                    "type": release["type"],
                    "first_release_date": release["first_release_date"],
                    "cover_url": release["cover_url"],
                },
            ).fetchone()

            if not release.get("tracks") or not rg_row:
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


def save_concerts(concerts: list[dict]) -> None:
    """수집된 공연 목록을 concert 테이블에 저장한다. kopis_id 중복 시 무시."""
    with get_session() as session:
        for concert in concerts:
            session.execute(
                text("""
                    INSERT INTO concert
                        (kopis_id, prfnm, prfcast, prfpdfrom, prfpdto,
                         fcltynm, prfstate, updatedate, relates)
                    VALUES
                        (:kopis_id, :prfnm, :prfcast, :prfpdfrom, :prfpdto,
                         :fcltynm, :prfstate, :updatedate, :relates)
                    ON CONFLICT (kopis_id) DO NOTHING
                """),
                {
                    "kopis_id": concert["kopis_id"],
                    "prfnm": concert["prfnm"],
                    "prfcast": concert["prfcast"],
                    "prfpdfrom": concert["prfpdfrom"],
                    "prfpdto": concert["prfpdto"],
                    "fcltynm": concert["fcltynm"],
                    "prfstate": concert["prfstate"],
                    "updatedate": concert["updatedate"],
                    "relates": json.dumps(concert["relates"], ensure_ascii=False),
                },
            )
    logger.info("공연 저장 완료: %d건 처리", len(concerts))


def get_completed_concerts() -> list[dict]:
    """setlist 미수집 공연완료 건을 아티스트 MBID와 함께 반환한다."""
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT DISTINCT c.id AS concert_id, c.prfnm, c.prfpdfrom, c.prfpdto,
                                a.mbid AS artist_mbid
                FROM concert c
                JOIN concert_artist ca ON ca.concert_id = c.id AND ca.approved = true
                JOIN artist a ON a.id = ca.artist_id
                LEFT JOIN setlist s ON s.concert_id = c.id
                WHERE c.prfstate = '공연완료'
                  AND s.id IS NULL
            """)
        ).fetchall()
    return [
        {
            "concert_id": row[0],
            "prfnm": row[1],
            "prfpdfrom": str(row[2]) if row[2] else None,
            "prfpdto": str(row[3]) if row[3] else None,
            "artist_mbid": row[4],
        }
        for row in rows
    ]


def save_setlists(setlists: list[dict]) -> None:
    """수집된 셋리스트를 setlist·setlist_track 테이블에 저장한다. 중복 시 무시."""
    with get_session() as session:
        for item in setlists:
            row = session.execute(
                text("""
                    INSERT INTO setlist (concert_id, setlist_fm_id, collected_at)
                    VALUES (:concert_id, :setlist_fm_id, NOW())
                    ON CONFLICT (setlist_fm_id) DO NOTHING
                    RETURNING id
                """),
                {"concert_id": item["concert_id"], "setlist_fm_id": item["setlist_fm_id"]},
            ).fetchone()

            if not row or not item.get("tracks"):
                continue

            setlist_id = row[0]
            session.execute(
                text("""
                    INSERT INTO setlist_track (setlist_id, position, song_name, info)
                    VALUES (:setlist_id, :position, :song_name, :info)
                """),
                [
                    {
                        "setlist_id": setlist_id,
                        "position": track["position"],
                        "song_name": track["song_name"],
                        "info": track.get("info"),
                    }
                    for track in item["tracks"]
                ],
            )

    logger.info("셋리스트 저장 완료: %d건 처리", len(setlists))


def update_concert_status(concerts: list[dict]) -> None:
    """updatedate 변화 감지 시 prfstate와 updatedate를 갱신한다."""
    updated = 0
    with get_session() as session:
        for concert in concerts:
            row = session.execute(
                text("SELECT updatedate FROM concert WHERE kopis_id = :kopis_id"),
                {"kopis_id": concert["kopis_id"]},
            ).fetchone()

            if row is None:
                continue

            if row[0] != concert["updatedate"]:
                session.execute(
                    text("""
                        UPDATE concert
                        SET prfstate = :prfstate, updatedate = :updatedate
                        WHERE kopis_id = :kopis_id
                    """),
                    {
                        "prfstate": concert["prfstate"],
                        "updatedate": concert["updatedate"],
                        "kopis_id": concert["kopis_id"],
                    },
                )
                updated += 1

    logger.info("공연 상태 갱신 완료: %d건 변경", updated)
