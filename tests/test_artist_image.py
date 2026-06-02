"""collectors/artist_image.py 단위 테스트."""
from unittest.mock import MagicMock, patch

import pytest
import requests

from collectors.artist_image import collect_artist_image


def _make_token_response(token: str = "test-token", expires_in: int = 3600) -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {"access_token": token, "expires_in": expires_in}
    return mock


def _make_mb_response(name: str = "back number", spotify_url: str = None) -> MagicMock:
    relations = []
    if spotify_url:
        relations.append({"url": {"resource": spotify_url}})
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {"name": name, "relations": relations}
    return mock


def _make_spotify_artist_response(images: list = None) -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {"images": images or []}
    return mock


class TestCollectArtistImage:
    def _patch_env(self):
        return patch.dict(
            "os.environ",
            {"SPOTIFY_CLIENT_ID": "test-id", "SPOTIFY_CLIENT_SECRET": "test-secret"},
        )

    def test_returns_image_url_via_url_rels(self):
        """MB URL relations에 Spotify ID 있음 → 이미지 URL 반환."""
        mb_response = _make_mb_response(
            name="back number",
            spotify_url="https://open.spotify.com/artist/abc123",
        )
        artist_response = _make_spotify_artist_response(
            images=[{"url": "https://i.scdn.co/image/large.jpg", "width": 640, "height": 640}]
        )

        with self._patch_env(), patch("collectors.artist_image.requests.post",
                                      return_value=_make_token_response()), \
                patch("collectors.artist_image.requests.get",
                      side_effect=[mb_response, artist_response]):
            result = collect_artist_image("mbid-001")

        assert result == "https://i.scdn.co/image/large.jpg"

    def test_returns_image_url_via_name_search(self):
        """MB URL relations에 Spotify 없음 → 이름 검색 fallback → 이미지 반환."""
        mb_response = _make_mb_response(name="Mrs. GREEN APPLE")
        search_response = MagicMock()
        search_response.status_code = 200
        search_response.json.return_value = {
            "artists": {"items": [{"id": "spotify-xyz"}]}
        }
        artist_response = _make_spotify_artist_response(
            images=[{"url": "https://i.scdn.co/image/fallback.jpg", "width": 640, "height": 640}]
        )

        with self._patch_env(), patch("collectors.artist_image.requests.post",
                                      return_value=_make_token_response()), \
                patch("collectors.artist_image.requests.get",
                      side_effect=[mb_response, search_response, artist_response]):
            result = collect_artist_image("mbid-002")

        assert result == "https://i.scdn.co/image/fallback.jpg"

    def test_returns_none_when_mb_artist_not_found(self):
        """MusicBrainz 404 → None 반환."""
        mb_response = MagicMock()
        mb_response.status_code = 404

        with self._patch_env(), patch("collectors.artist_image.requests.post",
                                      return_value=_make_token_response()), \
                patch("collectors.artist_image.requests.get", return_value=mb_response):
            result = collect_artist_image("mbid-unknown")

        assert result is None

    def test_returns_none_when_spotify_id_not_found(self):
        """Spotify ID 조회 실패 (검색 결과 없음) → None 반환."""
        mb_response = _make_mb_response(name="Unknown Artist")
        search_response = MagicMock()
        search_response.status_code = 200
        search_response.json.return_value = {"artists": {"items": []}}

        with self._patch_env(), patch("collectors.artist_image.requests.post",
                                      return_value=_make_token_response()), \
                patch("collectors.artist_image.requests.get",
                      side_effect=[mb_response, search_response]):
            result = collect_artist_image("mbid-003")

        assert result is None

    def test_returns_none_when_images_empty(self):
        """Spotify images 배열이 비어 있음 → None 반환."""
        mb_response = _make_mb_response(
            name="Yoasobi",
            spotify_url="https://open.spotify.com/artist/yoasobi123",
        )
        artist_response = _make_spotify_artist_response(images=[])

        with self._patch_env(), patch("collectors.artist_image.requests.post",
                                      return_value=_make_token_response()), \
                patch("collectors.artist_image.requests.get",
                      side_effect=[mb_response, artist_response]):
            result = collect_artist_image("mbid-004")

        assert result is None

    def test_skips_mb_api_when_spotify_url_provided(self):
        """spotify_url 파라미터 제공 시 MB API 호출 없이 Spotify ID 직접 사용."""
        artist_response = _make_spotify_artist_response(
            images=[{"url": "https://i.scdn.co/image/direct.jpg", "width": 640, "height": 640}]
        )
        mock_get = MagicMock(return_value=artist_response)

        with self._patch_env(), patch("collectors.artist_image.requests.post",
                                      return_value=_make_token_response()), \
                patch("collectors.artist_image.requests.get", mock_get):
            result = collect_artist_image(
                "mbid-005",
                spotify_url="https://open.spotify.com/artist/direct-id",
            )

        assert result == "https://i.scdn.co/image/direct.jpg"
        # MB API가 아닌 Spotify artists 엔드포인트만 호출됐는지 확인
        call_url = mock_get.call_args[0][0]
        assert "spotify.com" in call_url or "api.spotify.com" in call_url
        assert "musicbrainz" not in call_url

    def test_skips_mb_api_when_name_provided(self):
        """name 파라미터 제공 시 MB API 호출 없이 이름 검색만 수행."""
        search_response = MagicMock()
        search_response.status_code = 200
        search_response.json.return_value = {"artists": {"items": [{"id": "name-search-id"}]}}
        artist_response = _make_spotify_artist_response(
            images=[{"url": "https://i.scdn.co/image/by-name.jpg", "width": 640, "height": 640}]
        )

        with self._patch_env(), patch("collectors.artist_image.requests.post",
                                      return_value=_make_token_response()), \
                patch("collectors.artist_image.requests.get",
                      side_effect=[search_response, artist_response]) as mock_get:
            result = collect_artist_image("mbid-006", name="YOASOBI")

        assert result == "https://i.scdn.co/image/by-name.jpg"
        # 첫 번째 GET 호출이 MusicBrainz가 아닌 Spotify search여야 함
        first_call_url = mock_get.call_args_list[0][0][0]
        assert "musicbrainz" not in first_call_url

    def test_raises_when_credentials_missing(self):
        """SPOTIFY_CLIENT_ID 또는 SPOTIFY_CLIENT_SECRET 미설정 → ValueError."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="SPOTIFY_CLIENT_ID"):
                collect_artist_image("mbid-001")

    def test_raises_on_network_error(self):
        """네트워크 오류 시 RequestException 전파."""
        with self._patch_env(), patch("collectors.artist_image.requests.post",
                                      side_effect=requests.ConnectionError("timeout")):
            with pytest.raises(requests.RequestException):
                collect_artist_image("mbid-001")
