from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

_HIRAGANA_RANGE = range(0x3040, 0x30A0)
_KATAKANA_RANGE = range(0x30A0, 0x3100)
_KANJI_RANGE = range(0x4E00, 0xA000)

_JONG_N = 4  # 종성 ㄴ (KS X 1001 종성 인덱스)
_JONG_S = 19  # 종성 ㅅ

# 청음(무성 파열음/파찰음) 계열: 어두=예사소리, 어중=거센소리로 갈라 적는다 (표기법 세칙).
# 그 외 계열(탁음·비음·유음·마찰음 등)은 위치와 무관하게 고정 표기.
_ALTERNATING = {
    "ka": ("가", "카"), "ki": ("기", "키"), "ku": ("구", "쿠"),
    "ke": ("게", "케"), "ko": ("고", "코"),
    "kya": ("갸", "캬"), "kyu": ("규", "큐"), "kyo": ("교", "쿄"),
    "ta": ("다", "타"), "te": ("데", "테"), "to": ("도", "토"),
    "chi": ("지", "치"),
    "cha": ("자", "차"), "chu": ("주", "추"), "cho": ("조", "초"),
}
_FIXED = {
    "a": "아", "i": "이", "u": "우", "e": "에", "o": "오",
    "ga": "가", "gi": "기", "gu": "구", "ge": "게", "go": "고",
    "gya": "갸", "gyu": "규", "gyo": "교",
    "sa": "사", "shi": "시", "su": "스", "se": "세", "so": "소",
    "sha": "샤", "shu": "슈", "sho": "쇼",
    "za": "자", "ji": "지", "zu": "즈", "ze": "제", "zo": "조",
    "ja": "자", "ju": "주", "jo": "조",
    "tsu": "쓰",
    "da": "다", "de": "데", "do": "도",
    "na": "나", "ni": "니", "nu": "누", "ne": "네", "no": "노",
    "nya": "냐", "nyu": "뉴", "nyo": "뇨",
    "ha": "하", "hi": "히", "fu": "후", "he": "헤", "ho": "호",
    "hya": "햐", "hyu": "휴", "hyo": "효",
    "ba": "바", "bi": "비", "bu": "부", "be": "베", "bo": "보",
    "bya": "뱌", "byu": "뷰", "byo": "뵤",
    "pa": "파", "pi": "피", "pu": "푸", "pe": "페", "po": "포",
    "pya": "퍄", "pyu": "퓨", "pyo": "표",
    "ma": "마", "mi": "미", "mu": "무", "me": "메", "mo": "모",
    "mya": "먀", "myu": "뮤", "myo": "묘",
    "ya": "야", "yu": "유", "yo": "요",
    "ra": "라", "ri": "리", "ru": "루", "re": "레", "ro": "로",
    "rya": "랴", "ryu": "류", "ryo": "료",
    "wa": "와", "wo": "오",
}
_SOKUON_PREFIXES = ("kk", "ss", "tt", "pp", "cch", "tch")
_NON_ROMAJI_RE = re.compile(r"[^a-z0-9\s]")


def _is_japanese_script(text: str) -> bool:
    """가나(히라가나·가타카나) 또는 한자가 하나라도 포함되어 있으면 True."""
    return any(
        ord(c) in _HIRAGANA_RANGE or ord(c) in _KATAKANA_RANGE or ord(c) in _KANJI_RANGE
        for c in text
    )


def _add_batchim(syllable: str, jong: int) -> str:
    """완성형 한글 음절에 종성을 붙인다. 종성이 이미 있거나 한글이 아니면 그대로 반환한다."""
    if len(syllable) != 1:
        return syllable
    code = ord(syllable) - 0xAC00
    if not (0 <= code < 11172) or code % 28 != 0:
        return syllable
    return chr(0xAC00 + code + jong)


def _match_mora(word: str, pos: int) -> Optional[tuple]:
    """word[pos:]에서 가장 긴 모라를 찾아 (음소 키, 소비한 길이)를 반환한다. 실패 시 None."""
    for length in (3, 2, 1):
        chunk = word[pos:pos + length]
        if chunk in _ALTERNATING or chunk in _FIXED:
            return chunk, length
    return None


