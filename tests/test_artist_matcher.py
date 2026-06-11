from matchers.artist_matcher import match_concert

_ALIASES = [
    {"artist_id": 1, "name": "아이유"},
    {"artist_id": 2, "name": "BTS"},
    {"artist_id": 3, "name": "NewJeans"},
    {"artist_id": 4, "name": "Fujii Kaze"},
]


class TestTitlePhraseMatch:
    def test_single_word_alias_exact_token_match(self):
        """공연명에 alias가 단어 단위로 정확히 포함되면 매칭되어야 한다."""
        concert = {"concert_id": 20, "title": "BTS World Tour 콘서트", "cast": ""}
        matches, failures = match_concert(concert, _ALIASES)

        assert len(matches) == 1
        assert matches[0]["artist_id"] == 2
        assert failures == []

    def test_multi_word_alias_phrase_match(self):
        """다중 단어 alias가 공연명에 구문으로 포함되면 매칭되어야 한다."""
        concert = {"concert_id": 21, "title": "Fujii Kaze ASIA TOUR in SEOUL", "cast": ""}
        matches, failures = match_concert(concert, _ALIASES)

        assert len(matches) == 1
        assert matches[0]["artist_id"] == 4

    def test_korean_alias_in_title(self):
        """한국어 alias가 공연명에 포함되면 매칭되어야 한다."""
        concert = {"concert_id": 22, "title": "아이유 콘서트", "cast": ""}
        matches, failures = match_concert(concert, _ALIASES)

        assert len(matches) == 1
        assert matches[0]["artist_id"] == 1

    def test_alias_not_full_word_does_not_match_title(self):
        """alias가 공연명의 단어 일부분이면 매칭되지 않아야 한다."""
        concert = {"concert_id": 24, "title": "BTSWORLDTOUR2024", "cast": ""}
        matches, failures = match_concert(concert, _ALIASES)

        assert matches == []
        assert len(failures) == 1

    def test_no_match_on_unrelated_title(self):
        """관련 없는 공연명에는 매칭이 실패해야 한다."""
        concert = {"concert_id": 25, "title": "전혀 관계없는 공연 제목 xyzxyz", "cast": ""}
        matches, failures = match_concert(concert, _ALIASES)

        assert matches == []
        assert len(failures) == 1

    def test_match_result_has_matched_by_field(self):
        """매칭 결과에 matched_by 필드가 'title' 값으로 포함되어야 한다."""
        concert = {"concert_id": 26, "title": "BTS 콘서트", "cast": ""}
        matches, _ = match_concert(concert, _ALIASES)

        assert len(matches) == 1
        assert "confidence" not in matches[0]
        assert matches[0]["matched_by"] == "title"


class TestMatchFailure:
    def test_no_match_returns_empty_matches(self):
        """매칭 실패 시 matches가 빈 리스트이어야 한다."""
        concert = {"concert_id": 40, "title": "알 수 없는 공연 zzzz", "cast": "미상 아티스트 xyz"}
        matches, failures = match_concert(concert, _ALIASES)

        assert matches == []

    def test_no_match_adds_to_failures(self):
        """매칭 실패 시 failures에 concert_id가 등록되어야 한다."""
        concert = {"concert_id": 40, "title": "알 수 없는 공연 zzzz", "cast": "미상 아티스트 xyz"}
        _, failures = match_concert(concert, _ALIASES)

        assert len(failures) == 1
        assert failures[0]["concert_id"] == 40

    def test_empty_aliases_always_fails(self):
        """aliases가 빈 리스트이면 항상 매칭 실패여야 한다."""
        concert = {"concert_id": 41, "title": "아이유 콘서트", "cast": "아이유"}
        matches, failures = match_concert(concert, [])

        assert matches == []
        assert failures == [{"concert_id": 41}]
