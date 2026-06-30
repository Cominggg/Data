import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from db.connection import get_session

logger = logging.getLogger(__name__)

_KOPIS_STATUS_MAP = {
    "공연예정": "UPCOMING",
    "공연중": "ONGOING",
    "공연완료": "ENDED",
    "공연취소": "CANCELLED",
}


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
                        INSERT INTO artist (mbid, name, sort_name)
                        VALUES (:mbid, :name, :sort_name)
                        ON CONFLICT (mbid) DO NOTHING
                        RETURNING id
                    """),
                    {
                        "mbid": artist["mbid"],
                        "name": artist["name"],
                        "sort_name": artist["sort_name"],
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
                            ON CONFLICT (artist_id, name) DO NOTHING
                        """),
                        {"artist_id": artist_id, "name": alias["name"], "locale": alias["locale"]},
                    )

                for url_rel in artist.get("url_rels", []):
                    session.execute(
                        text("""
                            INSERT INTO artist_url (artist_id, type, url)
                            VALUES (:artist_id, :type, :url)
                            ON CONFLICT (artist_id, type) DO NOTHING
                        """),
                        {"artist_id": artist_id, "type": url_rel["type"], "url": url_rel["url"]},
                    )

                saved += 1
        except SQLAlchemyError as e:
            logger.error("아티스트 저장 실패 — 건너뜀: mbid=%s, 오류=%s", artist["mbid"], e)

    logger.info("아티스트 저장 완료: %d / %d건 처리", saved, len(artists))


def upsert_artist_url(artist_id: int, url_type: str, url: str) -> None:
    """artist_url에 (artist_id, type) 신규 저장. 이미 존재하면 무시."""
    with get_session() as session:
        session.execute(
            text("""
                INSERT INTO artist_url (artist_id, type, url)
                VALUES (:artist_id, :type, :url)
                ON CONFLICT (artist_id, type) DO NOTHING
            """),
            {"artist_id": artist_id, "type": url_type, "url": url},
        )


def save_releases(artist_id: int, releases: list[dict]) -> None:
    """수집된 릴리즈 목록을 DB에 저장한다. release_group 단위 독립 트랜잭션으로 격리."""
    saved = 0

    for release in releases:
        try:
            with get_session() as session:
                rg_row = session.execute(
                    text("""
                        INSERT INTO release_group
                            (spotify_id, artist_id, title, type,
                             first_release_date, cover_url, label, total_tracks)
                        VALUES
                            (:spotify_id, :artist_id, :title, :type,
                             :first_release_date, :cover_url, :label, :total_tracks)
                        ON CONFLICT (spotify_id) DO UPDATE SET
                            title            = EXCLUDED.title,
                            type             = EXCLUDED.type,
                            first_release_date = EXCLUDED.first_release_date,
                            cover_url        = EXCLUDED.cover_url,
                            label            = EXCLUDED.label,
                            total_tracks     = EXCLUDED.total_tracks
                        RETURNING id
                    """),
                    {
                        "spotify_id": release["spotify_id"],
                        "artist_id": artist_id,
                        "title": release["title"],
                        "type": release["type"],
                        "first_release_date": release["first_release_date"],
                        "cover_url": release["cover_url"],
                        "label": release.get("label"),
                        "total_tracks": release.get("total_tracks"),
                    },
                ).fetchone()

                if release.get("tracks") and rg_row:
                    rg_id = rg_row[0]
                    for track in release["tracks"]:
                        session.execute(
                            text("""
                                INSERT INTO track
                                    (release_group_id, spotify_id, title,
                                     position, disc_number, length_ms, explicit)
                                VALUES
                                    (:release_group_id, :spotify_id, :title,
                                     :position, :disc_number, :length_ms, :explicit)
                                ON CONFLICT (spotify_id) DO NOTHING
                            """),
                            {
                                "release_group_id": rg_id,
                                "spotify_id": track["spotify_id"],
                                "title": track["title"],
                                "position": track["position"],
                                "disc_number": track.get("disc_number"),
                                "length_ms": track.get("length_ms"),
                                "explicit": track.get("explicit", False),
                            },
                        )
            saved += 1
        except SQLAlchemyError as e:
            logger.error(
                "릴리즈 저장 실패 — 건너뜀: spotify_id=%s, %s", release.get("spotify_id"), e
            )

    logger.info("릴리즈 저장 완료: %d / %d건 처리", saved, len(releases))


