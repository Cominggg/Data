"""api.py 단위 테스트."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_SECRET = "test-secret"


@pytest.fixture(autouse=True)
def set_secret(monkeypatch):
    monkeypatch.setenv("INTERNAL_SECRET", _SECRET)
    import importlib

    import api
    importlib.reload(api)


@pytest.fixture()
def client():
    import api
    return TestClient(api.app, raise_server_exceptions=False)


_AUTH = {"X-Internal-Secret": _SECRET}


class TestAuth:
    def test_missing_secret_returns_401(self, client):
        """X-Internal-Secret 헤더 없으면 401이어야 한다."""
        res = client.post("/collect/concert", json={"kopis_id": "PF001"})
        assert res.status_code == 401

    def test_wrong_secret_returns_401(self, client):
        """잘못된 시크릿이면 401이어야 한다."""
        res = client.post(
            "/collect/concert",
            json={"kopis_id": "PF001"},
            headers={"X-Internal-Secret": "wrong"},
        )
        assert res.status_code == 401

    def test_correct_secret_is_accepted(self, client):
        """올바른 시크릿이면 401이 아니어야 한다."""
        with patch("api.collect_and_save_concert"):
            res = client.post("/collect/concert", json={"kopis_id": "PF001"}, headers=_AUTH)
        assert res.status_code != 401


class TestCollectConcertEndpoint:
    def test_returns_202(self, client):
        """POST /collect/concert 는 202를 반환해야 한다."""
        with patch("api.collect_and_save_concert"):
            res = client.post("/collect/concert", json={"kopis_id": "PF001"}, headers=_AUTH)
        assert res.status_code == 202

    def test_response_body_accepted(self, client):
        """응답 body에 accepted:true가 있어야 한다."""
        with patch("api.collect_and_save_concert"):
            res = client.post("/collect/concert", json={"kopis_id": "PF001"}, headers=_AUTH)
        assert res.json()["accepted"] is True

    def test_background_task_called(self, client):
        """collect_and_save_concert가 BackgroundTask로 호출되어야 한다."""
        with patch("api.collect_and_save_concert") as mock_fn:
            client.post("/collect/concert", json={"kopis_id": "PF123"}, headers=_AUTH)
        mock_fn.assert_called_once_with("PF123")


class TestCollectReleasesEndpoint:
    def test_returns_202(self, client):
        """POST /collect/artist/{id}/releases 는 202를 반환해야 한다."""
        with patch("api.collect_and_save_releases_for_artist"):
            res = client.post("/collect/artist/1/releases", headers=_AUTH)
        assert res.status_code == 202

    def test_background_task_called_with_artist_id(self, client):
        """collect_and_save_releases_for_artist가 artist_id로 호출되어야 한다."""
        with patch("api.collect_and_save_releases_for_artist") as mock_fn:
            client.post("/collect/artist/99/releases", headers=_AUTH)
        mock_fn.assert_called_once_with(99)


class TestCollectSetlistEndpoint:
    def test_returns_202(self, client):
        """POST /collect/concert/{id}/setlist 는 202를 반환해야 한다."""
        with patch("api.collect_and_save_setlist"):
            res = client.post("/collect/concert/7/setlist", headers=_AUTH)
        assert res.status_code == 202

    def test_background_task_called_with_concert_id(self, client):
        """collect_and_save_setlist가 concert_id로 호출되어야 한다."""
        with patch("api.collect_and_save_setlist") as mock_fn:
            client.post("/collect/concert/7/setlist", headers=_AUTH)
        mock_fn.assert_called_once_with(7)


class TestRegisterArtistEndpoint:
    def test_returns_202(self, client):
        """POST /collect/artist 는 202를 반환해야 한다."""
        with patch("api.register_artist_by_mbid"):
            res = client.post("/collect/artist", json={"mbid": "mbid-abc"}, headers=_AUTH)
        assert res.status_code == 202

    def test_background_task_called_with_mbid(self, client):
        """register_artist_by_mbid가 mbid로 호출되어야 한다."""
        with patch("api.register_artist_by_mbid") as mock_fn:
            client.post("/collect/artist", json={"mbid": "mbid-xyz"}, headers=_AUTH)
        mock_fn.assert_called_once_with("mbid-xyz")


class TestSearchArtistsEndpoint:
    def test_returns_200(self, client):
        """GET /search/artists?name= 는 200을 반환해야 한다."""
        with patch("collectors.musicbrainz.search_artists", return_value=[]):
            res = client.get("/search/artists?name=YOASOBI", headers=_AUTH)
        assert res.status_code == 200

    def test_missing_name_returns_422(self, client):
        """name 파라미터 없으면 422이어야 한다."""
        res = client.get("/search/artists", headers=_AUTH)
        assert res.status_code == 422

    def test_returns_artist_list(self, client):
        """검색 결과 리스트를 그대로 반환해야 한다."""
        artists = [{"mbid": "abc-123", "name": "YOASOBI", "country": "JP", "type": "Group"}]
        with patch("collectors.musicbrainz.search_artists", return_value=artists) as mock_fn:
            res = client.get("/search/artists?name=YOASOBI", headers=_AUTH)
        mock_fn.assert_called_once_with("YOASOBI")
        assert res.json() == artists

    def test_unauthorized_returns_401(self, client):
        """인증 없으면 401이어야 한다."""
        res = client.get("/search/artists?name=BTS")
        assert res.status_code == 401


class TestSearchConcertsEndpoint:
    def test_returns_200(self, client):
        """GET /search/concerts?title= 는 200을 반환해야 한다."""
        with patch("collectors.kopis.search_concerts", return_value=[]):
            res = client.get("/search/concerts?title=BTS", headers=_AUTH)
        assert res.status_code == 200

    def test_missing_title_returns_422(self, client):
        """title 파라미터 없으면 422이어야 한다."""
        res = client.get("/search/concerts", headers=_AUTH)
        assert res.status_code == 422

    def test_returns_concert_list(self, client):
        """검색 결과 리스트를 그대로 반환해야 한다."""
        concerts = [{
            "kopis_id": "PF001", "title": "BTS WORLD TOUR",
            "start_date": "2024-06-01", "end_date": "2024-06-02", "venue": "KSPO DOME",
        }]
        with patch("collectors.kopis.search_concerts", return_value=concerts) as mock_fn:
            res = client.get("/search/concerts?title=BTS", headers=_AUTH)
        mock_fn.assert_called_once_with("BTS")
        assert res.json() == concerts

    def test_unauthorized_returns_401(self, client):
        """인증 없으면 401이어야 한다."""
        res = client.get("/search/concerts?title=BTS")
        assert res.status_code == 401
