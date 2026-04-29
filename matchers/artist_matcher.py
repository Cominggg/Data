import logging
import re

logger = logging.getLogger(__name__)

_CAST_SEP = re.compile(r"[,·]")


def _split_cast(cast: str) -> list[str]:
    return [name.strip() for name in _CAST_SEP.split(cast) if name.strip()]


def _exact_match(name: str, aliases: list[dict]) -> dict | None:
    name_lower = name.lower()
    for alias in aliases:
        if alias["name"].lower() == name_lower:
            return alias
    return None


def match_concert(concert: dict, aliases: list[dict]) -> tuple[list[dict], list[dict]]:
    """공연-아티스트 매칭 실행. cast alias 완전 일치(HIGH) 매칭만 수행.

    concert: {"concert_id": int, "title": str, "cast": str | None}
    aliases: [{"artist_id": int, "name": str}]
    Returns: (matches, failures)
    """
    concert_id = concert["concert_id"]
    cast = concert.get("cast") or ""
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
        return [], [{"concert_id": concert_id}]

    return matches, []