def _romanize_stream(text: str) -> Optional[str]:
    """공백 포함 로마자 문자열 전체를 하나의 연속된 발화로 보고 한글로 변환한다.

    성-이름처럼 공백으로 나뉜 이름이라도 파열음 예사소리/거센소리 규칙은
    전체 이름 첫 음절에서만 "어두"로 취급하고 이후는 공백을 건너 "어중"으로
    이어진다 (예: Fujii Kaze → 후지이 카제, 공백 뒤에서도 거센소리 유지).
    인식 불가 문자가 있으면 None.
    """
    syllables: list = []
    word_initial = True
    pos = 0
    n = len(text)

    while pos < n:
        if text[pos] == " ":
            syllables.append(" ")
            pos += 1
            continue

        # 숫자(그룹명에 붙는 46, 96 등)는 발음 변환 없이 그대로 통과시킨다.
        if text[pos].isdigit():
            start = pos
            while pos < n and text[pos].isdigit():
                pos += 1
            syllables.append(text[start:pos])
            continue

        # 촉음(っ, 자음 중복 표기) — 앞 음절에 받침 ㅅ을 붙이고 중복 자음 하나만 소비한다.
        sokuon_prefix = next((p for p in _SOKUON_PREFIXES if text.startswith(p, pos)), None)
        if sokuon_prefix is not None:
            if not syllables or syllables[-1] == " ":
                return None
            syllables[-1] = _add_batchim(syllables[-1], _JONG_S)
            pos += 1
            continue

        # 발음(ん, 받침 비음) — 뒤에 모음/야행이 이어지지 않는 단독 n만 해당.
        if text[pos] == "n":
            next_char = text[pos + 1] if pos + 1 < n else ""
            if not next_char or next_char not in "aiueoy":
                if not syllables or syllables[-1] == " ":
                    return None
                syllables[-1] = _add_batchim(syllables[-1], _JONG_N)
                word_initial = False
                pos += 1
                continue

        matched = _match_mora(text, pos)
        if matched is None:
            return None
        key, length = matched
        if key in _ALTERNATING:
            initial_form, medial_form = _ALTERNATING[key]
            syllables.append(initial_form if word_initial else medial_form)
        else:
            syllables.append(_FIXED[key])
        word_initial = False
        pos += length

    return "".join(syllables) if any(s != " " for s in syllables) else None


def romanize_to_korean(sort_name: str) -> Optional[str]:
    """MusicBrainz sort_name(로마자)을 일본어 외래어 표기법 규칙으로 한글 변환한다.

    "Yonezu, Kenshi" 같은 "성, 이름" 형식은 콤마만 제거해 원래 순서(성-이름)를 유지한다.
    변환 규칙표에 없는 문자가 하나라도 있으면 전체를 포기하고 None을 반환한다
    (부분적으로 틀린 표기를 저장하지 않기 위함).
    """
    if not sort_name:
        return None

    # 하이픈은 단어 구분이 아니라 모라 경계 표시(예: "Ko-en")이므로 공백 대신 삭제로 처리한다.
    normalized = sort_name.replace(",", " ").replace("-", "").lower()
    normalized = _NON_ROMAJI_RE.sub(" ", normalized)
    cleaned = " ".join(normalized.split())
    if not cleaned:
        return None

    converted = _romanize_stream(cleaned)
    if converted is None:
        logger.debug("로마자 변환 실패 — 인식 불가 문자 포함: sort_name=%s", sort_name)
    return converted


def collect_ko_aliases(artists: list[dict]) -> list[dict]:
    """artist_id/name/sort_name 목록을 받아 변환 가능한 아티스트만 ko alias로 반환한다.

    artists: [{"artist_id": int, "name": str, "sort_name": str}]
    반환: [{"artist_id": int, "name": str, "locale": "ko"}]

    name에 가나·한자가 없는 경우(이미 로마자 표기된 그룹명 등)는 원본 그대로도
    매칭에 활용 가능하다고 보고 변환 대상에서 제외한다.
    """
    result: list[dict] = []
    for artist in artists:
        name = artist.get("name") or ""
        if not _is_japanese_script(name):
            continue
        converted = romanize_to_korean(artist.get("sort_name") or "")
        if converted:
            result.append({"artist_id": artist["artist_id"], "name": converted, "locale": "ko"})

    logger.info("로마자→한글 alias 변환 완료: %d / %d건", len(result), len(artists))
    return result
