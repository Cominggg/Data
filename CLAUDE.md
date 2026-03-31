# jpop-data-collector
Jpop 아티스트 및 내한공연 수집 파이프라인 (KOPIS / MusicBrainz / setlist.fm → DB)

## 규칙
- DML만 사용 (DDL은 백엔드 Flyway)
- MusicBrainz: `time.sleep(1.1)` 필수
- `logging`만 사용 (`print` 금지)
- `.env` 커밋 금지
