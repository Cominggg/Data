from unittest.mock import patch

import pytest
import requests

from collectors.musicbrainz import (
    _parse_aliases,
    _parse_artist,
    _parse_members,
    _parse_url_rels,
    collect_artists,
)


class TestParseAliases:
    def test_filters_supported_locales(self):
        raw = [
            {"name": "아이유", "locale": "ko"},
            {"name": "IU", "locale": "en"},
            {"name": "アイユー", "locale": "ja"},
            {"name": "Unknown", "locale": "fr"},
        ]
        result = _parse_aliases(raw)
        assert len(result) == 3
        assert {a["locale"] for a in result} == {"ko", "en", "ja"}

    def test_skips_missing_locale(self):
        assert _parse_aliases([{"name": "NoLocale"}]) == []

    def test_strips_region_suffix_from_locale(self):
        raw = [{"name": "IU", "locale": "en-US"}]
        assert _parse_aliases(raw)[0]["locale"] == "en"

    def test_returns_empty_for_empty_input(self):
        assert _parse_aliases([]) == []


class TestParseUrlRels:
    def test_extracts_url_type_relations(self):
        relations = [
            {
                "target-type": "url",
                "type": "official homepage",
                "url": {"resource": "https://example.com"},
            }
        ]
        result = _parse_url_rels(relations)
        assert result == [{"type": "official homepage", "url": "https://example.com"}]

    def test_ignores_non_url_relations(self):
        relations = [{"target-type": "artist", "type": "member of band"}]
        assert _parse_url_rels(relations) == []

    def test_returns_empty_for_empty_input(self):
        assert _parse_url_rels([]) == []


class TestParseMembers:
    def test_extracts_current_member(self):
        relations = [
            {
                "type": "member of band",
                "ended": False,
                "artist": {"id": "mbid-1", "name": "Member A", "sort-name": "A, Member"},
            }
        ]
        result = _parse_members(relations)
        assert len(result) == 1
        assert result[0]["mbid"] == "mbid-1"
        assert result[0]["is_current"] is True

    def test_former_member_is_not_current(self):
        relations = [
            {
                "type": "member of band",
                "ended": True,
                "artist": {"id": "mbid-2", "name": "Former", "sort-name": "Former"},
            }
        ]
        assert _parse_members(relations)[0]["is_current"] is False

    def test_ignores_non_member_relations(self):
        relations = [{"type": "supporting musician", "artist": {"id": "mbid-3"}}]
        assert _parse_members(relations) == []

    def test_returns_empty_for_empty_input(self):
        assert _parse_members([]) == []


class TestParseArtist:
    def test_parses_full_artist(self):
        detail = {
            "id": "mbid-artist",
            "name": "Test Artist",
            "sort-name": "Artist, Test",
            "aliases": [{"name": "테스트", "locale": "ko"}],
            "relations": [],
            "life-span": {"begin": "2010-01-01"},
        }
        result = _parse_artist(detail)
        assert result["mbid"] == "mbid-artist"
        assert result["name"] == "Test Artist"
        assert result["debut_date"] == "2010-01-01"
        assert result["aliases"] == [{"name": "테스트", "locale": "ko"}]

    def test_debut_date_is_none_when_absent(self):
        detail = {
            "id": "x",
            "name": "X",
            "sort-name": "X",
            "aliases": [],
            "relations": [],
            "life-span": {},
        }
        assert _parse_artist(detail)["debut_date"] is None


class TestCollectArtists:
    @patch("collectors.musicbrainz._fetch_artist_detail")
    @patch("collectors.musicbrainz._search_artists")
    def test_collects_single_page(self, mock_search, mock_detail):
        mock_search.return_value = {
            "artists": [{"id": "mbid-1", "name": "Artist1"}],
            "count": 1,
        }
        mock_detail.return_value = {
            "id": "mbid-1",
            "name": "Artist1",
            "sort-name": "Artist1",
            "aliases": [],
            "relations": [],
            "life-span": {},
        }
        result = collect_artists()
        assert len(result) == 1
        assert result[0]["mbid"] == "mbid-1"

    @patch("collectors.musicbrainz._fetch_artist_detail")
    @patch("collectors.musicbrainz._search_artists")
    def test_skips_artist_without_mbid(self, mock_search, mock_detail):
        mock_search.return_value = {"artists": [{"name": "NoMBID"}], "count": 1}
        result = collect_artists()
        mock_detail.assert_not_called()
        assert result == []

    @patch("collectors.musicbrainz._fetch_artist_detail")
    @patch("collectors.musicbrainz._search_artists")
    def test_continues_on_http_error(self, mock_search, mock_detail):
        mock_search.return_value = {"artists": [{"id": "mbid-err"}], "count": 1}
        mock_detail.side_effect = requests.HTTPError("404")
        result = collect_artists()
        assert result == []

    @patch("collectors.musicbrainz._fetch_artist_detail")
    @patch("collectors.musicbrainz._search_artists")
    def test_stops_when_batch_is_empty(self, mock_search, mock_detail):
        mock_search.return_value = {"artists": [], "count": 0}
        result = collect_artists()
        assert result == []
        mock_search.assert_called_once()
