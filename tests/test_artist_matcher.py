from matchers.artist_matcher import has_match, match_concert

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


class TestSpecialCharAndWordBoundary:
    def test_special_char_alias_matches_title(self):
        """특수문자 포함 alias가 정규화 후 공연명과 매칭되어야 한다 (tuki. 사례)."""
        aliases = [{"artist_id": 10, "name": "tuki."}]
        concert = {"concert_id": 30, "title": "tuki. 1ST ASIA TOUR [서울]"}
        matches, failures = match_concert(concert, aliases)

        assert len(matches) == 1
        assert matches[0]["artist_id"] == 10
        assert failures == []

    def test_hyphen_alias_matches_title(self):
        """하이픈 포함 alias가 정규화 후 공연명과 매칭되어야 한다 (w-inds. 사례)."""
        aliases = [{"artist_id": 11, "name": "w-inds."}]
        concert = {"concert_id": 31, "title": "w-inds. LIVE TOUR 2024"}
        matches, failures = match_concert(concert, aliases)

        assert len(matches) == 1
        assert matches[0]["artist_id"] == 11

    def test_multi_word_no_false_positive_on_suffix(self):
        """다중 단어 alias가 공연명 단어의 접두사인 경우 오탐되지 않아야 한다."""
        aliases = [{"artist_id": 12, "name": "One OK Rock"}]
        concert = {"concert_id": 32, "title": "One OK Rocket Festival 2024"}
        matches, failures = match_concert(concert, aliases)

        assert matches == []
        assert len(failures) == 1

    def test_multi_word_alias_exact_phrase_matches(self):
        """다중 단어 alias가 공연명에 정확한 구문으로 포함되면 매칭되어야 한다."""
        aliases = [{"artist_id": 12, "name": "One OK Rock"}]
        concert = {"concert_id": 33, "title": "One OK Rock LIVE IN SEOUL 2024"}
        matches, failures = match_concert(concert, aliases)

        assert len(matches) == 1
        assert matches[0]["artist_id"] == 12


class TestShortAliasFilter:
    def test_two_char_alias_matches(self):
        """2자 아티스트명(IU)이 공연명에 포함되면 매칭되어야 한다."""
        aliases = [{"artist_id": 20, "name": "IU"}]
        concert = {"concert_id": 34, "title": "IU CONCERT 2024 SEOUL"}
        matches, failures = match_concert(concert, aliases)

        assert len(matches) == 1
        assert matches[0]["artist_id"] == 20

    def test_one_wordchar_alias_is_filtered(self):
        """word-char 1자 이하 alias는 필터링되어 매칭되지 않아야 한다."""
        aliases = [{"artist_id": 21, "name": "."}]
        concert = {"concert_id": 35, "title": "어떤 공연 제목 2024"}
        matches, failures = match_concert(concert, aliases)

        assert matches == []

    def test_has_match_two_char_alias(self):
        """has_match에서도 2자 alias가 매칭되어야 한다."""
        aliases = [{"artist_id": 20, "name": "IU"}]
        concert_raw = {"prfnm": "IU CONCERT 2024 SEOUL"}

        assert has_match(concert_raw, aliases) is True


class TestJointConcertMultiArtist:
    def test_joint_concert_matches_both_artists(self):
        """합동 공연명에서 두 아티스트가 모두 매칭되어야 한다."""
        aliases = [
            {"artist_id": 30, "name": "Perfume"},
            {"artist_id": 31, "name": "BABYMETAL"},
        ]
        concert = {"concert_id": 36, "title": "Perfume × BABYMETAL LIVE IN SEOUL"}
        matches, failures = match_concert(concert, aliases)

        assert len(matches) == 2
        matched_ids = {m["artist_id"] for m in matches}
        assert matched_ids == {30, 31}
        assert failures == []

    def test_same_artist_best_alias_only_returned(self):
        """동일 artist의 여러 alias가 모두 매칭되면 가장 긴 alias 하나만 반환해야 한다."""
        aliases = [
            {"artist_id": 40, "name": "ONE OK ROCK"},
            {"artist_id": 40, "name": "ONE OK"},
        ]
        concert = {"concert_id": 37, "title": "ONE OK ROCK LIVE 2024"}
        matches, failures = match_concert(concert, aliases)

        assert len(matches) == 1
        assert matches[0]["artist_id"] == 40

    def test_joint_concert_all_matched_by_title(self):
        """합동 공연 다중 매칭 결과의 matched_by 필드가 모두 'title'이어야 한다."""
        aliases = [
            {"artist_id": 30, "name": "Perfume"},
            {"artist_id": 31, "name": "BABYMETAL"},
        ]
        concert = {"concert_id": 38, "title": "Perfume × BABYMETAL LIVE IN SEOUL"}
        matches, _ = match_concert(concert, aliases)

        assert all(m["matched_by"] == "title" for m in matches)


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
