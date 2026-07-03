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
        with patch("api.collect_and_save_concert", return_value={"status": "not_found"}):
            res = client.post("/collect/concert", json={"kopis_id": "PF001"}, headers=_AUTH)
        assert res.status_code != 401


class TestCollectConcertEndpoint:
    _OK_RESULT = {
        "status": "ok",
        "concert_id": 1,
        "title": "TestArtist Live",
        "matched_artists": [{"artist_id": 1, "name": "TestArtist"}],
    }

    def test_returns_200_and_data_on_success(self, client):
        """수집 성공 시 200과 success:true + 데이터를 반환해야 한다."""
        with patch("api.collect_and_save_concert", return_value=self._OK_RESULT):
            res = client.post("/collect/concert", json={"kopis_id": "PF001"}, headers=_AUTH)
        assert res.status_code == 200
        assert res.json() == {
            "success": True,
            "concert_id": 1,
            "title": "TestArtist Live",
            "matched_artists": [{"artist_id": 1, "name": "TestArtist"}],
        }

    def test_returns_404_when_not_found(self, client):
        """KOPIS에 데이터가 없으면 404를 반환해야 한다."""
        with patch("api.collect_and_save_concert", return_value={"status": "not_found"}):
            res = client.post("/collect/concert", json={"kopis_id": "PF001"}, headers=_AUTH)
        assert res.status_code == 404

    def test_returns_200_with_success_false_when_skipped(self, client):
        """비즈니스 스킵(내한 아님 등)이면 200 + success:false를 반환해야 한다."""
        with patch(
            "api.collect_and_save_concert",
            return_value={"status": "skipped", "reason": "not_touring"},
        ):
            res = client.post("/collect/concert", json={"kopis_id": "PF001"}, headers=_AUTH)
        assert res.status_code == 200
        assert res.json() == {"success": False, "reason": "not_touring"}

    def test_called_with_kopis_id(self, client):
        """collect_and_save_concert가 kopis_id로 직접 호출되어야 한다."""
        with patch(
            "api.collect_and_save_concert", return_value={"status": "not_found"}
        ) as mock_fn:
            client.post("/collect/concert", json={"kopis_id": "PF123"}, headers=_AUTH)
        mock_fn.assert_called_once_with("PF123")

    def test_duplicate_request_returns_409(self, client):
        """동일 kopis_id가 이미 실행 중이면 409를 반환해야 한다."""
        import api as api_module
        key = ("concert", "PF_DUP")
        api_module._running_tasks.add(key)
        try:
            with patch("api.collect_and_save_concert", return_value={"status": "not_found"}):
                res = client.post("/collect/concert", json={"kopis_id": "PF_DUP"}, headers=_AUTH)
            assert res.status_code == 409
        finally:
            api_module._running_tasks.discard(key)


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

    def test_duplicate_request_not_accepted(self, client):
        """동일 artist_id가 이미 실행 중이면 accepted:false를 반환해야 한다."""
        import api as api_module
        key = ("releases", 99)
        api_module._running_tasks.add(key)
        try:
            with patch("api.collect_and_save_releases_for_artist"):
                res = client.post("/collect/artist/99/releases", headers=_AUTH)
            assert res.json()["accepted"] is False
        finally:
            api_module._running_tasks.discard(key)


