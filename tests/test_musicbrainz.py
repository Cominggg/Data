from unittest.mock import MagicMock, patch

import pytest
import requests

from collectors.musicbrainz import (
    _parse_aliases,
    _parse_artist,
    _parse_url_rels,
    collect_artists,
)
from db.repository import save_artists


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
    def test_allows_instagram(self):
        relations = [
            {
                "target-type": "url",
                "type": "social network",
                "url": {"resource": "https://www.instagram.com/artist"},
            }
        ]
        result = _parse_url_rels(relations)
        assert result == [{"type": "social network", "url": "https://www.instagram.com/artist"}]

    def test_allows_all_target_platforms(self):
        relations = [
            {"target-type": "url", "type": "social network", "url": {"resource": "https://twitter.com/artist"}},
            {"target-type": "url", "type": "social network", "url": {"resource": "https://x.com/artist"}},
            {"target-type": "url", "type": "social network", "url": {"resource": "https://www.instagram.com/artist"}},
            {"target-type": "url", "type": "youtube", "url": {"resource": "https://www.youtube.com/channel/abc"}},
            {"target-type": "url", "type": "free streaming", "url": {"resource": "https://open.spotify.com/artist/abc"}},
            {"target-type": "url", "type": "free streaming", "url": {"resource": "https://music.apple.com/artist/abc"}},
        ]
        result = _parse_url_rels(relations)
        assert len(result) == 6

    def test_filters_disallowed_domains(self):
        relations = [
            {"target-type": "url", "type": "official homepage", "url": {"resource": "https://example.com"}},
            {"target-type": "url", "type": "social network", "url": {"resource": "https://facebook.com/artist"}},
            {"target-type": "url", "type": "social network", "url": {"resource": "https://weibo.com/artist"}},
            {"target-type": "url", "type": "free streaming", "url": {"resource": "https://soundcloud.com/artist"}},
        ]
        assert _parse_url_rels(relations) == []

    def test_ignores_non_url_relations(self):
        relations = [{"target-type": "artist", "type": "member of band"}]
        assert _parse_url_rels(relations) == []

    def test_returns_empty_for_empty_input(self):
        assert _parse_url_rels([]) == []


class TestParseArtist:
    def test_parses_full_artist(self):
        detail = {
            "id": "mbid-artist",
            "name": "Test Artist",
            "sort-name": "Artist, Test",
            "aliases": [{"name": "테스트", "locale": "ko"}],
            "relations": [],
        }
        result = _parse_artist(detail)
        assert result["mbid"] == "mbid-artist"
        assert result["name"] == "Test Artist"
        assert result["aliases"] == [{"name": "테스트", "locale": "ko"}]
        assert "debut_date" not in result


class TestCollectArtists:
    @patch("collectors.musicbrainz.get_monthly_listeners", return_value=10000)
    @patch("collectors.musicbrainz._fetch_artist_detail")
    @patch("collectors.musicbrainz._search_artists")
    def test_collects_single_page(self, mock_search, mock_detail, mock_listeners):
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

    @patch("collectors.musicbrainz.get_monthly_listeners", return_value=10000)
    @patch("collectors.musicbrainz._fetch_artist_detail")
    @patch("collectors.musicbrainz._search_artists")
    def test_continues_on_http_error(self, mock_search, mock_detail, mock_listeners):
        mock_search.return_value = {"artists": [{"id": "mbid-err"}], "count": 1}
        mock_detail.side_effect = requests.HTTPError("404")
        result = collect_artists()
        assert result == []

    @patch("collectors.musicbrainz.get_monthly_listeners", return_value=1000)
    @patch("collectors.musicbrainz._fetch_artist_detail")
    @patch("collectors.musicbrainz._search_artists")
    def test_skips_artist_below_listener_threshold(self, mock_search, mock_detail, mock_listeners):
        """월간 리스너가 임계값 미만이면 아티스트를 수집하지 않아야 한다."""
        mock_search.return_value = {
            "artists": [{"id": "mbid-low", "name": "LowArtist"}],
            "count": 1,
        }
        mock_detail.return_value = {
            "id": "mbid-low", "name": "LowArtist", "sort-name": "LowArtist",
            "aliases": [], "relations": [],
        }
        result = collect_artists()
        assert result == []

    @patch("collectors.musicbrainz.get_monthly_listeners", return_value=None)
    @patch("collectors.musicbrainz._fetch_artist_detail")
    @patch("collectors.musicbrainz._search_artists")
    def test_includes_artist_when_listeners_unavailable(self, mock_search, mock_detail, mock_listeners):
        """Last.fm 조회 실패(None) 시 아티스트를 수집해야 한다."""
        mock_search.return_value = {
            "artists": [{"id": "mbid-1", "name": "Artist1"}],
            "count": 1,
        }
        mock_detail.return_value = {
            "id": "mbid-1", "name": "Artist1", "sort-name": "Artist1",
            "aliases": [], "relations": [],
        }
        result = collect_artists()
        assert len(result) == 1

    @patch("collectors.musicbrainz._fetch_artist_detail")
    @patch("collectors.musicbrainz._search_artists")
    def test_stops_when_batch_is_empty(self, mock_search, mock_detail):
        mock_search.return_value = {"artists": [], "count": 0}
        result = collect_artists()
        assert result == []
        mock_search.assert_called_once()

    @patch("collectors.musicbrainz._MAX_ARTISTS", 1)
    @patch("collectors.musicbrainz.get_monthly_listeners", return_value=10000)
    @patch("collectors.musicbrainz._fetch_artist_detail")
    @patch("collectors.musicbrainz._search_artists")
    def test_stops_at_max_artists_limit(self, mock_search, mock_detail, mock_listeners):
        """_MAX_ARTISTS 상한 도달 시 다음 페이지를 요청하지 않고 중단해야 한다."""
        mock_search.return_value = {
            "artists": [{"id": "mbid-1", "name": "Artist1"}],
            "count": 10_000,
        }
        mock_detail.return_value = {
            "id": "mbid-1", "name": "Artist1", "sort-name": "Artist1",
            "aliases": [], "relations": [],
        }
        result = collect_artists()
        assert len(result) == 1
        mock_search.assert_called_once()


