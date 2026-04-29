import logging
import re
from typing import Optional

from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

_CAST_SEP = re.compile(r"[,·]")
_FUZZY_THRESHOLD = 85


def _split_cast(cast: str) -> list[str]:
    return [name.strip() for name in _CAST_SEP.split(cast) if name.strip()]


def _exact_match(name: str, aliases: list[dict]) -> Optional[dict]:
    name_lower = name.lower()
    for alias in aliases:
        if alias["name"].lower() == name_lower:
            return alias
    return None


def _fuzzy_match(text: str, aliases: list[dict]) -> Optional[dict]:
    best_score = 0
    best_alias = None
    text_lower = text.lower()
    for alias in aliases:
        score = fuzz.partial_ratio(text_lower, alias["name"].lower())
        if score > best_score:
            best_score = score
            best_alias = alias
    if best_score >= _FUZZY_THRESHOLD:
        return best_alias
    return None


def match_concert(concert: dict, aliases: list[dict]) -> tuple[list[dict], list[dict]]:
    """공연-아티스트 매칭 실행.

    매칭 ①: cast → alias 완전 일치 → confidence=HIGH
    매칭 ②: title → rapidfuzz partial_ratio ≥ 85 → confidence=LOW
    둘 다 실패 시 review_queue 등록용 failures 반환.

    concert: {"concert_id": int, "title": str, "cast": str | None}
    aliases: [{"artist_id": int, "name": str}]
    Returns: (matches, failures)
    """
    concert_id = concert["concert_id"]
    cast = concert.get("cast") or ""
    title = concert.get("title") or ""
    matches = []

    for artist_name in _split_cast(cast):
        alias = _exact_match(artist_name, aliases)
        if alias:
            matches.append({
                "concert_id": concert_id,
                "artist_id": alias["artist_id"],
                "confidence": "HIGH",
                "matched_by": "prfcast",
            })
            logger.debug("HIGH 매칭: concert_id=%s, artist_id=%s, name=%s", concert_id, alias["artist_id"], artist_name)

    if not matches:
        alias = _fuzzy_match(title, aliases)
        if alias:
            matches.append({
                "concert_id": concert_id,
                "artist_id": alias["artist_id"],
                "confidence": "LOW",
                "matched_by": "prfnm",
            })
            logger.debug("LOW 매칭: concert_id=%s, artist_id=%s, title=%s", concert_id, alias["artist_id"], title)

    if not matches:
        logger.debug("매칭 실패: concert_id=%s", concert_id)
        return [], [{"concert_id": concert_id}]

    return matches, []
