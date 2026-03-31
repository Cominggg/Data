import logging
import xml.etree.ElementTree as ET

import requests

from collector.config import settings

logger = logging.getLogger(__name__)


class KopisClient:
    """KOPIS OpenAPI 클라이언트.

    KOPIS는 XML 응답을 반환한다. 내부에서 dict 리스트로 변환해 반환한다.
    """

    def __init__(self) -> None:
        self._session = requests.Session()

    def _get_xml(self, endpoint: str, params: dict) -> list[dict]:
        url = f"{settings.kopis_base_url}/{endpoint}"
        params["service"] = settings.kopis_api_key
        logger.debug("KOPIS GET %s params=%s", url, {k: v for k, v in params.items() if k != "service"})
        response = self._session.get(url, params=params, timeout=30)
        response.raise_for_status()
        return self._parse_xml(response.content)

    def _parse_xml(self, content: bytes) -> list[dict]:
        root = ET.fromstring(content)
        return [{child.tag: child.text for child in item} for item in root]

    def get_concerts(
        self,
        start_date: str,
        end_date: str,
        genre_code: str = "GGGA",  # 팝
        page: int = 1,
        rows: int = 100,
    ) -> list[dict]:
        """공연 목록을 조회한다.

        Args:
            start_date: 시작일 (YYYYMMDD)
            end_date: 종료일 (YYYYMMDD)
            genre_code: 장르코드 (기본값: GGGA 팝)
            page: 페이지 번호
            rows: 페이지 당 건수
        """
        return self._get_xml(
            "pblprfr",
            {
                "stdate": start_date,
                "eddate": end_date,
                "genrenm": genre_code,
                "cpage": page,
                "rows": rows,
            },
        )
