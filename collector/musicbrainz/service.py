import logging

from sqlalchemy.orm import Session

from collector.db.repositories.artist_repo import upsert_artist
from collector.musicbrainz.client import MusicBrainzClient
from collector.musicbrainz.models import ArtistResult

logger = logging.getLogger(__name__)

_JPOP_TAGS = {"j-pop", "japanese", "j-rock", "anime", "visual kei"}


def _is_jpop_artist(artist: ArtistResult) -> bool:
    """태그 기준으로 JPOP 아티스트인지 판별한다."""
    return bool(_JPOP_TAGS & {tag.lower() for tag in artist.tags})


def collect_jpop_artists(
    session: Session,
    client: MusicBrainzClient,
    query: str = "tag:j-pop",
    limit: int = 25,
    max_pages: int = 10,
) -> int:
    """JPOP 아티스트를 검색해 DB에 저장하고 저장된 건수를 반환한다."""
    saved = 0
    for page in range(max_pages):
        offset = page * limit
        logger.info("MusicBrainz 아티스트 검색 page=%d offset=%d", page, offset)
        data = client.search_artists(query=query, limit=limit, offset=offset)

        artists = data.get("artists", [])
        if not artists:
            logger.info("더 이상 결과 없음. 종료.")
            break

        for raw in artists:
            artist = ArtistResult.from_api_response(raw)
            upsert_artist(session, artist.to_db_dict())
            saved += 1
            logger.info("저장: %s (%s)", artist.name, artist.mbid)

    return saved
