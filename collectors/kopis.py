import datetime
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_BASE_URL = "http://kopis.or.kr/openApi/restful/pblprfr"
_API_KEY = os.environ.get("KOPIS_API_KEY")
if not _API_KEY:
    raise ValueError("KOPIS_API_KEY 환경변수가 설정되지 않았습니다.")

_DEFAULT_PARAMS = {
    "service": _API_KEY,
    "visit": "Y",
    "genrenm": "GGGA",
    "rows": 100,
}

_DEFAULT_STDATE = "20250101"
_DEFAULT_LOOKAHEAD_DAYS = 365
_SEARCH_STDATE = "20200101"


def _parse_kopis_date(raw: Optional[str]) -> Optional[str]:
    """KOPIS 날짜 문자열을 DB date 컬럼용 YYYY-MM-DD로 정규화.

    "YYYY.MM.DD"              → "YYYY-MM-DD"
    "YYYY.MM.DD HH:MM:SS"     → "YYYY-MM-DD"
    "YYYY-MM-DD HH:MM:SS..."  → "YYYY-MM-DD"
    그 외 / None               → None
    """
    if not raw:
        return None
    m = re.match(r"^(\d{4})[-.](\d{2})[-.](\d{2})", raw)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def _text(elem: ET.Element, tag: str) -> Optional[str]:
    """child 요소의 텍스트를 반환. 없으면 None."""
    child = elem.find(tag)
    return child.text if child is not None else None


def _get(params: dict) -> ET.Element:
    response = requests.get(_BASE_URL, params=params, timeout=30)
    response.raise_for_status()
    try:
        return ET.fromstring(response.content)
    except ET.ParseError as e:
        logger.error("KOPIS 리스트 XML 파싱 실패: %s", e)
        raise


def _parse_relates(relates_elem: Optional[ET.Element]) -> list[dict]:
    """relates XML 요소에서 예매처 링크 목록을 추출한다. 없으면 [] 반환."""
    if relates_elem is None:
        return []
    return [
        {"relatenm": _text(r, "relatenm"), "relateurl": _text(r, "relateurl")}
        for r in relates_elem.findall("relate")
    ]


_DETAIL_FALLBACK = {
    "prfcast": None, "poster_url": None, "price": None,
    "relates": [], "updatedate": None, "visit": None, "still_urls": [],
}
_DETAIL_WORKERS = 8


def _fetch_detail(kopis_id: str) -> dict:
    """단건 상세 API를 호출해 poster_url, venue_address, relates, price, updatedate를 반환한다."""
    url = f"{_BASE_URL}/{kopis_id}"
    response = requests.get(url, params={"service": _API_KEY}, timeout=30)
    response.raise_for_status()
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as e:
        # 이스케이프되지 않은 특수문자(&, < 등) 포함 시 발생 — 폴백 적용
        logger.warning("상세 API XML 파싱 실패 — 폴백 적용: kopis_id=%s, %s", kopis_id, e)
        return _DETAIL_FALLBACK
    db = root.find("db")
    if db is None:
        return _DETAIL_FALLBACK
    styurls_elem = db.find("styurls")
    still_urls = (
        [el.text for el in styurls_elem.findall("styurl") if el.text]
        if styurls_elem is not None else []
    )
    return {
        "prfcast": _text(db, "prfcast"),
        "poster_url": _text(db, "poster"),
        "relates": _parse_relates(db.find("relates")),
        "price": _text(db, "pcseguidance"),
        "updatedate": _parse_kopis_date(_text(db, "updatedate")),
        "visit": _text(db, "visit"),
        "still_urls": still_urls,
    }


def _parse_concert(item: ET.Element) -> dict:
    return {
        "kopis_id": _text(item, "mt20id"),
        "prfnm": _text(item, "prfnm"),
        "prfcast": _text(item, "prfcast"),
        "prfpdfrom": _parse_kopis_date(_text(item, "prfpdfrom")),
        "prfpdto": _parse_kopis_date(_text(item, "prfpdto")),
        "fcltynm": _text(item, "fcltynm"),
        "prfstate": _text(item, "prfstate"),
        "updatedate": _parse_kopis_date(_text(item, "updatedate")),
        "relates": _parse_relates(item.find("relates")),
    }


def search_concerts(title: str) -> list[dict]:
    """공연명으로 KOPIS 검색. 2020-01-01~1년 후 범위, 최대 20건 반환."""
    today = datetime.date.today()
    stdate = _SEARCH_STDATE
    eddate = (today + datetime.timedelta(days=_DEFAULT_LOOKAHEAD_DAYS)).strftime("%Y%m%d")
    params = {
        **_DEFAULT_PARAMS,
        "prfnm": title,
        "stdate": stdate,
        "eddate": eddate,
        "cpage": 1,
        "rows": 20,
    }
    try:
        root = _get(params)
    except (requests.RequestException, ET.ParseError) as e:
        logger.error("KOPIS 공연 검색 실패 title=%s: %s", title, e)
        return []
    return [
        {
            "kopis_id": _text(item, "mt20id"),
            "title": _text(item, "prfnm"),
            "start_date": _parse_kopis_date(_text(item, "prfpdfrom")),
            "end_date": _parse_kopis_date(_text(item, "prfpdto")),
            "venue": _text(item, "fcltynm"),
        }
        for item in root.findall("db")
    ]


