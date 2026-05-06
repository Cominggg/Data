import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from db.connection import get_session

logger = logging.getLogger(__name__)


def save_artists(artists: list[dict]) -> None:
    """수집된 아티스트 목록을 artist, artist_alias, artist_url 테이블에 저장한다.

    아티스트별로 독립 트랜잭션을 사용해 한 건 실패가 전체에 영향을 주지 않는다.
    """
    saved = 0
    for artist in artists:
        try:
            with get_session() as session:
                row = session.execute(
                    text("""
                        INSERT INTO artist (mbid, name, sort_name, debut_date)
                        VALUES (:mbid, :name, :sort_name, :debut_date)
                        ON CONFLICT (mbid) DO NOTHING
                        RETURNING id
                    """),
                    {
                        "mbid": artist["mbid"],
                        "name": artist["name"],
                        "sort_name": artist["sort_name"],
                        "debut_date": artist.get("debut_date"),
                    },
                ).fetchone()

                if row is None:
                    row = session.execute(
                        text("SELECT id FROM artist WHERE mbid = :mbid"),
                        {"mbid": artist["mbid"]},
                    ).fetchone()

                if row is None:
                    logger.warning("아티스트 ID 조회 실패 — 저장 건너뜀: mbid=%s", artist["mbid"])
                    continue

                artist_id = row[0]

                for alias in artist.get("aliases", []):
                    session.execute(
                        text("""
                            INSERT INTO artist_alias (artist_id, name, locale)
                            VALUES (:artist_id, :name, :locale)
                            ON CONFLICT DO NOTHING
                        """),
                        {"artist_id": artist_id, "name": alias["name"], "locale": alias["locale"]},
                    )

                for url_rel in artist.get("url_rels", []):
                    session.execute(
                        text("""
                            INSERT INTO artist_url (artist_id, type, url)
                            VALUES (:artist_id, :type, :url)
                            ON CONFLICT DO NOTHING
                        """),
                        {"artist_id": artist_id, "type": url_rel["type"], "url": url_rel["url"]},
                    )

                saved += 1
        except SQLAlchemyError as e:
            logger.error("아티스트 저장 실패 — 건너뜀: mbid=%s, 오류=%s", artist["mbid"], e)

    logger.info("아티스트 저장 완료: %d / %d건 처리", saved, len(artists))


