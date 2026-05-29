"""collectors/artist_image.py 단위 테스트."""
from unittest.mock import MagicMock, patch

import pytest
import requests

from collectors.artist_image import collect_artist_image


class TestCollectArtistImage:
    def test_returns_image_url(self):
        """정상 응답에서 artistthumb[0].url을 반환해야 한다."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "artistthumb": [{"url": "https://assets.fanart.tv/fanart/music/mbid-001/artistthumb.jpg"}]
        }
        with (
            patch("collectors.artist_image.os.environ.get", return_value="dummy-key"),
            patch("collectors.artist_image.requests.get", return_value=mock_response),
        ):
            result = collect_artist_image("mbid-001")

        assert result == "https://assets.fanart.tv/fanart/music/mbid-001/artistthumb.jpg"

    def test_returns_none_on_404(self):
        """404 응답 시 None을 반환해야 한다."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        with (
            patch("collectors.artist_image.os.environ.get", return_value="dummy-key"),
            patch("collectors.artist_image.requests.get", return_value=mock_response),
        ):
            result = collect_artist_image("mbid-unknown")

        assert result is None

    def test_returns_none_when_artistthumb_missing(self):
        """응답에 artistthumb 필드가 없으면 None을 반환해야 한다."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}
        with (
            patch("collectors.artist_image.os.environ.get", return_value="dummy-key"),
            patch("collectors.artist_image.requests.get", return_value=mock_response),
        ):
            result = collect_artist_image("mbid-001")

        assert result is None

    def test_returns_none_when_artistthumb_empty(self):
        """artistthumb 배열이 비어 있으면 None을 반환해야 한다."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"artistthumb": []}
        with (
            patch("collectors.artist_image.os.environ.get", return_value="dummy-key"),
            patch("collectors.artist_image.requests.get", return_value=mock_response),
        ):
            result = collect_artist_image("mbid-001")

        assert result is None

    def test_raises_when_api_key_missing(self):
        """FANART_TV_API_KEY가 없으면 ValueError를 발생시켜야 한다."""
        with patch("collectors.artist_image.os.environ.get", return_value=None):
            with pytest.raises(ValueError, match="FANART_TV_API_KEY"):
                collect_artist_image("mbid-001")

    def test_raises_on_network_error(self):
        """네트워크 오류 시 RequestException을 전파해야 한다."""
        with (
            patch("collectors.artist_image.os.environ.get", return_value="dummy-key"),
            patch(
                "collectors.artist_image.requests.get",
                side_effect=requests.ConnectionError("timeout"),
            ),
        ):
            with pytest.raises(requests.RequestException):
                collect_artist_image("mbid-001")
