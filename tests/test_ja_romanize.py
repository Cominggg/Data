from collectors.ja_romanize import (
    _is_japanese_script,
    collect_ko_aliases,
    romanize_to_korean,
)


class TestIsJapaneseScript:
    def test_detects_kanji(self):
        assert _is_japanese_script("米津玄師") is True

    def test_detects_katakana(self):
        assert _is_japanese_script("ヨアソビ") is True

    def test_detects_hiragana(self):
        assert _is_japanese_script("ふじい") is True

    def test_rejects_latin_only(self):
        assert _is_japanese_script("YOASOBI") is False

    def test_rejects_empty_string(self):
        assert _is_japanese_script("") is False


class TestRomanizeToKorean:
    def test_word_initial_plain_medial_aspirate_across_space(self):
        # 성-이름 경계를 넘어도 파열음 규칙은 이름 전체를 한 발화로 취급한다.
        assert romanize_to_korean("Yonezu, Kenshi") == "요네즈 켄시"
        assert romanize_to_korean("Fujii, Kaze") == "후지이 카제"

    def test_fixed_series_no_alternation(self):
        assert romanize_to_korean("Utada, Hikaru") == "우타다 히카루"
        assert romanize_to_korean("Fujiwara, Sakura") == "후지와라 사쿠라"

    def test_group_name_without_comma(self):
        assert romanize_to_korean("Tokyo Jihen") == "도쿄 지헨"
        assert romanize_to_korean("Kobukuro") == "고부쿠로"

    def test_sokuon_doubled_consonant_becomes_batchim_siot(self):
        assert romanize_to_korean("Sapporo") == "삿포로"

    def test_hatsuon_word_final_n_becomes_batchim_nieun(self):
        assert romanize_to_korean("Jihen") == "지헨"

    def test_returns_none_for_unparseable_latin_words(self):
        assert romanize_to_korean("Tokyo Ska Paradise Orchestra") is None

    def test_strips_trailing_punctuation(self):
        assert romanize_to_korean("haku.") == "하쿠"

    def test_passes_through_trailing_group_number(self):
        assert romanize_to_korean("Nogizaka46") == "노기자카46"

    def test_hyphen_is_treated_as_mora_boundary_not_word_break(self):
        assert romanize_to_korean("Akai Ko-en") == "아카이 코엔"

    def test_returns_none_for_empty_input(self):
        assert romanize_to_korean("") is None
        assert romanize_to_korean(None) is None


class TestCollectKoAliases:
    def test_converts_artist_with_japanese_script_name(self):
        artists = [{"artist_id": 1, "name": "米津玄師", "sort_name": "Yonezu, Kenshi"}]
        assert collect_ko_aliases(artists) == [
            {"artist_id": 1, "name": "요네즈 켄시", "locale": "ko"}
        ]

    def test_skips_artist_whose_name_is_already_latin(self):
        artists = [{"artist_id": 2, "name": "YOASOBI", "sort_name": "YOASOBI"}]
        assert collect_ko_aliases(artists) == []

    def test_skips_artist_when_conversion_fails(self):
        artists = [
            {
                "artist_id": 3,
                "name": "東京スカパラダイスオーケストラ",
                "sort_name": "Tokyo Ska Paradise Orchestra",
            }
        ]
        assert collect_ko_aliases(artists) == []

    def test_handles_multiple_artists_mixed_results(self):
        artists = [
            {"artist_id": 1, "name": "米津玄師", "sort_name": "Yonezu, Kenshi"},
            {"artist_id": 2, "name": "YOASOBI", "sort_name": "YOASOBI"},
        ]
        result = collect_ko_aliases(artists)
        assert result == [{"artist_id": 1, "name": "요네즈 켄시", "locale": "ko"}]