def save_concerts(concerts: list[dict], use_prfstate: bool = False) -> None:
    """수집된 공연 목록을 concert 테이블에 저장한다. kopis_id 중복 시 무시.

    use_prfstate=True이면 prfstate → _KOPIS_STATUS_MAP으로 status를 결정한다.
    기본값(False)은 배치 수집용 PENDING을 사용한다.
    """
    saved = 0
    for concert in concerts:
        try:
            with get_session() as session:
                status = (
                    _KOPIS_STATUS_MAP.get(concert.get("prfstate"), "PENDING")
                    if use_prfstate
                    else "PENDING"
                )
                new_row = session.execute(
                    text("""
                        INSERT INTO concert
                            (kopis_id, title, "cast", start_date, end_date,
                             venue_name, poster_url, price, status, kopis_update_date,
                             ticket_open_at)
                        VALUES
                            (:kopis_id, :title, :cast, :start_date, :end_date,
                             :venue_name, :poster_url, :price,
                             :status, :kopis_update_date,
                             NULL)
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
                        "poster_url": concert.get("poster_url"),
                        "price": concert.get("price"),
                        "status": status,
                        "kopis_update_date": concert["updatedate"],
                    },
                ).fetchone()

                if new_row is not None:
                    concert_id = new_row[0]
                    for position, url in enumerate(concert.get("still_urls", [])):
                        session.execute(
                            text("""
                                INSERT INTO concert_image (concert_id, url, position)
                                VALUES (:concert_id, :url, :position)
                            """),
                            {"concert_id": concert_id, "url": url, "position": position},
                        )
                    row = new_row
                else:
                    row = session.execute(
                        text("SELECT id FROM concert WHERE kopis_id = :kopis_id"),
                        {"kopis_id": concert["kopis_id"]},
                    ).fetchone()

                if row and concert.get("relates"):
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
                saved += 1
        except SQLAlchemyError as e:
            logger.error("공연 저장 실패 — 건너뜀: kopis_id=%s, 오류=%s", concert["kopis_id"], e)
    logger.info("공연 저장 완료: %d / %d건 처리", saved, len(concerts))


def get_completed_concerts() -> list[dict]:
    """setlist 미수집·미시도(또는 7일 경과) 공연완료 건을 아티스트 MBID와 함께 반환한다."""
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT DISTINCT c.id AS concert_id, c.title, c.start_date, c.end_date,
                                a.mbid AS artist_mbid
                FROM concert c
                JOIN concert_artist ca ON ca.concert_id = c.id
                JOIN artist a ON a.id = ca.artist_id
                LEFT JOIN setlist s ON s.concert_id = c.id
                WHERE c.status = 'ENDED'
                  AND s.id IS NULL
                  AND (
                      c.fetch_attempted_at IS NULL
                      OR c.fetch_attempted_at < NOW() - INTERVAL '7 days'
                  )
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
    """매칭에 사용할 모든 아티스트 alias를 반환한다. artist.name도 포함."""
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT artist_id, name FROM artist_alias
                UNION
                SELECT id AS artist_id, name FROM artist
            """)
        ).fetchall()
    return [{"artist_id": row[0], "name": row[1]} for row in rows]


def get_all_artist_mbids() -> list[str]:
    """DB에 저장된 모든 아티스트 MBID를 반환한다."""
    with get_session() as session:
        rows = session.execute(text("SELECT mbid FROM artist")).fetchall()
    return [row[0] for row in rows]


def get_all_artists() -> list[dict]:
    """Wikipedia 수집용 아티스트 목록 (artist_id, name)을 반환한다."""
    with get_session() as session:
        rows = session.execute(text("SELECT id, name FROM artist")).fetchall()
    return [{"artist_id": row[0], "name": row[1]} for row in rows]