def save_releases(releases: list[dict]) -> None:
    """수집된 릴리즈 목록을 DB에 저장한다. release_group 단위 독립 트랜잭션으로 격리."""
    artist_id_cache: dict = {}
    saved = 0

    for release in releases:
        artist_mbid = release["artist_mbid"]

        if artist_mbid not in artist_id_cache:
            try:
                with get_session() as session:
                    row = session.execute(
                        text("SELECT id FROM artist WHERE mbid = :mbid"),
                        {"mbid": artist_mbid},
                    ).fetchone()
                artist_id_cache[artist_mbid] = row[0] if row else None
            except SQLAlchemyError as e:
                logger.error("아티스트 ID 조회 실패 — 건너뜀: artist_mbid=%s, %s", artist_mbid, e)
                artist_id_cache[artist_mbid] = None

        artist_id = artist_id_cache[artist_mbid]
        if artist_id is None:
            logger.warning("아티스트 미존재 — 저장 건너뜀: artist_mbid=%s", artist_mbid)
            continue

        try:
            with get_session() as session:
                rg_row = session.execute(
                    text("""
                        INSERT INTO release_group
                            (mbid, artist_id, title, type, first_release_date, cover_url, label)
                        VALUES
                            (:mbid, :artist_id, :title, :type, :first_release_date, :cover_url, :label)
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
                        "label": release.get("label"),
                    },
                ).fetchone()

                if release.get("tracks") and rg_row:
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
            saved += 1
        except SQLAlchemyError as e:
            logger.error("릴리즈 저장 실패 — 건너뜀: mbid=%s, %s", release["release_group_mbid"], e)

    logger.info("릴리즈 저장 완료: %d / %d건 처리", saved, len(releases))


def save_concerts(concerts: list[dict]) -> None:
    """수집된 공연 목록을 concert 테이블에 저장한다. kopis_id 중복 시 무시."""
    with get_session() as session:
        for concert in concerts:
            row = session.execute(
                text("""
                    INSERT INTO concert
                        (kopis_id, title, "cast", start_date, end_date,
                         venue_name, venue_address, poster_url, price, status, kopis_update_date)
                    VALUES
                        (:kopis_id, :title, :cast, :start_date, :end_date,
                         :venue_name, :venue_address, :poster_url, :price, :status, :kopis_update_date)
                    ON CONFLICT (kopis_id) DO NOTHING
                    RETURNING id
                """),
                {
                    "kopis_id": concert["kopis_id"],
                    "title": concert["prfnm"],
                    "cast": concert["prfcast"],
                    "start_date": concert["prfpdfrom"],
                    "end_date": concert["prfpdto"],
                    "venue_name": concert["fcltynm"],
                    "venue_address": concert.get("venue_address"),
                    "poster_url": concert.get("poster_url"),
                    "price": concert.get("price"),
                    "status": concert["prfstate"],
                    "kopis_update_date": concert["updatedate"],
                },
            ).fetchone()

            if row is None:
                row = session.execute(
                    text("SELECT id FROM concert WHERE kopis_id = :kopis_id"),
                    {"kopis_id": concert["kopis_id"]},
                ).fetchone()

            if not row or not concert.get("relates"):
                continue

            concert_id = row[0]
            for link in concert["relates"]:
                session.execute(
                    text("""
                        INSERT INTO concert_booking_link (concert_id, name, url)
                        VALUES (:concert_id, :name, :url)
                        ON CONFLICT (concert_id, url) DO NOTHING
                    """),
                    {
                        "concert_id": concert_id,
                        "name": link["relatenm"],
                        "url": link["relateurl"],
                    },
                )
    logger.info("공연 저장 완료: %d건 처리", len(concerts))


def get_completed_concerts() -> list[dict]:
    """setlist 미수집 공연완료 건을 아티스트 MBID와 함께 반환한다."""
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT DISTINCT c.id AS concert_id, c.title, c.start_date, c.end_date,
                                a.mbid AS artist_mbid
                FROM concert c
                JOIN concert_artist ca ON ca.concert_id = c.id AND ca.approved = true
                JOIN artist a ON a.id = ca.artist_id
                LEFT JOIN setlist s ON s.concert_id = c.id
                WHERE c.status = '공연완료'
                  AND s.id IS NULL
            """)
        ).fetchall()
    return [
        {
            "concert_id": row[0],
            "title": row[1],
            "start_date": str(row[2]) if row[2] else None,
            "end_date": str(row[3]) if row[3] else None,
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


def get_all_aliases() -> list[dict]:
    """매칭에 사용할 모든 아티스트 alias를 반환한다."""
    with get_session() as session:
        rows = session.execute(
            text("SELECT artist_id, name FROM artist_alias")
        ).fetchall()
    return [{"artist_id": row[0], "name": row[1]} for row in rows]


def get_all_artist_mbids() -> list[str]:
    """DB에 저장된 모든 아티스트 MBID를 반환한다."""
    with get_session() as session:
        rows = session.execute(text("SELECT mbid FROM artist")).fetchall()
    return [row[0] for row in rows]


def get_matched_artist_mbids() -> list[str]:
    """승인된 공연-아티스트 매칭이 있는 아티스트 MBID를 반환한다."""
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT DISTINCT a.mbid
                FROM artist a
                JOIN concert_artist ca ON ca.artist_id = a.id
                WHERE ca.approved = true
            """)
        ).fetchall()
    return [row[0] for row in rows]


def get_release_groups_without_cover() -> list[str]:
    """cover_url이 없는 release_group의 mbid 목록을 반환한다."""
    with get_session() as session:
        rows = session.execute(
            text("SELECT mbid FROM release_group WHERE cover_url IS NULL")
        ).fetchall()
    return [row[0] for row in rows]


def update_release_group_cover(mbid: str, cover_url: str) -> None:
    """release_group의 cover_url을 갱신한다."""
    with get_session() as session:
        session.execute(
            text("UPDATE release_group SET cover_url = :cover_url WHERE mbid = :mbid"),
            {"cover_url": cover_url, "mbid": mbid},
        )


def get_concert_with_artist(concert_id: int) -> Optional[dict]:
    """셋리스트 수집에 필요한 공연 정보(artist_mbid 포함)를 반환한다. 없으면 None."""
    with get_session() as session:
        row = session.execute(
            text("""
                SELECT c.id, c.start_date, c.end_date, a.mbid AS artist_mbid
                FROM concert c
                JOIN concert_artist ca ON ca.concert_id = c.id
                JOIN artist a ON a.id = ca.artist_id
                WHERE c.id = :concert_id
                LIMIT 1
            """),
            {"concert_id": concert_id},
        ).fetchone()
    if row is None:
        return None
    return {
        "concert_id": row[0],
        "start_date": str(row[1]) if row[1] else None,
        "end_date": str(row[2]) if row[2] else None,
        "artist_mbid": row[3],
    }


def get_concert_by_kopis_id(kopis_id: str) -> Optional[dict]:
    """kopis_id로 공연을 조회한다. 없으면 None 반환."""
    with get_session() as session:
        row = session.execute(
            text('SELECT id, title, "cast" FROM concert WHERE kopis_id = :kopis_id'),
            {"kopis_id": kopis_id},
        ).fetchone()
    if row is None:
        return None
    return {"concert_id": row[0], "title": row[1], "cast": row[2]}


def get_unmatched_concerts() -> list[dict]:
    """concert_artist 매칭이 없는 공연을 반환한다."""
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT c.id AS concert_id, c.title, c."cast"
                FROM concert c
                LEFT JOIN concert_artist ca ON ca.concert_id = c.id
                WHERE ca.concert_id IS NULL
            """)
        ).fetchall()
    return [{"concert_id": row[0], "title": row[1], "cast": row[2]} for row in rows]


