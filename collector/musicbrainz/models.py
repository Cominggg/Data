from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ArtistResult:
    mbid: str
    name: str
    sort_name: str
    country: Optional[str] = None
    area: Optional[str] = None
    begin_date: Optional[str] = None
    end_date: Optional[str] = None
    artist_type: Optional[str] = None
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_api_response(cls, data: dict) -> "ArtistResult":
        """MusicBrainz API 응답 dict → ArtistResult"""
        life = data.get("life-span", {})
        return cls(
            mbid=data["id"],
            name=data["name"],
            sort_name=data.get("sort-name", data["name"]),
            country=data.get("country"),
            area=data.get("area", {}).get("name") if data.get("area") else None,
            begin_date=life.get("begin"),
            end_date=life.get("end"),
            artist_type=data.get("type"),
            tags=[t["name"] for t in data.get("tags", [])],
        )

    def to_db_dict(self) -> dict:
        """DB insert용 dict로 변환"""
        return {
            "mbid": self.mbid,
            "name": self.name,
            "sort_name": self.sort_name,
            "country": self.country,
            "area": self.area,
            "begin_date": self.begin_date,
            "end_date": self.end_date,
            "artist_type": self.artist_type,
        }
