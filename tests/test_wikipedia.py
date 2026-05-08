from unittest.mock import MagicMock, patch

import requests

from collectors.wikipedia import _fetch_redirects, _is_korean, collect_korean_aliases


class TestIsKorean:
    def test_detects_korean_text(self):
        assert _is_korean("호시노 겐") is True

    def test_detects_mixed_korean_english(self):
        assert _is_korean("Hoshino 겐") is True

    def test_rejects_english_only(self):
        assert _is_korean("Hoshino Gen") is False

    def test_rejects_japanese_only(self):
        assert _is_korean("星野源") is False

    def test_rejects_empty_string(self):
        assert _is_korean("") is False


class TestFetchRedirects:
    def _make_response(self, redirects: list) -> MagicMock:
        mock = MagicMock()
        mock.raise_for_status.return_value = None
        mock.json.return_value = {
            "query": {
                "pages": {
                    "1": {
                        "pageid": 1,
                        "title": "Hoshino Gen",
                        "redirects": [{"title": t} for t in redirects],
                    }
                }
            }
        }
        return mock

    @patch("collectors.wikipedia.requests.get")
    def test_returns_redirect_titles(self, mock_get):
        mock_get.return_value = self._make_response(["호시노 겐", "星野源", "Hoshino Gen"])
        result = _fetch_redirects("Hoshino Gen")
        assert result == ["호시노 겐", "星野源", "Hoshino Gen"]

    @patch("collectors.wikipedia.requests.get")
    def test_returns_empty_when_no_redirects(self, mock_get):
        mock_get.return_value = self._make_response([])
        result = _fetch_redirects("Unknown Artist")
        assert result == []

    @patch("collectors.wikipedia.time.sleep")
    @patch("collectors.wikipedia.requests.get")
    def test_returns_empty_on_http_error(self, mock_get, mock_sleep):
        mock_get.return_value = MagicMock()
        mock_get.return_value.raise_for_status.side_effect = requests.HTTPError("404")
        result = _fetch_redirects("Some Artist")
        assert result == []
        assert mock_get.call_count == 3

    @patch("collectors.wikipedia.time.sleep")
    @patch("collectors.wikipedia.requests.get")
    def test_returns_empty_on_connection_error(self, mock_get, mock_sleep):
        mock_get.side_effect = requests.ConnectionError("timeout")
        result = _fetch_redirects("Some Artist")
        assert result == []
        assert mock_get.call_count == 3

    @patch("collectors.wikipedia.time.sleep")
    @patch("collectors.wikipedia.requests.get")
    def test_retries_and_succeeds_on_second_attempt(self, mock_get, mock_sleep):
        mock_get.side_effect = [
            requests.ConnectionError("timeout"),
            self._make_response(["호시노 겐"]),
        ]
        result = _fetch_redirects("Hoshino Gen")
        assert result == ["호시노 겐"]
        assert mock_get.call_count == 2

    @patch("collectors.wikipedia.requests.get")
    def test_skips_redirect_with_empty_title(self, mock_get):
        mock = MagicMock()
        mock.raise_for_status.return_value = None
        mock.json.return_value = {
            "query": {
                "pages": {
                    "1": {
                        "redirects": [{"title": "호시노 겐"}, {"title": ""}],
                    }
                }
            }
        }
        mock_get.return_value = mock
        result = _fetch_redirects("Hoshino Gen")
        assert "" not in result
        assert "호시노 겐" in result


class TestCollectKoreanAliases:
    @patch("collectors.wikipedia._fetch_redirects")
    def test_filters_korean_redirects_only(self, mock_fetch):
        mock_fetch.return_value = ["호시노 겐", "Star Field", "星野源"]
        artists = [{"artist_id": 1, "name": "Hoshino Gen"}]
        result = collect_korean_aliases(artists)
        assert len(result) == 1
        assert result[0] == {"artist_id": 1, "name": "호시노 겐", "locale": "ko"}

    @patch("collectors.wikipedia._fetch_redirects")
    def test_handles_multiple_artists(self, mock_fetch):
        mock_fetch.side_effect = [
            ["호시노 겐"],
            ["아이코"],
        ]
        artists = [
            {"artist_id": 1, "name": "Hoshino Gen"},
            {"artist_id": 2, "name": "aiko"},
        ]
        result = collect_korean_aliases(artists)
        assert len(result) == 2
        assert {r["artist_id"] for r in result} == {1, 2}

    @patch("collectors.wikipedia._fetch_redirects")
    def test_returns_empty_for_no_korean_redirects(self, mock_fetch):
        mock_fetch.return_value = ["Hoshino Gen", "星野源"]
        result = collect_korean_aliases([{"artist_id": 1, "name": "Hoshino Gen"}])
        assert result == []

    @patch("collectors.wikipedia._fetch_redirects")
    def test_returns_empty_for_empty_artist_list(self, mock_fetch):
        result = collect_korean_aliases([])
        mock_fetch.assert_not_called()
        assert result == []

    @patch("collectors.wikipedia._fetch_redirects")
    def test_multiple_korean_aliases_per_artist(self, mock_fetch):
        mock_fetch.return_value = ["호시노 겐", "호시노겐"]
        result = collect_korean_aliases([{"artist_id": 1, "name": "Hoshino Gen"}])
        assert len(result) == 2
        names = {r["name"] for r in result}
        assert names == {"호시노 겐", "호시노겐"}