def save_concert_artists(matches: list[dict]) -> None:
    """매칭 결과를 concert_artist 테이블에 저장한다. HIGH confidence는 즉시 승인."""
    with get_session() as session:
        for match in matches:
            session.execute(
                text("""
                    INSERT INTO concert_artist
                        (concert_id, artist_id, confidence, matched_by, approved)
                    VALUES
                        (:concert_id, :artist_id, :confidence, :matched_by, :approved)
                    ON CONFLICT (concert_id, artist_id) DO NOTHING
                """),
                {
                    "concert_id": match["concert_id"],
                    "artist_id": match["artist_id"],
                    "confidence": match["confidence"],
                    "matched_by": match["matched_by"],
                    "approved": match["approved"],
                },
            )
    logger.info("공연-아티스트 매칭 저장 완료: %d건 처리", len(matches))



def update_artist_is_coming() -> int:
    """오늘 이후 approved 공연 보유 여부에 따라 artist.is_coming을 갱신한다.

    값이 실제로 바뀌는 행만 UPDATE해 불필요한 쓰기 I/O를 줄인다.
    반환값: 갱신된 행 수
    """
    with get_session() as session:
        result = session.execute(
            text("""
                UPDATE artist
                SET is_coming = new_val.is_coming
                FROM (
                    SELECT a.id,
                           EXISTS (
                               SELECT 1
                               FROM concert_artist ca
                               JOIN concert c ON c.id = ca.concert_id
                               WHERE ca.artist_id = a.id
                                 AND ca.approved = true
                                 AND c.end_date >= CURRENT_DATE
                           ) AS is_coming
                    FROM artist a
                ) new_val
                WHERE artist.id = new_val.id
                  AND artist.is_coming IS DISTINCT FROM new_val.is_coming
            """)
        )
        updated = result.rowcount
    logger.info("artist.is_coming 갱신 완료: %d건 변경", updated)
    return updated


def update_concert_status(concerts: list[dict]) -> None:
    """updatedate 변화 감지 시 status와 kopis_update_date를 갱신한다."""
    updated = 0
    with get_session() as session:
        for concert in concerts:
            row = session.execute(
                text("SELECT kopis_update_date FROM concert WHERE kopis_id = :kopis_id"),
                {"kopis_id": concert["kopis_id"]},
            ).fetchone()

            if row is None:
                continue

            if row[0] != concert["updatedate"]:
                session.execute(
                    text("""
                        UPDATE concert
                        SET status = :status, kopis_update_date = :kopis_update_date
                        WHERE kopis_id = :kopis_id
                    """),
                    {
                        "status": concert["prfstate"],
                        "kopis_update_date": concert["updatedate"],
                        "kopis_id": concert["kopis_id"],
                    },
                )
                updated += 1

    logger.info("공연 상태 갱신 완료: %d건 변경", updated)
