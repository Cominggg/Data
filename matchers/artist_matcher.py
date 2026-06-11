import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

_MIN_ALIAS_LEN = 3


def _phrase_match_title(title: str, aliases: list[dict]) -> Optional[dict]:
    """제목 내 구문 일치 기반 매칭.

    단일 단어 alias: 제목을 단어 집합으로 분리 후 exact match.
    다중 단어 alias: 제목 내 구문 포함 여부 확인.
    가장 긴 매칭 alias를 반환해 특이도를 최대화한다.
    """
    title_lower = title.lower()
    title_tokens = set(re.split(r"\W+", title_lower))
    best: Optional[dict] = None
    for alias in aliases:
        name = alias["name"]
        if len(name) < _MIN_ALIAS_LEN:
            continue
        name_lower = name.lower()
        matched = (
            name_lower in title_tokens          # 단일 단어: 단어 경계 exact
            if " " not in name_lower
            else name_lower in title_lower      # 다중 단어: 구문 포함
        )
        if matched and (best is None or len(name) > len(best["name"])):
            best = alias
    return best


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

    alias = _phrase_match_title(title, aliases)
    if alias:
        logger.debug(
            "매칭(title): concert_id=%s, artist_id=%s, title=%s",
            concert_id, alias["artist_id"], title,
        )
        match = {"concert_id": concert_id, "artist_id": alias["artist_id"], "matched_by": "title"}
        return [match], []

    logger.debug("매칭 실패: concert_id=%s", concert_id)
    return [], [{"concert_id": concert_id}]
