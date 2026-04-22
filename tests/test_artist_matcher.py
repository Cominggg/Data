import pytest

matcher = pytest.importorskip("matchers.artist_matcher", reason="matchers.artist_matcher 미구현")


class TestAliasExactMatch:
    def test_exact_alias_match_returns_high_confidence(self):
        """prfcast → alias 완전 일치 시 confidence=HIGH를 반환해야 한다."""
        pytest.skip("미구현")

    def test_exact_match_does_not_require_approval(self):
        """HIGH 매칭은 approved=True이어야 한다."""
        pytest.skip("미구현")

    def test_multi_artist_cast_matched_individually(self):
        """prfcast에 ',' 또는 '·' 구분자로 여러 아티스트가 있을 때 각각 개별 매칭되어야 한다."""
        pytest.skip("미구현")


class TestFuzzyMatch:
    def test_partial_ratio_above_threshold_returns_low_confidence(self):
        """rapidfuzz partial_ratio >= 85이면 confidence=LOW를 반환해야 한다."""
        pytest.skip("미구현")

    def test_partial_ratio_below_threshold_returns_none(self):
        """partial_ratio < 85이면 매칭 실패로 None을 반환해야 한다."""
        pytest.skip("미구현")

    def test_low_confidence_requires_approval(self):
        """LOW 매칭은 approved=False이어야 한다."""
        pytest.skip("미구현")


class TestMatchFailure:
    def test_no_match_returns_none(self):
        """두 매칭 모두 실패하면 None을 반환해야 한다."""
        pytest.skip("미구현")
