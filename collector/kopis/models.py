from dataclasses import dataclass
from typing import Optional


@dataclass
class ConcertResult:
    kopis_id: str
    title: str
    start_date: str
    end_date: str
    venue: str
    venue_area: Optional[str] = None
    artist_id: Optional[int] = None  # DB artists.id (매핑 후 채워짐)

    @classmethod
    def from_api_response(cls, data: dict) -> "ConcertResult":
        """KOPIS API 응답 dict → ConcertResult.

        KOPIS XML을 파싱한 dict를 기대한다.
        실제 필드명은 KOPIS API 문서(공연목록 조회)를 기준으로 조정할 것.
        """
        return cls(
            kopis_id=data["mt20id"],
            title=data["prfnm"],
            start_date=data["prfpdfrom"],
            end_date=data["prfpdto"],
            venue=data["fcltynm"],
            venue_area=data.get("area"),
        )

    def to_db_dict(self) -> dict:
        return {
            "kopis_id": self.kopis_id,
            "title": self.title,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "venue": self.venue,
            "venue_area": self.venue_area,
            "artist_id": self.artist_id,
        }
