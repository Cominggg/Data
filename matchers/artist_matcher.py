import logging
import re

logger = logging.getLogger(__name__)

_MIN_ALIAS_LEN = 2


def _normalize(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def _phrase_match_title(title: str, aliases: list[dict]) -> list[dict]:
    """제목 내 구문 일치 기반 매칭.

    단일 단어 alias: 정규화된 title token set에서 exact match.
    다중 단어 alias: 공백 padding 기반 구문 포함 검사 (단어 경계 보장).
    artist_id별 가장 긴 매칭 alias를 반환해 특이도를 최대화하며, 복수 아티스트 모두 반환한다.
    """
    title_norm = _normalize(title)
    title_tokens = set(title_norm.split())
    title_padded = f" {title_norm} "
    best_per_artist: dict = {}
    for alias in aliases:
        name = alias["name"]
        if len(re.sub(r"\W", "", name)) < _MIN_ALIAS_LEN:
            continue
        name_norm = _normalize(name)
        name_words = name_norm.split()
        matched = (
            name_norm in title_tokens                       # 단일 단어: token exact
            if len(name_words) == 1
            else f" {name_norm} " in title_padded           # 다중 단어: 단어 경계 구문 포함
        )
        if matched:
            artist_id = alias["artist_id"]
            if artist_id not in best_per_artist or len(name) > len(
                best_per_artist[artist_id]["name"]
            ):
                best_per_artist[artist_id] = alias
    return list(best_per_artist.values())


def has_match(concert_raw: dict, aliases: list[dict]) -> bool:
    """KOPIS 원시 공연 데이터가 alias와 매칭되는지 확인 (저장 전 필터링용)."""
    title = concert_raw.get("prfnm") or ""
    return bool(_phrase_match_title(title, aliases))


def match_concert(concert: dict, aliases: list[dict]) -> tuple[list[dict], list[dict]]:
    """공연-아티스트 매칭 실행.

    공연명(title) 구문 일치(단어 경계 or 구문 포함)로 매칭한다.

    concert: {"concert_id": int, "title": str}
    aliases: [{"artist_id": int, "name": str}]
    Returns: (matches, failures)
    """
    concert_id = concert["concert_id"]
    title = concert.get("title") or ""

    matched_aliases = _phrase_match_title(title, aliases)
    if matched_aliases:
        for alias in matched_aliases:
            logger.debug(
                "매칭(title): concert_id=%s, artist_id=%s, title=%s",
                concert_id, alias["artist_id"], title,
            )
        matches = [
            {"concert_id": concert_id, "artist_id": alias["artist_id"], "matched_by": "title"}
            for alias in matched_aliases
        ]
        return matches, []

    logger.debug("매칭 실패: concert_id=%s", concert_id)
    return [], [{"concert_id": concert_id}]
