from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
import requests

from collectors.kopis import _fetch_detail, _parse_concert, _parse_relates, collect
from db.repository import save_concerts, update_concert_status


def _make_api_response(items: list[dict]) -> dict:
    return {"dbs": {"db": items}}


def _make_detail_response(
    kopis_id: str,
    poster: Optional[str] = None,
    adres: Optional[str] = None,
    relates: object = None,
    pcseguidance: Optional[str] = None,
) -> dict:
    db = {"mt20id": kopis_id}
    if poster is not None:
        db["poster"] = poster
    if adres is not None:
        db["adres"] = adres
    if relates is not None:
        db["relates"] = relates
    if pcseguidance is not None:
        db["pcseguidance"] = pcseguidance
    return {"dbs": {"db": db}}


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


def _make_mock_get(list_response: dict, detail_responses: dict[str, dict]):
    """URL 기반으로 목록/상세 응답을 분기하는 mock requests.get."""
    def _mock_get(url, params=None, **kwargs):
        response = MagicMock()
        response.raise_for_status = MagicMock()
        kopis_id = url.split("/")[-1] if url != "http://kopis.or.kr/openApi/restful/pblprfr" else None
        if kopis_id and kopis_id in detail_responses:
            response.json.return_value = detail_responses[kopis_id]
        else:
            response.json.return_value = list_response
        return response
    return _mock_get


