"""collectors/kopis.py 단위 테스트."""
import xml.etree.ElementTree as ET
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
import requests

from collectors.kopis import (
    _fetch_and_merge,
    _fetch_detail,
    _parse_concert,
    _parse_kopis_date,
    _parse_relates,
    collect,
)
from db.repository import save_concerts, update_concert_status

_LIST_URL = "http://kopis.or.kr/openApi/restful/pblprfr"


# ─── XML 헬퍼 ────────────────────────────────────────────────────────────────

def _make_list_content(*items: dict) -> bytes:
    """목록 API XML 응답 bytes 생성. 각 item은 <db> 필드 dict."""
    root = ET.Element("dbs")
    for fields in items:
        db = ET.SubElement(root, "db")
        for tag, val in fields.items():
            if tag == "relates":
                if val:
                    relates_elem = ET.SubElement(db, "relates")
                    for r in val:
                        rel = ET.SubElement(relates_elem, "relate")
                        ET.SubElement(rel, "relatenm").text = r["relatenm"]
                        ET.SubElement(rel, "relateurl").text = r["relateurl"]
            elif val is not None:
                ET.SubElement(db, tag).text = str(val)
    return ET.tostring(root, encoding="unicode").encode("utf-8")


def _make_detail_content(kopis_id: str, **fields) -> bytes:
    """상세 API XML 응답 bytes 생성."""
    root = ET.Element("dbs")
    db = ET.SubElement(root, "db")
    ET.SubElement(db, "mt20id").text = kopis_id
    for tag, val in fields.items():
        if tag == "relates":
            if val:
                relates_elem = ET.SubElement(db, "relates")
                for r in val:
                    rel = ET.SubElement(relates_elem, "relate")
                    ET.SubElement(rel, "relatenm").text = r["relatenm"]
                    ET.SubElement(rel, "relateurl").text = r["relateurl"]
        elif tag == "styurls":
            if val:
                styurls_elem = ET.SubElement(db, "styurls")
                for url in val:
                    ET.SubElement(styurls_elem, "styurl").text = url
        elif val is not None:
            ET.SubElement(db, tag).text = str(val)
    return ET.tostring(root, encoding="unicode").encode("utf-8")