class TestCollectSetlistEndpoint:
    _OK_RESULT = {
        "status": "ok",
        "concert_id": 7,
        "setlist_fm_id": "abc123",
        "attribution_url": "https://setlist.fm/abc123",
        "tracks": [{"position": 1, "song_name": "Song A", "info": None}],
    }

    def test_returns_200_and_data_on_success(self, client):
        """수집 성공 시 200과 success:true + 데이터를 반환해야 한다."""
        with patch("api.collect_and_save_setlist", return_value=self._OK_RESULT):
            res = client.post("/collect/concert/7/setlist", headers=_AUTH)
        assert res.status_code == 200
        assert res.json()["success"] is True
        assert res.json()["tracks"] == [{"position": 1, "song_name": "Song A", "info": None}]

    def test_returns_404_when_concert_not_found(self, client):
        """공연 조회 실패 시 404를 반환해야 한다."""
        with patch("api.collect_and_save_setlist", return_value={"status": "not_found"}):
            res = client.post("/collect/concert/7/setlist", headers=_AUTH)
        assert res.status_code == 404

    def test_returns_200_with_success_false_when_no_setlist(self, client):
        """셋리스트가 없으면 200 + success:false를 반환해야 한다."""
        with patch(
            "api.collect_and_save_setlist",
            return_value={"status": "skipped", "reason": "no_setlist_found"},
        ):
            res = client.post("/collect/concert/7/setlist", headers=_AUTH)
        assert res.status_code == 200
        assert res.json() == {"success": False, "reason": "no_setlist_found"}

    def test_called_with_concert_id(self, client):
        """collect_and_save_setlist가 concert_id로 직접 호출되어야 한다."""
        with patch(
            "api.collect_and_save_setlist", return_value={"status": "not_found"}
        ) as mock_fn:
            client.post("/collect/concert/7/setlist", headers=_AUTH)
        mock_fn.assert_called_once_with(7)

    def test_duplicate_request_returns_409(self, client):
        """동일 concert_id가 이미 실행 중이면 409를 반환해야 한다."""
        import api as api_module
        key = ("setlist", 7)
        api_module._running_tasks.add(key)
        try:
            with patch("api.collect_and_save_setlist", return_value={"status": "not_found"}):
                res = client.post("/collect/concert/7/setlist", headers=_AUTH)
            assert res.status_code == 409
        finally:
            api_module._running_tasks.discard(key)


class TestRegisterArtistEndpoint:
    _OK_RESULT = {
        "status": "ok",
        "artist_id": 1,
        "mbid": "mbid-abc",
        "name": "TestArtist",
        "image_url": "http://img.url",
        "aliases": [{"name": "テストアーティスト", "locale": "ja"}],
    }

    def test_returns_200_and_data_on_success(self, client):
        """등록 성공 시 200과 success:true + 아티스트 정보를 반환해야 한다."""
        with patch("api.register_artist_by_mbid", return_value=self._OK_RESULT):
            res = client.post("/collect/artist", json={"mbid": "mbid-abc"}, headers=_AUTH)
        assert res.status_code == 200
        assert res.json() == {
            "success": True,
            "artist_id": 1,
            "mbid": "mbid-abc",
            "name": "TestArtist",
            "image_url": "http://img.url",
            "aliases": [{"name": "テストアーティスト", "locale": "ja"}],
        }

    def test_returns_404_when_not_found(self, client):
        """MusicBrainz에 아티스트가 없으면 404를 반환해야 한다."""
        with patch("api.register_artist_by_mbid", return_value={"status": "not_found"}):
            res = client.post("/collect/artist", json={"mbid": "mbid-bad"}, headers=_AUTH)
        assert res.status_code == 404

    def test_called_with_mbid(self, client):
        """register_artist_by_mbid가 mbid로 직접 호출되어야 한다."""
        with patch(
            "api.register_artist_by_mbid", return_value={"status": "not_found"}
        ) as mock_fn:
            client.post("/collect/artist", json={"mbid": "mbid-xyz"}, headers=_AUTH)
        mock_fn.assert_called_once_with("mbid-xyz")

    def test_duplicate_request_returns_409(self, client):
        """동일 mbid가 이미 실행 중이면 409를 반환해야 한다."""
        import api as api_module
        key = ("artist", "mbid-dup")
        api_module._running_tasks.add(key)
        try:
            with patch("api.register_artist_by_mbid", return_value={"status": "not_found"}):
                res = client.post("/collect/artist", json={"mbid": "mbid-dup"}, headers=_AUTH)
            assert res.status_code == 409
        finally:
            api_module._running_tasks.discard(key)


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