class TestSaveArtists:
    def _make_session_mock(self, insert_returns_id=True):
        mock_session = MagicMock()
        if insert_returns_id:
            mock_session.execute.return_value.fetchone.return_value = (1,)
        else:
            mock_session.execute.return_value.fetchone.side_effect = [None, (1,)]
        return mock_session

    def _run(self, artists, mock_session):
        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            save_artists(artists)

    def test_artist_insert_uses_on_conflict_do_nothing(self):
        """artist INSERT에 ON CONFLICT (mbid) DO NOTHING이 포함되어야 한다."""
        mock_session = self._make_session_mock()
        self._run([{"mbid": "m1", "name": "A", "sort_name": "A", "aliases": [], "url_rels": []}], mock_session)

        artist_insert_sql = next(
            str(c.args[0])
            for c in mock_session.execute.call_args_list
            if "INSERT INTO artist" in str(c.args[0])
        )
        assert "ON CONFLICT (mbid) DO NOTHING" in artist_insert_sql

    def test_inserts_aliases_for_artist(self):
        """alias 목록이 artist_alias 테이블에 INSERT되어야 한다."""
        mock_session = self._make_session_mock()
        artist = {
            "mbid": "m1",
            "name": "Artist",
            "sort_name": "Artist",
            "aliases": [
                {"name": "아티스트", "locale": "ko"},
                {"name": "Artist", "locale": "en"},
            ],
            "url_rels": [],
        }
        self._run([artist], mock_session)

        alias_inserts = [
            c for c in mock_session.execute.call_args_list
            if "INSERT INTO artist_alias" in str(c.args[0])
        ]
        assert len(alias_inserts) == 2

    def test_inserts_url_rels_for_artist(self):
        """url_rels 목록이 artist_url 테이블에 INSERT되어야 한다."""
        mock_session = self._make_session_mock()
        artist = {
            "mbid": "m1",
            "name": "Artist",
            "sort_name": "Artist",
            "aliases": [],
            "url_rels": [
                {"type": "official homepage", "url": "https://example.com"},
                {"type": "social network", "url": "https://twitter.com/artist"},
            ],
        }
        self._run([artist], mock_session)

        url_inserts = [
            c for c in mock_session.execute.call_args_list
            if "INSERT INTO artist_url" in str(c.args[0])
        ]
        assert len(url_inserts) == 2

    def test_selects_artist_id_when_conflict(self):
        """mbid 충돌로 RETURNING이 없을 때 SELECT로 기존 ID를 조회해야 한다."""
        mock_session = self._make_session_mock(insert_returns_id=False)
        artist = {
            "mbid": "existing-mbid",
            "name": "Artist",
            "sort_name": "Artist",
            "aliases": [{"name": "아티스트", "locale": "ko"}],
            "url_rels": [],
        }
        self._run([artist], mock_session)

        select_calls = [
            c for c in mock_session.execute.call_args_list
            if "SELECT id FROM artist" in str(c.args[0])
        ]
        assert len(select_calls) == 1

        alias_inserts = [
            c for c in mock_session.execute.call_args_list
            if "INSERT INTO artist_alias" in str(c.args[0])
        ]
        assert len(alias_inserts) == 1

    def test_skips_artist_when_id_not_found(self):
        """INSERT도 SELECT도 None이면 alias·url INSERT 없이 건너뛰어야 한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = None

        artist = {
            "mbid": "ghost-mbid",
            "name": "Ghost",
            "sort_name": "Ghost",
            "aliases": [{"name": "고스트", "locale": "ko"}],
            "url_rels": [{"type": "homepage", "url": "https://ghost.com"}],
        }
        self._run([artist], mock_session)

        child_inserts = [
            c for c in mock_session.execute.call_args_list
            if "INSERT INTO artist_alias" in str(c.args[0])
            or "INSERT INTO artist_url" in str(c.args[0])
        ]
        assert len(child_inserts) == 0

    def test_handles_empty_aliases_and_urls(self):
        """aliases와 url_rels가 없어도 정상 저장되어야 한다."""
        mock_session = self._make_session_mock()
        artist = {"mbid": "m1", "name": "A", "sort_name": "A", "aliases": [], "url_rels": []}
        self._run([artist], mock_session)

        artist_inserts = [
            c for c in mock_session.execute.call_args_list
            if "INSERT INTO artist" in str(c.args[0])
        ]
        assert len(artist_inserts) == 1

    def test_handles_empty_list(self):
        """빈 리스트 입력 시 DB 호출 없이 종료되어야 한다."""
        mock_session = self._make_session_mock()
        self._run([], mock_session)
        mock_session.execute.assert_not_called()
