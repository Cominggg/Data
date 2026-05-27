"""collectors/lastfm.py 단위 테스트."""
from unittest.mock import MagicMock, patch

import pytest
import requests

from collectors.lastfm import get_monthly_listeners


class TestGetMonthlyListeners:
    def test_returns_listener_count(self):
        """정상 응답에서 월간 리스너 수를 반환해야 한다."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "artist": {"stats": {"listeners": "1234567"}}
        }
        with (
            patch("collectors.lastfm._API_KEY", "dummy-key"),
            patch("collectors.lastfm.requests.get", return_value=mock_response),
        ):
            result = get_monthly_listeners("mbid-001")

        assert result == 1234567

    def test_returns_none_when_api_key_missing(self):
        """LASTFM_API_KEY가 없으면 None을 반환해야 한다."""
        with patch("collectors.lastfm._API_KEY", None):
            result = get_monthly_listeners("mbid-001")

        assert result is None

    def test_returns_none_on_api_error_response(self):
        """Last.fm API가 error 필드를 반환하면 None을 반환해야 한다."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"error": 6, "message": "Artist not found"}
        with (
            patch("collectors.lastfm._API_KEY", "dummy-key"),
            patch("collectors.lastfm.requests.get", return_value=mock_response),
        ):
            result = get_monthly_listeners("mbid-unknown")

        assert result is None

    def test_returns_none_on_http_error(self):
        """HTTP 오류 시 None을 반환해야 한다."""
        with (
            patch("collectors.lastfm._API_KEY", "dummy-key"),
            patch(
                "collectors.lastfm.requests.get",
                side_effect=requests.HTTPError("500"),
            ),
        ):
            result = get_monthly_listeners("mbid-001")

        assert result is None

    def test_returns_none_when_listeners_field_missing(self):
        """응답에 listeners 필드가 없으면 None을 반환해야 한다."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"artist": {"stats": {}}}
        with (
            patch("collectors.lastfm._API_KEY", "dummy-key"),
            patch("collectors.lastfm.requests.get", return_value=mock_response),
        ):
            result = get_monthly_listeners("mbid-001")

        assert result is None
