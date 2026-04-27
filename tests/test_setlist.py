from unittest.mock import MagicMock, patch

import pytest
import requests

from collectors.setlist import _event_date_in_range, _parse_tracks, collect


def _make_api_response(setlists: list[dict]) -> dict:
    return {"setlist": setlists}


def _sample_setlist(**kwargs) -> dict:
    base = {
        "id": "abc123def",
        "eventDate": "28-04-2024",
        "sets": {
            "set": [
                {
                    "song": [
                        {"name": "Song A"},
                        {"name": "Song B", "info": "acoustic"},
                    ]
                }
            ]
        },
    }
    base.update(kwargs)
    return base


def _sample_concert(**kwargs) -> dict:
    base = {
        "concert_id": 1,
        "prfnm": "공연명",
        "prfpdfrom": "2024-04-28",
        "prfpdto": "2024-04-28",
        "artist_mbid": "some-mbid-1234",
    }
    base.update(kwargs)
    return base


class TestSetlistCollect:
    def test_collect_returns_list(self):
        """collect() 호출 결과가 리스트여야 한다."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = _make_api_response([_sample_setlist()])

        with patch("collectors.setlist.get_completed_concerts", return_value=[_sample_concert()]):
            with patch("collectors.setlist.requests.get", return_value=mock_response):
                result = collect()

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["concert_id"] == 1
        assert result[0]["setlist_fm_id"] == "abc123def"

    def test_targets_completed_concerts_only(self):
        """prfstate=공연완료 건에 대해서만 수집을 시도해야 한다.

        공연완료 필터링은 get_completed_concerts()가 담당한다.
        해당 함수가 반드시 호출되고, 반환된 항목에 대해서만 API를 호출한다.
        """
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = _make_api_response([])

        with patch("collectors.setlist.get_completed_concerts", return_value=[]) as mock_get:
            with patch("collectors.setlist.requests.get", return_value=mock_response) as mock_req:
                result = collect()

        mock_get.assert_called_once()
        mock_req.assert_not_called()
        assert result == []

    def test_returns_empty_when_no_data(self):
        """setlist.fm에 데이터가 없으면 빈 상태를 유지해야 한다."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = _make_api_response([])

        with patch("collectors.setlist.get_completed_concerts", return_value=[_sample_concert()]):
            with patch("collectors.setlist.requests.get", return_value=mock_response):
                result = collect()

        assert result == []

    def test_returns_empty_on_404(self):
        """setlist.fm API 404 응답 시 빈 상태를 유지해야 한다."""
        http_err = requests.HTTPError()
        http_err.response = MagicMock(status_code=404)

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = http_err

        with patch("collectors.setlist.get_completed_concerts", return_value=[_sample_concert()]):
            with patch("collectors.setlist.requests.get", return_value=mock_response):
                result = collect()

        assert result == []

    def test_request_includes_required_headers(self):
        """x-api-key, Accept: application/json 헤더가 포함되어야 한다."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = _make_api_response([])

        with patch("collectors.setlist.get_completed_concerts", return_value=[_sample_concert()]):
            with patch("collectors.setlist.requests.get", return_value=mock_response) as mock_get:
                collect()

        call_kwargs = mock_get.call_args
        headers = call_kwargs[1].get("headers") or call_kwargs[0][1]
        assert "x-api-key" in headers
        assert headers.get("Accept") == "application/json"


class TestParseTracks:
    def test_parses_songs_in_order(self):
        """sets 안의 song 목록이 순서대로 파싱되어야 한다."""
        sets_data = {
            "set": [
                {
                    "song": [
                        {"name": "Song A"},
                        {"name": "Song B", "info": "acoustic"},
                    ]
                }
            ]
        }
        result = _parse_tracks(sets_data)

        assert len(result) == 2
        assert result[0] == {"position": 1, "song_name": "Song A", "info": None}
        assert result[1] == {"position": 2, "song_name": "Song B", "info": "acoustic"}

    def test_returns_empty_for_empty_sets(self):
        """sets가 비어있으면 빈 리스트를 반환해야 한다."""
        assert _parse_tracks({}) == []
        assert _parse_tracks({"set": []}) == []

    def test_increments_position_across_multiple_sets(self):
        """여러 set에 걸쳐 position이 연속으로 증가해야 한다."""
        sets_data = {
            "set": [
                {"song": [{"name": "Song A"}]},
                {"song": [{"name": "Song B"}]},
            ]
        }
        result = _parse_tracks(sets_data)

        assert result[0]["position"] == 1
        assert result[1]["position"] == 2


class TestEventDateInRange:
    def test_date_within_range(self):
        assert _event_date_in_range("28-04-2024", "2024-04-28", "2024-04-28") is True

    def test_date_before_range(self):
        assert _event_date_in_range("27-04-2024", "2024-04-28", "2024-04-30") is False

    def test_date_after_range(self):
        assert _event_date_in_range("01-05-2024", "2024-04-28", "2024-04-30") is False

    def test_none_dates_always_in_range(self):
        assert _event_date_in_range("28-04-2024", None, None) is True

    def test_invalid_date_returns_false(self):
        assert _event_date_in_range("invalid", "2024-04-28", "2024-04-30") is False
