import datetime
import logging
import os
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
    "outfmt": "json",
    "stdate": "20200101",
}


def _get(params: dict) -> dict:
    response = requests.get(_BASE_URL, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def _parse_relates(raw: object) -> list[dict]:
    """relates 필드가 없거나 빈 문자열이면 [] 반환."""
    if not raw or not isinstance(raw, dict):
        return []
    relate = raw.get("relate")
    if not relate:
        return []
    # relate 가 단일 객체일 때도 리스트로 정규화
    if isinstance(relate, dict):
        relate = [relate]
    return [{"relatenm": r.get("relatenm"), "relateurl": r.get("relateurl")} for r in relate]


def _fetch_detail(kopis_id: str) -> dict:
    """단건 상세 API를 호출해 poster_url, venue_address, relates를 반환한다."""
    url = f"{_BASE_URL}/{kopis_id}"
    response = requests.get(url, params={"service": _API_KEY, "outfmt": "json"}, timeout=30)
    response.raise_for_status()
    data = response.json()
    db = data.get("dbs", {}).get("db", {})
    if isinstance(db, list):
        db = db[0] if db else {}
    return {
        "poster_url": db.get("poster"),
        "venue_address": db.get("adres"),
        "relates": _parse_relates(db.get("relates")),
    }


def _parse_concert(item: dict) -> dict:
    return {
        "kopis_id": item.get("mt20id"),
        "prfnm": item.get("prfnm"),
        "prfcast": item.get("prfcast"),
        "prfpdfrom": item.get("prfpdfrom"),
        "prfpdto": item.get("prfpdto"),
        "fcltynm": item.get("fcltynm"),
        "prfstate": item.get("prfstate"),
        "updatedate": item.get("updatedate"),
        "relates": _parse_relates(item.get("relates")),
    }


def collect() -> list[dict]:
    """KOPIS에서 내한공연 목록을 전 페이지 순회해 반환한다."""
    logger.info("KOPIS 공연 수집 시작")
    results = []
    cpage = 1
    eddate = datetime.date.today().strftime("%Y%m%d")

    while True:
        logger.debug("KOPIS 페이지 조회: cpage=%d", cpage)
        params = {**_DEFAULT_PARAMS, "cpage": cpage, "eddate": eddate}
        data = _get(params)

        batch: Optional[list] = data.get("dbs", {}).get("db")
        # 빈 페이지이거나 dbs 자체가 없으면 순회 종료
        if not batch:
            break

        for item in batch:
            concert = _parse_concert(item)
            detail = _fetch_detail(concert["kopis_id"])
            concert.update(detail)
            results.append(concert)

        logger.info("KOPIS 수집 중: cpage=%d, 누적 %d건", cpage, len(results))
        cpage += 1

        # 마지막 페이지는 rows보다 적게 반환되므로 그 시점에 중단
        if len(batch) < _DEFAULT_PARAMS["rows"]:
            break

    logger.info("KOPIS 공연 수집 완료: 총 %d건", len(results))
    return results
