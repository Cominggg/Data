import logging
import re
from typing import Optional

from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

_CAST_SEP = re.compile(r"[,·&×・/]")
_FEAT_RE = re.compile(r"\b(?:featuring|feat|ft)\.?\s*", re.IGNORECASE)
_FUZZY_THRESHOLD = 85
_MIN_ALIAS_LEN = 3  # cast 및 title 매칭 공통 최소 길이


def _split_cast(cast: str) -> list[str]:
    cleaned = _FEAT_RE.sub(",", cast)
    return [name.strip() for name in _CAST_SEP.split(cleaned) if name.strip()]


def _exact_match(name: str, alias_map: dict) -> Optional[dict]:
    return alias_map.get(name.lower())


def _fuzzy_match(text: str, aliases: list[dict]) -> Optional[dict]:
    best_score = 0
    best_alias = None
    text_lower = text.lower()
    for alias in aliases:
        if len(alias["name"]) < _MIN_ALIAS_LEN:
            continue
        score = fuzz.token_set_ratio(text_lower, alias["name"].lower())
        if score > best_score:
            best_score = score
            best_alias = alias
    if best_score >= _FUZZY_THRESHOLD:
        return best_alias
    return None


def _phrase_match_title(title: str, aliases: list[dict]) -> Optional[dict]:
    """제목 내 구문 일치 기반 매칭 (HIGH confidence 전용).

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
    cast = concert_raw.get("prfcast") or ""
    title = concert_raw.get("prfnm") or ""
    alias_map = {a["name"].lower(): a for a in aliases}

    for name in _split_cast(cast):
        if _exact_match(name, alias_map) or _fuzzy_match(name, aliases):
            return True
    return bool(_phrase_match_title(title, aliases))


def match_concert(concert: dict, aliases: list[dict]) -> tuple[list[dict], list[dict]]:
    """공연-아티스트 매칭 실행.

    매칭 ①: cast 각 이름 → alias 완전 일치 → confidence=HIGH
    매칭 ②: cast 각 이름 → rapidfuzz token_set_ratio ≥ 85 → confidence=LOW
    매칭 ③: title → 구문 일치(단어 경계 or 구문 포함) → confidence=HIGH (cast 전체 실패 시 폴백)

    concert: {"concert_id": int, "title": str, "cast": str | None}
    aliases: [{"artist_id": int, "name": str}]
    Returns: (matches, failures)
    """
    concert_id = concert["concert_id"]
    cast = concert.get("cast") or ""
    title = concert.get("title") or ""
    matches = []
    matched_ids: set = set()
    alias_map = {a["name"].lower(): a for a in aliases}

    for artist_name in _split_cast(cast):
        alias = _exact_match(artist_name, alias_map)
        if alias and alias["artist_id"] not in matched_ids:
            matches.append({
                "concert_id": concert_id,
                "artist_id": alias["artist_id"],
                "confidence": "HIGH",
                "matched_by": "prfcast",
            })
            matched_ids.add(alias["artist_id"])
            logger.debug("HIGH 매칭(cast): concert_id=%s, artist_id=%s, name=%s", concert_id, alias["artist_id"], artist_name)
            continue

        alias = _fuzzy_match(artist_name, aliases)
        if alias and alias["artist_id"] not in matched_ids:
            matches.append({
                "concert_id": concert_id,
                "artist_id": alias["artist_id"],
                "confidence": "LOW",
                "matched_by": "prfcast",
            })
            matched_ids.add(alias["artist_id"])
            logger.debug("LOW(cast) 매칭: concert_id=%s, artist_id=%s, name=%s", concert_id, alias["artist_id"], artist_name)

    if not matches:
        alias = _phrase_match_title(title, aliases)
        if alias:
            matches.append({
                "concert_id": concert_id,
                "artist_id": alias["artist_id"],
                "confidence": "HIGH",
                "matched_by": "prfnm",
            })
            logger.debug("HIGH 매칭(title): concert_id=%s, artist_id=%s, title=%s", concert_id, alias["artist_id"], title)

    if not matches:
        logger.debug("매칭 실패: concert_id=%s", concert_id)
        return [], [{"concert_id": concert_id}]

    return matches, []
