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
