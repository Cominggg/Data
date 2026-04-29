import pytest

from matchers.artist_matcher import match_concert

_ALIASES = [
    {"artist_id": 1, "name": "아이유"},
    {"artist_id": 2, "name": "BTS"},
    {"artist_id": 3, "name": "NewJeans"},
]


class TestAliasExactMatch:
    def test_exact_alias_match_returns_high_confidence(self):
        """prfcast → alias 완전 일치 시 confidence=HIGH를 반환해야 한다."""
        concert = {"concert_id": 10, "title": "콘서트", "cast": "아이유"}
        matches, failures = match_concert(concert, _ALIASES)

        assert len(matches) == 1
        assert matches[0]["confidence"] == "HIGH"

    def test_exact_match_does_not_require_approval(self):
        """HIGH 매칭은 matched_by=prfcast이어야 한다."""
        concert = {"concert_id": 10, "title": "콘서트", "cast": "아이유"}
        matches, _ = match_concert(concert, _ALIASES)

        assert matches[0]["matched_by"] == "prfcast"
        assert matches[0]["artist_id"] == 1

    def test_multi_artist_cast_matched_individually(self):
        """prfcast에 ',' 또는 '·' 구분자로 여러 아티스트가 있을 때 각각 개별 매칭되어야 한다."""
        concert = {"concert_id": 10, "title": "합동 공연", "cast": "아이유·BTS"}
        matches, failures = match_concert(concert, _ALIASES)

        assert len(matches) == 2
        assert failures == []
        matched_ids = {m["artist_id"] for m in matches}
        assert matched_ids == {1, 2}

    def test_comma_separator_splits_cast(self):
        """',' 구분자로도 복수 아티스트가 분리되어야 한다."""
        concert = {"concert_id": 11, "title": "합동", "cast": "아이유,NewJeans"}
        matches, _ = match_concert(concert, _ALIASES)

        assert len(matches) == 2


class TestFuzzyMatch:
    def test_partial_ratio_above_threshold_returns_low_confidence(self):
        """rapidfuzz partial_ratio >= 85이면 confidence=LOW를 반환해야 한다."""
        concert = {"concert_id": 20, "title": "BTS World Tour 콘서트", "cast": ""}
        matches, failures = match_concert(concert, _ALIASES)

        assert len(matches) == 1
        assert matches[0]["confidence"] == "LOW"

    def test_partial_ratio_below_threshold_returns_none(self):
        """partial_ratio < 85이면 매칭 실패로 failures에 등록되어야 한다."""
        concert = {"concert_id": 21, "title": "전혀 관계없는 공연 제목 xyzxyz", "cast": ""}
        matches, failures = match_concert(concert, _ALIASES)

        assert matches == []
        assert len(failures) == 1

    def test_low_confidence_requires_approval(self):
        """LOW 매칭은 matched_by=prfnm이어야 한다."""
        concert = {"concert_id": 22, "title": "BTS 콘서트", "cast": ""}
        matches, _ = match_concert(concert, _ALIASES)

        assert matches[0]["matched_by"] == "prfnm"

    def test_fuzzy_match_not_used_when_exact_match_found(self):
        """cast 완전 일치가 성공하면 title fuzzy 매칭을 시도하지 않아야 한다."""
        concert = {"concert_id": 23, "title": "BTS 콘서트", "cast": "아이유"}
        matches, _ = match_concert(concert, _ALIASES)

        assert len(matches) == 1
        assert matches[0]["confidence"] == "HIGH"
        assert matches[0]["artist_id"] == 1


class TestMatchFailure:
    def test_no_match_returns_empty_matches(self):
        """두 매칭 모두 실패하면 matches가 빈 리스트이어야 한다."""
        concert = {"concert_id": 30, "title": "알 수 없는 공연 zzzz", "cast": "미상 아티스트 xyz"}
        matches, failures = match_concert(concert, _ALIASES)

        assert matches == []

    def test_no_match_adds_to_failures(self):
        """두 매칭 모두 실패하면 failures에 concert_id가 등록되어야 한다."""
        concert = {"concert_id": 30, "title": "알 수 없는 공연 zzzz", "cast": "미상 아티스트 xyz"}
        _, failures = match_concert(concert, _ALIASES)

        assert len(failures) == 1
        assert failures[0]["concert_id"] == 30

    def test_empty_aliases_always_fails(self):
        """aliases가 빈 리스트이면 항상 매칭 실패여야 한다."""
        concert = {"concert_id": 31, "title": "아이유 콘서트", "cast": "아이유"}
        matches, failures = match_concert(concert, [])

        assert matches == []
        assert failures == [{"concert_id": 31}]