def collect_by_id(kopis_id: str) -> Optional[dict]:
    """단건 kopis_id로 공연 상세 데이터를 수집한다. 데이터 없거나 파싱 실패 시 None 반환."""
    url = f"{_BASE_URL}/{kopis_id}"
    response = requests.get(url, params={"service": _API_KEY}, timeout=30)
    response.raise_for_status()
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as e:
        logger.warning("단건 XML 파싱 실패: kopis_id=%s, %s", kopis_id, e)
        return None
    db = root.find("db")
    if db is None:
        return None
    styurls_elem = db.find("styurls")
    still_urls = (
        [el.text for el in styurls_elem.findall("styurl") if el.text]
        if styurls_elem is not None else []
    )
    return {
        "kopis_id": _text(db, "mt20id") or kopis_id,
        "prfnm": _text(db, "prfnm"),
        "prfcast": _text(db, "prfcast"),
        "prfpdfrom": _parse_kopis_date(_text(db, "prfpdfrom")),
        "prfpdto": _parse_kopis_date(_text(db, "prfpdto")),
        "fcltynm": _text(db, "fcltynm"),
        "prfstate": _text(db, "prfstate"),
        "poster_url": _text(db, "poster"),
        "price": _text(db, "pcseguidance"),
        "relates": _parse_relates(db.find("relates")),
        "updatedate": _parse_kopis_date(_text(db, "updatedate")),
        "visit": _text(db, "visit"),
        "still_urls": still_urls,
    }


def _fetch_and_merge(concert: dict) -> Optional[dict]:
    """상세 API를 호출해 concert에 병합. visit!=Y이면 None 반환."""
    for attempt in range(1, 4):
        try:
            detail = _fetch_detail(concert["kopis_id"])
            concert.update(detail)
            break
        except requests.RequestException as e:
            if attempt == 3:
                logger.warning(
                    "상세 API 3회 실패 — 폴백 적용: kopis_id=%s, %s",
                    concert["kopis_id"], e,
                )
                concert.update({
                    "poster_url": None, "price": None,
                    "relates": [], "updatedate": None, "visit": None,
                    "still_urls": [],
                })
            else:
                logger.debug(
                    "상세 API 재시도 %d/3: kopis_id=%s, %s",
                    attempt, concert["kopis_id"], e,
                )
                time.sleep(5 * attempt)
    if concert.get("visit") != "Y":
        logger.debug(
            "내한 공연 아님 — 제외: kopis_id=%s, prfnm=%s", concert["kopis_id"], concert["prfnm"]
        )
        return None
    return concert


def collect(stdate: Optional[str] = None, eddate: Optional[str] = None) -> list[dict]:
    """KOPIS에서 내한공연 목록을 전 페이지 순회해 반환한다.

    stdate 미전달 시 _DEFAULT_STDATE(2025-01-01)를 시작일로 사용한다.
    eddate 미전달 시 오늘 기준 _DEFAULT_LOOKAHEAD_DAYS일 후를 종료일로 사용한다.
    """
    logger.info("KOPIS 공연 수집 시작")
    results = []
    cpage = 1
    today = datetime.date.today()
    resolved_stdate = stdate or _DEFAULT_STDATE
    lookahead = today + datetime.timedelta(days=_DEFAULT_LOOKAHEAD_DAYS)
    resolved_eddate = eddate or lookahead.strftime("%Y%m%d")

    while True:
        logger.debug("KOPIS 페이지 조회: cpage=%d", cpage)
        params = {
            **_DEFAULT_PARAMS, "cpage": cpage,
            "stdate": resolved_stdate, "eddate": resolved_eddate,
        }

        root = None
        for attempt in range(1, 4):
            try:
                root = _get(params)
                break
            except requests.HTTPError as e:
                status = e.response.status_code if e.response is not None else None
                if attempt == 3:
                    if status == 400:
                        logger.info(
                            "KOPIS 400 응답 — 마지막 페이지로 간주하고 수집 종료: cpage=%d", cpage
                        )
                        return results
                    raise
                logger.warning(
                    "KOPIS 페이지 조회 실패 (attempt %d/3, status=%s): cpage=%d",
                    attempt, status, cpage,
                )
                time.sleep(2 ** attempt)

        batch = root.findall("db")
        if not batch:
            break

        concerts_to_fetch = [
            _parse_concert(item)
            for item in batch
            if _text(item, "genrenm") == "대중음악"
        ]

        with ThreadPoolExecutor(max_workers=_DETAIL_WORKERS) as pool:
            futures = [pool.submit(_fetch_and_merge, c) for c in concerts_to_fetch]
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    results.append(result)

        logger.info("KOPIS 수집 중: cpage=%d, 누적 %d건", cpage, len(results))
        cpage += 1

        if len(batch) < _DEFAULT_PARAMS["rows"]:
            break

    logger.info("KOPIS 공연 수집 완료: 총 %d건", len(results))
    return results