def get_artists_without_ko_alias() -> list[dict]:
    """artist_alias에 locale='ko' 행이 없는 아티스트 목록 (artist_id, name)을 반환한다."""
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT a.id AS artist_id, a.name
                FROM artist a
                WHERE NOT EXISTS (
                    SELECT 1 FROM artist_alias aa
                    WHERE aa.artist_id = a.id AND aa.locale = 'ko'
                )
            """)
        ).fetchall()
    return [{"artist_id": row[0], "name": row[1]} for row in rows]


def save_aliases(aliases: list[dict]) -> None:
    """외부 소스에서 수집된 alias를 artist_alias 테이블에 저장한다. 중복 시 무시.

    aliases: [{"artist_id": int, "name": str, "locale": str}]
    """
    saved = 0
    with get_session() as session:
        for alias in aliases:
            try:
                session.execute(
                    text("""
                        INSERT INTO artist_alias (artist_id, name, locale)
                        VALUES (:artist_id, :name, :locale)
                        ON CONFLICT (artist_id, name) DO NOTHING
                    """),
                    {
                        "artist_id": alias["artist_id"],
                        "name": alias["name"],
                        "locale": alias["locale"],
                    },
                )
                saved += 1
            except SQLAlchemyError as e:
                logger.error(
                    "alias 저장 실패 — 건너뜀: artist_id=%s, name=%s, 오류=%s",
                    alias["artist_id"], alias["name"], e,
                )
    logger.info("alias 저장 완료: %d / %d건 처리", saved, len(aliases))


def get_matched_artist_mbids() -> list[str]:
    """매칭이 있는 아티스트 MBID를 반환한다."""
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT DISTINCT a.mbid
                FROM artist a
                JOIN concert_artist ca ON ca.artist_id = a.id
            """)
        ).fetchall()
    return [row[0] for row in rows]


def get_matched_artists_with_spotify() -> list[dict]:
    """매칭이 있는 아티스트 중 Spotify URL을 보유한 목록을 반환한다."""
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT DISTINCT a.id, au.url
                FROM artist a
                JOIN concert_artist ca ON ca.artist_id = a.id
                JOIN artist_url au ON au.artist_id = a.id
                WHERE au.url LIKE '%open.spotify.com/artist/%'
            """)
        ).fetchall()
    return [{"artist_id": row[0], "spotify_url": row[1]} for row in rows]


def get_all_artists_with_spotify() -> list[dict]:
    """Spotify URL을 보유한 모든 아티스트 목록을 반환한다."""
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT DISTINCT ON (a.id) a.id, au.url
                FROM artist a
                JOIN artist_url au ON au.artist_id = a.id
                WHERE au.url LIKE '%open.spotify.com/artist/%'
                ORDER BY a.id
            """)
        ).fetchall()
    return [{"artist_id": row[0], "spotify_url": row[1]} for row in rows]


def get_artists_without_releases() -> list[dict]:
    """내한 공연 매칭 아티스트 중 Spotify URL을 보유하지만 릴리즈가 없는 목록을 반환한다."""
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT DISTINCT ON (a.id) a.id, au.url AS spotify_url
                FROM artist a
                JOIN concert_artist ca ON ca.artist_id = a.id
                JOIN artist_url au ON au.artist_id = a.id
                    AND au.url LIKE '%open.spotify.com/artist/%'
                LEFT JOIN release_group rg ON rg.artist_id = a.id
                WHERE rg.id IS NULL
                ORDER BY a.id
            """)
        ).fetchall()
    return [{"artist_id": row[0], "spotify_url": row[1]} for row in rows]


def get_existing_release_spotify_ids(artist_id: int) -> set:
    """특정 아티스트의 이미 수집된 릴리즈 spotify_id 집합을 반환한다."""
    with get_session() as session:
        rows = session.execute(
            text("SELECT spotify_id FROM release_group WHERE artist_id = :artist_id"),
            {"artist_id": artist_id},
        ).fetchall()
    return {row[0] for row in rows}


def get_artist_by_mbid(mbid: str) -> Optional[dict]:
    """mbid로 아티스트 id·name·spotify_url을 반환한다. 없으면 None."""
    with get_session() as session:
        row = session.execute(
            text("""
                SELECT DISTINCT ON (a.id) a.id, a.name, au.url AS spotify_url
                FROM artist a
                LEFT JOIN artist_url au ON au.artist_id = a.id AND au.type = 'Spotify'
                WHERE a.mbid = :mbid
                ORDER BY a.id
                LIMIT 1
            """),
            {"mbid": mbid},
        ).fetchone()
    if row is None:
        return None
    return {"id": row[0], "name": row[1], "spotify_url": row[2]}


def get_artists_without_image() -> list[dict]:
    """image_url이 없는 artist의 id·mbid·name·spotify_url 목록을 반환한다."""
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT DISTINCT ON (a.id) a.id, a.mbid, a.name, au.url AS spotify_url
                FROM artist a
                LEFT JOIN artist_url au ON au.artist_id = a.id AND au.type = 'Spotify'
                WHERE a.image_url IS NULL AND a.mbid IS NOT NULL
                ORDER BY a.id
            """)
        ).fetchall()
    return [{"id": row[0], "mbid": row[1], "name": row[2], "spotify_url": row[3]} for row in rows]


