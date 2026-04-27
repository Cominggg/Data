from unittest.mock import MagicMock, call, patch

import pytest
import requests

from collectors.kopis import _parse_concert, _parse_relates, collect
from db.repository import save_concerts, update_concert_status


def _make_api_response(items: list[dict]) -> dict:
    return {"dbs": {"db": items}}


def _sample_item(**kwargs) -> dict:
    base = {
        "mt20id": "PF123456",
        "prfnm": "공연명",
        "prfcast": "아티스트명",
        "prfpdfrom": "2024.01.01",
        "prfpdto": "2024.01.31",
        "fcltynm": "장소명",
        "prfstate": "공연예정",
        "updatedate": "2024.01.15 12:00:00",
        "relates": {
            "relate": [{"relatenm": "예스24", "relateurl": "https://yes24.com"}]
        },
    }
    base.update(kwargs)
    return base


class TestKopisCollect:
    def test_collect_returns_list(self):
        """collect() 호출 결과가 리스트여야 한다."""
        mock_response = MagicMock()
        mock_response.json.return_value = _make_api_response([_sample_item()])
        mock_response.raise_for_status = MagicMock()

        with patch("collectors.kopis.requests.get", return_value=mock_response):
            result = collect()

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["kopis_id"] == "PF123456"

    def test_filters_visit_concerts_only(self):
        """요청 파라미터에 visit=Y가 포함되어야 한다."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"dbs": {}}
        mock_response.raise_for_status = MagicMock()

        with patch("collectors.kopis.requests.get", return_value=mock_response) as mock_get:
            collect()

        call_kwargs = mock_get.call_args
        params = call_kwargs[1].get("params") or call_kwargs[0][1]
        assert params.get("visit") == "Y"

    def test_filters_popular_music_genre(self):
        """요청 파라미터에 genrenm=GGGA가 포함되어야 한다."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"dbs": {}}
        mock_response.raise_for_status = MagicMock()

        with patch("collectors.kopis.requests.get", return_value=mock_response) as mock_get:
            collect()

        call_kwargs = mock_get.call_args
        params = call_kwargs[1].get("params") or call_kwargs[0][1]
        assert params.get("genrenm") == "GGGA"

    def test_stores_booking_links(self):
        """relates 있을 때 파싱되고 없으면 빈 배열이어야 한다."""
        item_with_relates = _sample_item()
        item_no_relates = _sample_item(mt20id="PF999999", relates="")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = _make_api_response(
            [item_with_relates, item_no_relates]
        )

        with patch("collectors.kopis.requests.get", return_value=mock_response):
            result = collect()

        assert result[0]["relates"] == [
            {"relatenm": "예스24", "relateurl": "https://yes24.com"}
        ]
        assert result[1]["relates"] == []

    def test_detects_status_change_by_updatedate(self):
        """update_concert_status가 호출되면 updatedate 변화를 감지해 prfstate를 갱신한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = (
            "2024.01.10 00:00:00",
        )

        concerts = [
            {
                "kopis_id": "PF123456",
                "prfstate": "공연완료",
                "updatedate": "2024.01.20 12:00:00",
            }
        ]

        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            update_concert_status(concerts)

        update_calls = [
            c for c in mock_session.execute.call_args_list
            if "UPDATE" in str(c.args[0])
        ]
        assert len(update_calls) == 1


class TestParseRelates:
    def test_parses_relate_list(self):
        raw = {
            "relate": [
                {"relatenm": "예스24", "relateurl": "https://yes24.com"},
                {"relatenm": "멜론티켓", "relateurl": "https://ticket.melon.com"},
            ]
        }
        result = _parse_relates(raw)
        assert len(result) == 2
        assert result[0] == {"relatenm": "예스24", "relateurl": "https://yes24.com"}

    def test_normalizes_single_relate_dict(self):
        raw = {"relate": {"relatenm": "예스24", "relateurl": "https://yes24.com"}}
        result = _parse_relates(raw)
        assert len(result) == 1
        assert result[0]["relatenm"] == "예스24"

    def test_returns_empty_list_for_empty_string(self):
        assert _parse_relates("") == []

    def test_returns_empty_list_for_none(self):
        assert _parse_relates(None) == []


class TestSaveConcerts:
    def test_insert_sql_contains_on_conflict(self):
        """INSERT SQL에 ON CONFLICT가 포함되어야 한다."""
        mock_session = MagicMock()

        concerts = [
            {
                "kopis_id": "PF123456",
                "prfnm": "공연명",
                "prfcast": "아티스트명",
                "prfpdfrom": "2024.01.01",
                "prfpdto": "2024.01.31",
                "fcltynm": "장소명",
                "prfstate": "공연예정",
                "updatedate": "2024.01.15 12:00:00",
                "relates": [],
            }
        ]

        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            save_concerts(concerts)

        insert_sqls = [
            str(c.args[0])
            for c in mock_session.execute.call_args_list
            if "INSERT" in str(c.args[0])
        ]
        assert len(insert_sqls) == 1
        assert "ON CONFLICT" in insert_sqls[0]

    def test_relates_serialized_as_json(self):
        """relates 필드가 JSON 문자열로 직렬화되어 저장되어야 한다."""
        mock_session = MagicMock()

        concerts = [
            {
                "kopis_id": "PF123456",
                "prfnm": "공연명",
                "prfcast": "아티스트명",
                "prfpdfrom": "2024.01.01",
                "prfpdto": "2024.01.31",
                "fcltynm": "장소명",
                "prfstate": "공연예정",
                "updatedate": "2024.01.15 12:00:00",
                "relates": [{"relatenm": "예스24", "relateurl": "https://yes24.com"}],
            }
        ]

        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            save_concerts(concerts)

        execute_params = mock_session.execute.call_args_list[0].args[1]
        import json

        parsed = json.loads(execute_params["relates"])
        assert parsed[0]["relatenm"] == "예스24"


class TestUpdateConcertStatus:
    def test_no_update_when_updatedate_unchanged(self):
        """updatedate가 같으면 UPDATE가 실행되지 않아야 한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = (
            "2024.01.15 12:00:00",
        )

        concerts = [
            {
                "kopis_id": "PF123456",
                "prfstate": "공연예정",
                "updatedate": "2024.01.15 12:00:00",
            }
        ]

        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            update_concert_status(concerts)

        update_calls = [
            c for c in mock_session.execute.call_args_list
            if "UPDATE" in str(c.args[0])
        ]
        assert len(update_calls) == 0

    def test_updates_prfstate_and_updatedate_when_changed(self):
        """updatedate가 다르면 prfstate와 updatedate가 UPDATE되어야 한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = (
            "2024.01.10 00:00:00",
        )

        concerts = [
            {
                "kopis_id": "PF123456",
                "prfstate": "공연완료",
                "updatedate": "2024.01.20 12:00:00",
            }
        ]

        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            update_concert_status(concerts)

        update_calls = [
            c for c in mock_session.execute.call_args_list
            if "UPDATE" in str(c.args[0])
        ]
        assert len(update_calls) == 1

        update_params = update_calls[0].args[1]
        assert update_params["prfstate"] == "공연완료"
        assert update_params["updatedate"] == "2024.01.20 12:00:00"


class TestKopisHttpErrors:
    def test_propagates_http_error_on_4xx(self):
        """4xx 응답 시 collect()가 HTTPError를 전파해야 한다."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("404 Not Found")

        with patch("collectors.kopis.requests.get", return_value=mock_response):
            with pytest.raises(requests.HTTPError):
                collect()

    def test_propagates_http_error_on_5xx(self):
        """5xx 응답 시 collect()가 HTTPError를 전파해야 한다."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("500 Internal Server Error")

        with patch("collectors.kopis.requests.get", return_value=mock_response):
            with pytest.raises(requests.HTTPError):
                collect()