def _mock_get_factory(list_content: bytes, detail_map: Optional[dict] = None):
    """URL 기반으로 목록/상세 응답을 분기하는 requests.get side_effect."""
    detail_map = detail_map or {}

    def _side_effect(url, params=None, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        kopis_id = url.split("/")[-1] if url != _LIST_URL else None
        resp.content = detail_map.get(kopis_id, list_content) if kopis_id else list_content
        return resp

    return _side_effect


def _sample_item(**overrides) -> dict:
    """목록 API 단일 <db> 항목 기본값."""
    base = {
        "mt20id": "PF123456",
        "prfnm": "공연명",
        "prfcast": "아티스트명",
        "prfpdfrom": "2024.01.01",
        "prfpdto": "2024.01.31",
        "fcltynm": "장소명",
        "prfstate": "공연예정",
        "updatedate": "2024.01.15 12:00:00",
        "genrenm": "대중음악",
    }
    base.update(overrides)
    return base


def _make_db_elem(**fields) -> ET.Element:
    """_parse_concert 테스트용 <db> ET.Element 생성."""
    db = ET.Element("db")
    for tag, val in fields.items():
        child = ET.SubElement(db, tag)
        if val is not None:
            child.text = str(val)
    return db


# ─── TestFetchAndMerge ────────────────────────────────────────────────────────

class TestFetchAndMerge:
    def test_returns_merged_concert_when_visit_y(self):
        """detail 병합 후 visit=Y이면 concert dict를 반환해야 한다."""
        concert = {"kopis_id": "PF123456", "prfnm": "공연명"}
        detail = {
            "visit": "Y", "poster_url": "http://poster.jpg",
            "venue_address": None, "price": None, "relates": [],
            "updatedate": "2024-01-15", "prfcast": "아티스트",
        }
        with patch("collectors.kopis._fetch_detail", return_value=detail):
            result = _fetch_and_merge(concert)

        assert result is not None
        assert result["poster_url"] == "http://poster.jpg"
        assert result["visit"] == "Y"

    def test_returns_none_when_visit_not_y(self):
        """visit!=Y이면 None을 반환해야 한다."""
        concert = {"kopis_id": "PF123456", "prfnm": "공연명"}
        detail = {
            "visit": "N", "poster_url": None, "venue_address": None,
            "price": None, "relates": [], "updatedate": None, "prfcast": None,
        }
        with patch("collectors.kopis._fetch_detail", return_value=detail):
            result = _fetch_and_merge(concert)

        assert result is None

    def test_retries_on_request_exception(self):
        """RequestException 발생 시 최대 3회까지 재시도해야 한다."""
        concert = {"kopis_id": "PF123456", "prfnm": "공연명"}
        call_count = {"n": 0}

        def flaky_fetch(kopis_id):
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise requests.ConnectionError("timeout")
            return {
                "visit": "Y", "poster_url": "http://poster.jpg",
                "venue_address": None, "price": None, "relates": [],
                "updatedate": None, "prfcast": None,
            }

        with patch("collectors.kopis._fetch_detail", side_effect=flaky_fetch):
            with patch("collectors.kopis.time.sleep"):
                result = _fetch_and_merge(concert)

        assert result is not None
        assert call_count["n"] == 3

    def test_returns_none_after_three_failures(self):
        """3회 연속 실패 시 폴백(visit=None)이 적용되어 None을 반환해야 한다."""
        concert = {"kopis_id": "PF123456", "prfnm": "공연명"}

        with patch(
            "collectors.kopis._fetch_detail", side_effect=requests.ConnectionError("timeout")
        ):
            with patch("collectors.kopis.time.sleep"):
                result = _fetch_and_merge(concert)

        assert result is None

    def test_applies_fallback_fields_after_three_failures(self):
        """3회 연속 실패 시 poster_url·relates 등이 None·빈배열로 설정되어야 한다."""
        concert = {"kopis_id": "PF123456", "prfnm": "공연명"}

        with patch(
            "collectors.kopis._fetch_detail", side_effect=requests.ConnectionError("timeout")
        ):
            with patch("collectors.kopis.time.sleep"):
                _fetch_and_merge(concert)

        assert concert.get("poster_url") is None
        assert concert.get("relates") == []

    def test_fallback_sets_empty_still_urls(self):
        """3회 연속 실패 시 still_urls가 빈 리스트로 설정되어야 한다."""
        concert = {"kopis_id": "PF123456", "prfnm": "공연명"}

        with patch(
            "collectors.kopis._fetch_detail", side_effect=requests.ConnectionError("timeout")
        ):
            with patch("collectors.kopis.time.sleep"):
                _fetch_and_merge(concert)

        assert concert.get("still_urls") == []


# ─── TestKopisCollect ─────────────────────────────────────────────────────────

class TestKopisCollect:
    def test_collect_returns_list(self):
        """collect() 호출 결과가 리스트여야 한다."""
        list_content = _make_list_content(_sample_item())
        detail_content = _make_detail_content(
            "PF123456", poster="http://poster.jpg", adres="서울", visit="Y"
        )

        with patch("collectors.kopis.requests.get",
                   side_effect=_mock_get_factory(list_content, {"PF123456": detail_content})):
            result = collect()

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["kopis_id"] == "PF123456"

    def test_collect_merges_detail_fields(self):
        """collect() 결과에 poster_url, venue_address가 포함되어야 한다."""
        list_content = _make_list_content(_sample_item())
        detail_content = _make_detail_content(
            "PF123456", poster="http://poster.jpg", adres="서울특별시 강남구", visit="Y"
        )

        with patch("collectors.kopis.requests.get",
                   side_effect=_mock_get_factory(list_content, {"PF123456": detail_content})):
            result = collect()

        assert result[0]["poster_url"] == "http://poster.jpg"
        assert result[0]["venue_address"] == "서울특별시 강남구"

    def test_filters_visit_concerts_only(self):
        """요청 파라미터에 visit=Y가 포함되어야 한다."""
        with patch("collectors.kopis.requests.get") as mock_get:
            mock_get.return_value.content = b"<dbs></dbs>"
            mock_get.return_value.raise_for_status = MagicMock()
            collect()

        params = mock_get.call_args[1].get("params") or mock_get.call_args[0][1]
        assert params.get("visit") == "Y"

    def test_filters_popular_music_genre(self):
        """요청 파라미터에 genrenm=GGGA가 포함되어야 한다."""
        with patch("collectors.kopis.requests.get") as mock_get:
            mock_get.return_value.content = b"<dbs></dbs>"
            mock_get.return_value.raise_for_status = MagicMock()
            collect()

        params = mock_get.call_args[1].get("params") or mock_get.call_args[0][1]
        assert params.get("genrenm") == "GGGA"

    def test_includes_stdate_param(self):
        """요청 파라미터에 stdate=20200101이 포함되어야 한다."""
        with patch("collectors.kopis.requests.get") as mock_get:
            mock_get.return_value.content = b"<dbs></dbs>"
            mock_get.return_value.raise_for_status = MagicMock()
            collect()

        params = mock_get.call_args[1].get("params") or mock_get.call_args[0][1]
        assert params.get("stdate") == "20200101"

    def test_includes_eddate_param(self):
        """요청 파라미터에 eddate가 YYYYMMDD 형식으로 포함되어야 한다."""
        import datetime
        with patch("collectors.kopis.requests.get") as mock_get:
            mock_get.return_value.content = b"<dbs></dbs>"
            mock_get.return_value.raise_for_status = MagicMock()
            collect()

        params = mock_get.call_args[1].get("params") or mock_get.call_args[0][1]
        assert params.get("eddate") == datetime.date.today().strftime("%Y%m%d")

    def test_collect_includes_still_urls(self):
        """collect() 결과 concert dict에 still_urls가 포함되어야 한다."""
        list_content = _make_list_content(_sample_item())
        detail_content = _make_detail_content(
            "PF123456",
            visit="Y",
            styurls=["http://still1.jpg", "http://still2.jpg"],
        )

        with patch("collectors.kopis.requests.get",
                   side_effect=_mock_get_factory(list_content, {"PF123456": detail_content})):
            result = collect()

        assert result[0]["still_urls"] == ["http://still1.jpg", "http://still2.jpg"]

    def test_collect_still_urls_empty_when_absent(self):
        """<styurls> 없을 때 still_urls가 빈 리스트여야 한다."""
        list_content = _make_list_content(_sample_item())
        detail_content = _make_detail_content("PF123456", visit="Y")

        with patch("collectors.kopis.requests.get",
                   side_effect=_mock_get_factory(list_content, {"PF123456": detail_content})):
            result = collect()

        assert result[0]["still_urls"] == []

    def test_stores_booking_links(self):
        """relates가 있을 때 파싱되고 없으면 빈 배열이어야 한다."""
        list_content = _make_list_content(
            _sample_item(mt20id="PF001"),
            _sample_item(mt20id="PF002"),
        )
        detail_with = _make_detail_content(
            "PF001", visit="Y",
            relates=[{"relatenm": "예스24", "relateurl": "https://yes24.com"}],
        )
        detail_without = _make_detail_content("PF002", visit="Y")

        with patch("collectors.kopis.requests.get", side_effect=_mock_get_factory(
            list_content, {"PF001": detail_with, "PF002": detail_without}
        )):
            result = collect()

        result_by_id = {r["kopis_id"]: r for r in result}
        assert result_by_id["PF001"]["relates"] == [
            {"relatenm": "예스24", "relateurl": "https://yes24.com"}
        ]
        assert result_by_id["PF002"]["relates"] == []

    def test_excludes_concert_when_detail_api_fails(self):
        """상세 API 3회 실패 시 visit 미확인으로 공연이 제외되어야 한다."""
        list_content = _make_list_content(_sample_item())

        def failing_get(url, params=None, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if url == _LIST_URL:
                resp.content = list_content
            else:
                resp.raise_for_status.side_effect = requests.HTTPError("500")
            return resp

        with patch("collectors.kopis.requests.get", side_effect=failing_get):
            with patch("collectors.kopis.time.sleep"):
                result = collect()

        assert result == []

    def test_excludes_non_visit_y_concerts(self):
        """detail API의 visit!=Y인 공연은 결과에서 제외되어야 한다."""
        list_content = _make_list_content(
            _sample_item(mt20id="PF001"),
            _sample_item(mt20id="PF002"),
        )
        detail_y = _make_detail_content("PF001", visit="Y")
        detail_n = _make_detail_content("PF002", visit="N")

        with patch("collectors.kopis.requests.get", side_effect=_mock_get_factory(
            list_content, {"PF001": detail_y, "PF002": detail_n}
        )):
            result = collect()

        assert len(result) == 1
        assert result[0]["kopis_id"] == "PF001"

    def test_fetches_multiple_concerts(self):
        """여러 공연의 상세 정보가 모두 수집되어야 한다."""
        list_content = _make_list_content(
            _sample_item(mt20id="PF001", prfnm="공연1"),
            _sample_item(mt20id="PF002", prfnm="공연2"),
        )
        detail1 = _make_detail_content("PF001", visit="Y", poster="http://p1.jpg")
        detail2 = _make_detail_content("PF002", visit="Y", poster="http://p2.jpg")

        with patch("collectors.kopis.requests.get", side_effect=_mock_get_factory(
            list_content, {"PF001": detail1, "PF002": detail2}
        )):
            result = collect()

        assert len(result) == 2
        kopis_ids = {r["kopis_id"] for r in result}
        assert kopis_ids == {"PF001", "PF002"}

    def test_detects_status_change_by_updatedate(self):
        """update_concert_status가 호출되면 updatedate 변화를 감지해 prfstate를 갱신한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = ("2024-01-10",)

        concerts = [{"kopis_id": "PF123456", "prfstate": "공연완료", "updatedate": "2024-01-20"}]

        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            update_concert_status(concerts)

        update_calls = [
            c for c in mock_session.execute.call_args_list if "UPDATE" in str(c.args[0])
        ]
        assert len(update_calls) == 1


# ─── TestKopisDetailRetry ─────────────────────────────────────────────────────

class TestKopisDetailRetry:
    def test_retries_on_network_error_then_succeeds(self):
        """상세 API 네트워크 오류 후 재시도에서 성공 시 결과에 포함되어야 한다."""
        list_content = _make_list_content(_sample_item())
        detail_content = _make_detail_content("PF123456", poster="http://poster.jpg", visit="Y")
        call_count = {"n": 0}

        def flaky_get(url, params=None, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if url == _LIST_URL:
                resp.content = list_content
                return resp
            call_count["n"] += 1
            if call_count["n"] == 1:
                resp.raise_for_status.side_effect = requests.ConnectionError("timeout")
            else:
                resp.content = detail_content
            return resp

        with patch("collectors.kopis.requests.get", side_effect=flaky_get):
            with patch("collectors.kopis.time.sleep"):
                result = collect()

        assert len(result) == 1
        assert result[0]["poster_url"] == "http://poster.jpg"


# ─── TestFetchDetail ──────────────────────────────────────────────────────────

class TestFetchDetail:
    def _mock_resp(self, content: bytes) -> MagicMock:
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.content = content
        return resp

    def test_returns_poster_url(self):
        """상세 API 응답에서 poster_url을 파싱해야 한다."""
        content = _make_detail_content("PF123456", poster="http://poster.jpg", visit="Y")
        with patch("collectors.kopis.requests.get", return_value=self._mock_resp(content)):
            result = _fetch_detail("PF123456")

        assert result["poster_url"] == "http://poster.jpg"

    def test_returns_venue_address(self):
        """상세 API 응답에서 venue_address(adres)를 파싱해야 한다."""
        content = _make_detail_content("PF123456", adres="서울특별시 강남구 테헤란로", visit="Y")
        with patch("collectors.kopis.requests.get", return_value=self._mock_resp(content)):
            result = _fetch_detail("PF123456")

        assert result["venue_address"] == "서울특별시 강남구 테헤란로"

    def test_returns_relates(self):
        """상세 API 응답에서 relates를 파싱해야 한다."""
        content = _make_detail_content(
            "PF123456", visit="Y",
            relates=[{"relatenm": "예스24", "relateurl": "https://yes24.com"}],
        )
        with patch("collectors.kopis.requests.get", return_value=self._mock_resp(content)):
            result = _fetch_detail("PF123456")

        assert result["relates"] == [{"relatenm": "예스24", "relateurl": "https://yes24.com"}]

    def test_returns_price(self):
        """상세 API 응답에서 pcseguidance(price)를 파싱해야 한다."""
        content = _make_detail_content("PF123456", pcseguidance="전석 110,000원", visit="Y")
        with patch("collectors.kopis.requests.get", return_value=self._mock_resp(content)):
            result = _fetch_detail("PF123456")

        assert result["price"] == "전석 110,000원"

    def test_returns_none_when_fields_missing(self):
        """상세 API 응답에 필드가 없으면 poster_url, venue_address, price는 None이어야 한다."""
        content = _make_detail_content("PF123456", visit="Y")
        with patch("collectors.kopis.requests.get", return_value=self._mock_resp(content)):
            result = _fetch_detail("PF123456")

        assert result["poster_url"] is None
        assert result["venue_address"] is None
        assert result["relates"] == []
        assert result["price"] is None

    def test_uses_first_db_when_multiple(self):
        """dbs 안에 db가 여러 개일 때 첫 번째 db를 사용해야 한다."""
        root = ET.Element("dbs")
        db1 = ET.SubElement(root, "db")
        ET.SubElement(db1, "poster").text = "http://first.jpg"
        db2 = ET.SubElement(root, "db")
        ET.SubElement(db2, "poster").text = "http://second.jpg"
        content = ET.tostring(root, encoding="unicode").encode("utf-8")

        with patch("collectors.kopis.requests.get", return_value=self._mock_resp(content)):
            result = _fetch_detail("PF123456")

        assert result["poster_url"] == "http://first.jpg"

    def test_calls_correct_detail_url(self):
        """상세 API 호출 시 kopis_id를 포함한 URL을 사용해야 한다."""
        content = _make_detail_content("PF123456", visit="Y")
        with patch(
            "collectors.kopis.requests.get", return_value=self._mock_resp(content)
        ) as mock_get:
            _fetch_detail("PF123456")

        called_url = mock_get.call_args[0][0]
        assert called_url.endswith("/PF123456")

    def test_returns_still_urls(self):
        """상세 API 응답의 <styurls>/<styurl>이 still_urls 리스트로 파싱되어야 한다."""
        content = _make_detail_content(
            "PF123456",
            visit="Y",
            styurls=["http://still1.jpg", "http://still2.jpg"],
        )
        with patch("collectors.kopis.requests.get", return_value=self._mock_resp(content)):
            result = _fetch_detail("PF123456")

        assert result["still_urls"] == ["http://still1.jpg", "http://still2.jpg"]

    def test_returns_empty_still_urls_when_absent(self):
        """<styurls> 요소가 없으면 still_urls가 빈 리스트여야 한다."""
        content = _make_detail_content("PF123456", visit="Y")
        with patch("collectors.kopis.requests.get", return_value=self._mock_resp(content)):
            result = _fetch_detail("PF123456")

        assert result["still_urls"] == []

    def test_propagates_http_error(self):
        """상세 API 4xx/5xx 응답 시 HTTPError를 전파해야 한다."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("404 Not Found")

        with patch("collectors.kopis.requests.get", return_value=mock_response):
            with pytest.raises(requests.HTTPError):
                _fetch_detail("PF123456")


# ─── TestParseKopisDate ───────────────────────────────────────────────────────

class TestParseKopisDate:
    def test_dot_date_normalized(self):
        assert _parse_kopis_date("2024.01.15") == "2024-01-15"

    def test_datetime_string_strips_time(self):
        assert _parse_kopis_date("2024.01.15 12:00:00") == "2024-01-15"

    def test_none_returns_none(self):
        assert _parse_kopis_date(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_kopis_date("") is None

    def test_non_date_format_returns_none(self):
        assert _parse_kopis_date("01/15/2024") is None

    def test_parse_concert_applies_normalization(self):
        """_parse_concert 결과에서 날짜 필드가 YYYY-MM-DD 형식이어야 한다."""
        item = _make_db_elem(
            mt20id="PF123456",
            prfnm="공연명",
            prfpdfrom="2024.01.01",
            prfpdto="2024.01.31",
            updatedate="2024.01.15 12:00:00",
        )
        result = _parse_concert(item)
        assert result["prfpdfrom"] == "2024-01-01"
        assert result["prfpdto"] == "2024-01-31"
        assert result["updatedate"] == "2024-01-15"


# ─── TestParseRelates ─────────────────────────────────────────────────────────

class TestParseRelates:
    def _make_relates_elem(self, relates: list) -> ET.Element:
        elem = ET.Element("relates")
        for r in relates:
            rel = ET.SubElement(elem, "relate")
            ET.SubElement(rel, "relatenm").text = r.get("relatenm")
            ET.SubElement(rel, "relateurl").text = r.get("relateurl")
        return elem

    def test_parses_relate_list(self):
        elem = self._make_relates_elem([
            {"relatenm": "예스24", "relateurl": "https://yes24.com"},
            {"relatenm": "멜론티켓", "relateurl": "https://ticket.melon.com"},
        ])
        result = _parse_relates(elem)
        assert len(result) == 2
        assert result[0] == {"relatenm": "예스24", "relateurl": "https://yes24.com"}

    def test_parses_single_relate(self):
        elem = self._make_relates_elem([{"relatenm": "예스24", "relateurl": "https://yes24.com"}])
        result = _parse_relates(elem)
        assert len(result) == 1
        assert result[0]["relatenm"] == "예스24"

    def test_empty_relates_elem_returns_empty(self):
        elem = ET.Element("relates")
        result = _parse_relates(elem)
        assert result == []

    def test_returns_empty_list_for_none(self):
        assert _parse_relates(None) == []


# ─── TestSaveConcerts ─────────────────────────────────────────────────────────

class TestSaveConcerts:
    def _make_concert(self, **kwargs) -> dict:
        base = {
            "kopis_id": "PF123456",
            "prfnm": "공연명",
            "prfcast": "아티스트명",
            "prfpdfrom": "2024-01-01",
            "prfpdto": "2024-01-31",
            "fcltynm": "장소명",
            "prfstate": "공연예정",
            "updatedate": "2024-01-15",
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
            str(c.args[0]) for c in mock_session.execute.call_args_list
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
                poster_url="http://poster.jpg", venue_address="서울특별시 강남구"
            )])

        insert_sqls = [
            str(c.args[0]) for c in mock_session.execute.call_args_list
            if "INSERT INTO concert" in str(c.args[0])
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
                poster_url="http://poster.jpg", venue_address="서울특별시 강남구"
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
            str(c.args[0]) for c in mock_session.execute.call_args_list
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
        assert booking_link_inserts[0].args[1]["concert_id"] == 5

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
            str(c.args[0]) for c in mock_session.execute.call_args_list
            if "concert_booking_link" in str(c.args[0])
        ]
        assert len(booking_link_sqls) == 1
        assert "ON CONFLICT" in booking_link_sqls[0]

    def test_concert_image_inserted_for_new_concert(self):
        """신규 공연 저장 시 still_urls가 concert_image에 position 순으로 INSERT되어야 한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = (1,)
        concert = self._make_concert(still_urls=["http://still1.jpg", "http://still2.jpg"])
        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            save_concerts([concert])

        image_inserts = [
            c for c in mock_session.execute.call_args_list if "concert_image" in str(c.args[0])
        ]
        assert len(image_inserts) == 2
        assert image_inserts[0].args[1]["url"] == "http://still1.jpg"
        assert image_inserts[0].args[1]["position"] == 0
        assert image_inserts[1].args[1]["url"] == "http://still2.jpg"
        assert image_inserts[1].args[1]["position"] == 1

    def test_concert_image_not_inserted_for_existing_concert(self):
        """기존 공연(RETURNING None)이면 concert_image INSERT가 실행되지 않아야 한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.side_effect = [None, (5,)]
        concert = self._make_concert(still_urls=["http://still1.jpg"])
        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            save_concerts([concert])

        image_inserts = [
            c for c in mock_session.execute.call_args_list if "concert_image" in str(c.args[0])
        ]
        assert len(image_inserts) == 0

    def test_concert_image_not_inserted_when_still_urls_empty(self):
        """still_urls가 빈 리스트이면 concert_image INSERT가 실행되지 않아야 한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = (1,)
        concert = self._make_concert(still_urls=[])
        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            save_concerts([concert])

        image_inserts = [
            c for c in mock_session.execute.call_args_list if "concert_image" in str(c.args[0])
        ]
        assert len(image_inserts) == 0


# ─── TestUpdateConcertStatus ──────────────────────────────────────────────────

class TestUpdateConcertStatus:
    def test_no_update_when_updatedate_unchanged(self):
        """updatedate가 같으면 UPDATE가 실행되지 않아야 한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = ("2024-01-15",)
        concerts = [{"kopis_id": "PF123456", "prfstate": "공연예정", "updatedate": "2024-01-15"}]

        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            update_concert_status(concerts)

        update_calls = [
            c for c in mock_session.execute.call_args_list if "UPDATE" in str(c.args[0])
        ]
        assert len(update_calls) == 0

    def test_updates_prfstate_and_updatedate_when_changed(self):
        """updatedate가 다르면 prfstate와 updatedate가 UPDATE되어야 한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = ("2024-01-10",)
        concerts = [{"kopis_id": "PF123456", "prfstate": "공연완료", "updatedate": "2024-01-20"}]

        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            update_concert_status(concerts)

        update_calls = [
            c for c in mock_session.execute.call_args_list if "UPDATE" in str(c.args[0])
        ]
        assert len(update_calls) == 1
        update_params = update_calls[0].args[1]
        assert update_params["status"] == "공연완료"
        assert update_params["kopis_update_date"] == "2024-01-20"


# ─── TestKopisHttpErrors ──────────────────────────────────────────────────────

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