def update_artist_image(artist_id: int, image_url: str) -> None:
    """artist의 image_url을 갱신한다."""
    with get_session() as session:
        session.execute(
            text("UPDATE artist SET image_url = :image_url WHERE id = :id"),
            {"image_url": image_url, "id": artist_id},
        )


def get_spotify_album_total(artist_id: int) -> Optional[int]:
    """artist.spotify_album_total을 반환한다. NULL이면 None 반환."""
    with get_session() as session:
        row = session.execute(
            text("SELECT spotify_album_total FROM artist WHERE id = :id"),
            {"id": artist_id},
        ).fetchone()
    if row is None:
        return None
    return row[0]


def update_spotify_album_total(artist_id: int, total: int) -> None:
    """artist.spotify_album_total을 갱신한다."""
    with get_session() as session:
        session.execute(
            text("UPDATE artist SET spotify_album_total = :total WHERE id = :id"),
            {"total": total, "id": artist_id},
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
    """concert_artist 매칭이 없는 공연을 반환한다. EXCLUDED 상태 공연은 제외한다."""
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT c.id AS concert_id, c.title, c."cast"
                FROM concert c
                LEFT JOIN concert_artist ca ON ca.concert_id = c.id
                WHERE ca.concert_id IS NULL
                  AND c.status != 'EXCLUDED'
            """)
        ).fetchall()
    return [{"concert_id": row[0], "title": row[1], "cast": row[2]} for row in rows]


def save_concert_artists(matches: list[dict]) -> None:
    """매칭 결과를 concert_artist 테이블에 저장한다."""
    with get_session() as session:
        for match in matches:
            session.execute(
                text("""
                    INSERT INTO concert_artist (concert_id, artist_id)
                    VALUES (:concert_id, :artist_id)
                    ON CONFLICT (concert_id, artist_id) DO NOTHING
                """),
                {
                    "concert_id": match["concert_id"],
                    "artist_id": match["artist_id"],
                },
            )
    logger.info("공연-아티스트 매칭 저장 완료: %d건 처리", len(matches))


def save_concert_artist_candidates(matches: list[dict]) -> None:
    """자동 매칭 결과를 concert_artist_candidate 테이블에 저장한다. 중복 시 무시."""
    with get_session() as session:
        for match in matches:
            session.execute(
                text("""
                    INSERT INTO concert_artist_candidate
                        (concert_id, artist_id, matched_by)
                    VALUES (:concert_id, :artist_id, :matched_by)
                    ON CONFLICT (concert_id, artist_id) DO NOTHING
                """),
                {
                    "concert_id": match["concert_id"],
                    "artist_id": match["artist_id"],
                    "matched_by": match.get("matched_by", "title"),
                },
            )
    logger.info("공연-아티스트 후보 저장 완료: %d건 처리", len(matches))



def update_artist_is_coming() -> int:
    """오늘 이후 공연 보유 여부에 따라 artist.is_coming을 갱신한다.

    EXCLUDED 상태 공연은 제외한다.
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
                                 AND c.status NOT IN ('EXCLUDED', 'PENDING')
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


def get_active_concerts() -> list[dict]:
    """status가 UPCOMING 또는 ONGOING인 공연의 kopis_id·kopis_update_date를 반환한다."""
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT kopis_id, kopis_update_date
                FROM concert
                WHERE status IN ('UPCOMING', 'ONGOING')
            """)
        ).fetchall()
    return [
        {"kopis_id": row[0], "kopis_update_date": str(row[1]) if row[1] else None}
        for row in rows
    ]


def get_existing_kopis_ids() -> set:
    """DB에 저장된 모든 concert.kopis_id를 집합으로 반환한다."""
    with get_session() as session:
        rows = session.execute(text("SELECT kopis_id FROM concert")).fetchall()
    return {row[0] for row in rows}


def update_concert_fetch_attempted(concert_id: int) -> None:
    """concert.fetch_attempted_at을 현재 시각으로 갱신한다."""
    with get_session() as session:
        session.execute(
            text("UPDATE concert SET fetch_attempted_at = NOW() WHERE id = :id"),
            {"id": concert_id},
        )


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
                        "status": _KOPIS_STATUS_MAP.get(concert["prfstate"], "PENDING"),
                        "kopis_update_date": concert["updatedate"],
                        "kopis_id": concert["kopis_id"],
                    },
                )
                updated += 1

    logger.info("공연 상태 갱신 완료: %d건 변경", updated)