class TestKopisCollect:
    def test_collect_returns_list(self):
        """collect() 호출 결과가 리스트여야 한다."""
        item = _sample_item()
        list_resp = _make_api_response([item])
        detail_resp = _make_detail_response("PF123456", poster="http://poster.jpg", adres="서울")

        with patch(
            "collectors.kopis.requests.get",
            side_effect=_make_mock_get(list_resp, {"PF123456": detail_resp}),
        ):
            result = collect()

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["kopis_id"] == "PF123456"

    def test_collect_merges_detail_fields(self):
        """collect() 결과에 poster_url, venue_address가 포함되어야 한다."""
        item = _sample_item()
        list_resp = _make_api_response([item])
        detail_resp = _make_detail_response(
            "PF123456",
            poster="http://poster.jpg",
            adres="서울특별시 강남구",
        )

        with patch(
            "collectors.kopis.requests.get",
            side_effect=_make_mock_get(list_resp, {"PF123456": detail_resp}),
        ):
            result = collect()

        assert result[0]["poster_url"] == "http://poster.jpg"
        assert result[0]["venue_address"] == "서울특별시 강남구"

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

    def test_includes_stdate_param(self):
        """요청 파라미터에 stdate=20200101이 포함되어야 한다."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"dbs": {}}
        mock_response.raise_for_status = MagicMock()

        with patch("collectors.kopis.requests.get", return_value=mock_response) as mock_get:
            collect()

        call_kwargs = mock_get.call_args
        params = call_kwargs[1].get("params") or call_kwargs[0][1]
        assert params.get("stdate") == "20200101"

    def test_includes_eddate_param(self):
        """요청 파라미터에 eddate가 YYYYMMDD 형식으로 포함되어야 한다."""
        import datetime
        mock_response = MagicMock()
        mock_response.json.return_value = {"dbs": {}}
        mock_response.raise_for_status = MagicMock()

        with patch("collectors.kopis.requests.get", return_value=mock_response) as mock_get:
            collect()

        call_kwargs = mock_get.call_args
        params = call_kwargs[1].get("params") or call_kwargs[0][1]
        eddate = params.get("eddate")
        assert eddate is not None
        assert eddate == datetime.date.today().strftime("%Y%m%d")

    def test_stores_booking_links(self):
        """relates 있을 때 파싱되고 없으면 빈 배열이어야 한다."""
        item_with_relates = _sample_item()
        item_no_relates = _sample_item(mt20id="PF999999", relates="")
        list_resp = _make_api_response([item_with_relates, item_no_relates])
        detail_with = _make_detail_response(
            "PF123456",
            relates={"relate": [{"relatenm": "예스24", "relateurl": "https://yes24.com"}]},
        )
        detail_without = _make_detail_response("PF999999")

        with patch(
            "collectors.kopis.requests.get",
            side_effect=_make_mock_get(
                list_resp, {"PF123456": detail_with, "PF999999": detail_without}
            ),
        ):
            result = collect()

        assert result[0]["relates"] == [
            {"relatenm": "예스24", "relateurl": "https://yes24.com"}
        ]
        assert result[1]["relates"] == []

    def test_skips_item_on_detail_api_failure(self):
        """상세 API 실패 시 해당 건을 건너뛰고 나머지 수집을 계속해야 한다."""
        item = _sample_item()
        list_resp = _make_api_response([item])

        def failing_get(url, params=None, **kwargs):
            response = MagicMock()
            response.raise_for_status = MagicMock()
            if url == "http://kopis.or.kr/openApi/restful/pblprfr":
                response.json.return_value = list_resp
            else:
                response.raise_for_status.side_effect = requests.HTTPError("500")
            return response

        with patch("collectors.kopis.requests.get", side_effect=failing_get):
            result = collect()

        assert len(result) == 1
        assert result[0]["kopis_id"] == "PF123456"
        assert result[0]["poster_url"] is None
        assert result[0]["venue_address"] is None

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


class TestFetchDetail:
    def test_returns_poster_url(self):
        """상세 API 응답에서 poster_url을 파싱해야 한다."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = _make_detail_response(
            "PF123456", poster="http://poster.jpg"
        )

        with patch("collectors.kopis.requests.get", return_value=mock_response):
            result = _fetch_detail("PF123456")

        assert result["poster_url"] == "http://poster.jpg"

    def test_returns_venue_address(self):
        """상세 API 응답에서 venue_address(adres)를 파싱해야 한다."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = _make_detail_response(
            "PF123456", adres="서울특별시 강남구 테헤란로"
        )

        with patch("collectors.kopis.requests.get", return_value=mock_response):
            result = _fetch_detail("PF123456")

        assert result["venue_address"] == "서울특별시 강남구 테헤란로"

    def test_returns_relates(self):
        """상세 API 응답에서 relates를 파싱해야 한다."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = _make_detail_response(
            "PF123456",
            relates={"relate": [{"relatenm": "예스24", "relateurl": "https://yes24.com"}]},
        )

        with patch("collectors.kopis.requests.get", return_value=mock_response):
            result = _fetch_detail("PF123456")

        assert result["relates"] == [{"relatenm": "예스24", "relateurl": "https://yes24.com"}]

    def test_returns_price(self):
        """상세 API 응답에서 pcseguidance(price)를 파싱해야 한다."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = _make_detail_response(
            "PF123456", pcseguidance="전석 110,000원"
        )

        with patch("collectors.kopis.requests.get", return_value=mock_response):
            result = _fetch_detail("PF123456")

        assert result["price"] == "전석 110,000원"

    def test_returns_none_when_fields_missing(self):
        """상세 API 응답에 필드가 없으면 poster_url, venue_address, price는 None이어야 한다."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = _make_detail_response("PF123456")

        with patch("collectors.kopis.requests.get", return_value=mock_response):
            result = _fetch_detail("PF123456")

        assert result["poster_url"] is None
        assert result["venue_address"] is None
        assert result["relates"] == []
        assert result["price"] is None

    def test_normalizes_list_db_response(self):
        """db 응답이 리스트일 경우 첫 번째 요소를 사용해야 한다."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "dbs": {
                "db": [
                    {"mt20id": "PF123456", "poster": "http://poster.jpg"},
                    {"mt20id": "PF999999", "poster": "http://other.jpg"},
                ]
            }
        }

        with patch("collectors.kopis.requests.get", return_value=mock_response):
            result = _fetch_detail("PF123456")

        assert result["poster_url"] == "http://poster.jpg"

    def test_calls_correct_detail_url(self):
        """상세 API 호출 시 kopis_id를 포함한 URL을 사용해야 한다."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = _make_detail_response("PF123456")

        with patch("collectors.kopis.requests.get", return_value=mock_response) as mock_get:
            _fetch_detail("PF123456")

        called_url = mock_get.call_args[0][0]
        assert called_url.endswith("/PF123456")

    def test_propagates_http_error(self):
        """상세 API 4xx/5xx 응답 시 HTTPError를 전파해야 한다."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("404 Not Found")

        with patch("collectors.kopis.requests.get", return_value=mock_response):
            with pytest.raises(requests.HTTPError):
                _fetch_detail("PF123456")


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
    def _make_concert(self, **kwargs) -> dict:
        base = {
            "kopis_id": "PF123456",
            "prfnm": "공연명",
            "prfcast": "아티스트명",
            "prfpdfrom": "2024.01.01",
            "prfpdto": "2024.01.31",
            "fcltynm": "장소명",
            "prfstate": "공연예정",
            "updatedate": "2024.01.15 12:00:00",
            "poster_url": None,
            "venue_address": None,
            "price": None,
            "relates": [],
        }
        base.update(kwargs)
        return base

    def test_insert_sql_contains_on_conflict(self):
        """INSERT SQL에 ON CONFLICT가 포함되어야 한다."""
        mock_session = MagicMock()

        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            save_concerts([self._make_concert()])

        insert_sqls = [
            str(c.args[0])
            for c in mock_session.execute.call_args_list
            if "INSERT" in str(c.args[0])
        ]
        assert len(insert_sqls) == 1
        assert "ON CONFLICT" in insert_sqls[0]

    def test_insert_sql_includes_poster_and_address(self):
        """INSERT SQL에 poster_url, venue_address 컬럼이 포함되어야 한다."""
        mock_session = MagicMock()

        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            save_concerts([self._make_concert(
                poster_url="http://poster.jpg",
                venue_address="서울특별시 강남구",
            )])

        insert_sqls = [
            str(c.args[0])
            for c in mock_session.execute.call_args_list
            if "INSERT" in str(c.args[0])
        ]
        assert "poster_url" in insert_sqls[0]
        assert "venue_address" in insert_sqls[0]

    def test_poster_and_address_params_passed(self):
        """INSERT 파라미터에 poster_url, venue_address 값이 전달되어야 한다."""
        mock_session = MagicMock()

        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            save_concerts([self._make_concert(
                poster_url="http://poster.jpg",
                venue_address="서울특별시 강남구",
            )])

        insert_call = [
            c for c in mock_session.execute.call_args_list
            if "INSERT INTO concert" in str(c.args[0])
        ][0]
        params = insert_call.args[1]
        assert params["poster_url"] == "http://poster.jpg"
        assert params["venue_address"] == "서울특별시 강남구"

    def test_insert_sql_includes_price(self):
        """INSERT SQL에 price 컬럼이 포함되어야 한다."""
        mock_session = MagicMock()

        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            save_concerts([self._make_concert(price="전석 110,000원")])

        insert_sqls = [
            str(c.args[0])
            for c in mock_session.execute.call_args_list
            if "INSERT INTO concert" in str(c.args[0])
        ]
        assert "price" in insert_sqls[0]

    def test_price_param_passed(self):
        """INSERT 파라미터에 price 값이 전달되어야 한다."""
        mock_session = MagicMock()

        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            save_concerts([self._make_concert(price="전석 110,000원")])

        insert_call = [
            c for c in mock_session.execute.call_args_list
            if "INSERT INTO concert" in str(c.args[0])
        ][0]
        assert insert_call.args[1]["price"] == "전석 110,000원"

    def test_booking_links_inserted_for_new_concert(self):
        """신규 공연 저장 시 relates가 concert_booking_link 테이블에 별도 INSERT되어야 한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = (1,)

        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            save_concerts([self._make_concert(
                relates=[{"relatenm": "예스24", "relateurl": "https://yes24.com"}]
            )])

        booking_link_inserts = [
            c for c in mock_session.execute.call_args_list
            if "concert_booking_link" in str(c.args[0])
        ]
        assert len(booking_link_inserts) == 1
        params = booking_link_inserts[0].args[1]
        assert params["name"] == "예스24"
        assert params["url"] == "https://yes24.com"

    def test_booking_links_inserted_for_existing_concert(self):
        """기존 공연(INSERT DO NOTHING)도 SELECT fallback으로 booking_link가 INSERT되어야 한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.side_effect = [None, (5,)]

        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            save_concerts([self._make_concert(
                relates=[{"relatenm": "인터파크", "relateurl": "https://interpark.com"}]
            )])

        booking_link_inserts = [
            c for c in mock_session.execute.call_args_list
            if "concert_booking_link" in str(c.args[0])
        ]
        assert len(booking_link_inserts) == 1
        params = booking_link_inserts[0].args[1]
        assert params["concert_id"] == 5

    def test_booking_link_insert_has_on_conflict(self):
        """concert_booking_link INSERT에 ON CONFLICT DO NOTHING이 포함되어야 한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = (1,)

        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            save_concerts([self._make_concert(
                relates=[{"relatenm": "예스24", "relateurl": "https://yes24.com"}]
            )])

        booking_link_sqls = [
            str(c.args[0])
            for c in mock_session.execute.call_args_list
            if "concert_booking_link" in str(c.args[0])
        ]
        assert len(booking_link_sqls) == 1
        assert "ON CONFLICT" in booking_link_sqls[0]


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
        assert update_params["status"] == "공연완료"
        assert update_params["kopis_update_date"] == "2024.01.20 12:00:00"


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
