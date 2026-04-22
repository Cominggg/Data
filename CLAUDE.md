# coming-data (jpop-data-collector)

Jpop 아티스트 및 내한공연 수집 파이프라인 (KOPIS / MusicBrainz / setlist.fm → DB)

## 레포지토리 구조

```
jpop-concert-collector/
├── collectors/
│   ├── kopis.py           # KOPIS API 수집
│   ├── musicbrainz.py     # MusicBrainz 아티스트·멤버 수집
│   ├── release.py         # MusicBrainz 릴리즈(앨범·싱글·EP) + 트랙·커버 수집
│   └── setlist.py         # setlist.fm 셋리스트 수집
├── matchers/
│   └── artist_matcher.py  # alias 기반 매칭 로직 (rapidfuzz)
├── db/
│   └── repository.py      # DB 저장 (SQLAlchemy)
├── scheduler.py           # APScheduler 진입점
└── requirements.txt
```

## 코딩 규칙

- DML만 사용 — DDL은 백엔드(Spring) Flyway가 단일 관리
- `logging`만 사용 (`print` 금지)
- `.env` 커밋 금지
- MusicBrainz 모든 요청에 `time.sleep(1.1)` 필수 (Rate Limit: 1 req/sec)
- Cover Art Archive도 1 req/sec 제한 — 동일하게 sleep 적용

## 외부 API 정보

| API | 엔드포인트 | Rate Limit | 비고 |
|-----|-----------|------------|------|
| KOPIS | `GET /openApi/restful/pblprfr` | 없음 | 주 1회 이상 권장 |
| MusicBrainz | `GET /ws/2/artist/`, `/ws/2/release-group/`, `/ws/2/release/` | **1 req/sec** | `time.sleep(1.1)` 필수 |
| Cover Art Archive | `GET https://coverartarchive.org/release-group/{mbid}/front` | 1 req/sec | 404 시 null 허용 |
| setlist.fm | `GET https://api.setlist.fm/rest/1.0/search/setlists` | - | Header: `x-api-key`, `Accept: application/json` 필수 |

## 수집 파이프라인 단계

### ① MusicBrainz 아티스트 수집 (초기 1회)

- 조건: `country=JP`, `tag=j-pop`
- 이름·alias(한/영/일)·url-rels·멤버 구성·데뷔일 저장
- 멤버 구성: `relations` 배열에서 `type: "member of band"` 파싱, `ended` 필드로 전·현 멤버 구분
- 데뷔일: `life-span.begin` 저장 (없으면 null 허용)

### ② 릴리즈 수집 (초기 + 주 1회 갱신)

- release-group별 대표 release MBID 취득 후 트랙·커버 연속 수집
- `first-release-date` 기준 DB에 없는 항목만 INSERT
- 앨범 커버: Cover Art Archive 404 시 null 허용

### ③ KOPIS 수집 (주 1회 이상)

- 조건: `visit=Y`, `genrenm=대중음악(GGGA)`
- 저장: `prfnm`, `prfcast`, 날짜, 장소, `updatedate`, `relates`(예매처 링크, 없으면 빈 배열)
- 상태 갱신: `updatedate` 변화 감지 시 `prfstate` 갱신 (매일 실행)

### ④ 공연-아티스트 매칭

| 단계 | 기준 | 신뢰도 | 노출 |
|------|------|--------|------|
| 매칭 ① | `prfcast` → Artist alias **완전 일치** | HIGH | 관리자 승인 없이 즉시 노출 |
| 매칭 ② | `prfnm` → alias 부분 검색, `rapidfuzz.fuzz.partial_ratio` ≥ 85 | LOW | 관리자 승인 후 노출 |
| 실패 | 두 매칭 모두 실패 | - | 검토 큐 등록 |

- `prfcast`에 여러 아티스트(`,` · `·` 구분) 포함 시 각각 개별 매칭 후 모두 `concert_artist`에 INSERT
- 승인 시 alias 학습 → 다음 사이클 자동 매칭률 향상

### ⑤ setlist.fm 수집 (공연 완료 후 1일 이내)

- 대상: `prfstate=공연완료`
- 데이터 미존재 시 빈 상태 유지

## 공연-아티스트 관계 (concert_artist 테이블)

| 컬럼 | 설명 |
|------|------|
| `concert_id` | 공연 FK |
| `artist_id` | 아티스트 FK |
| `confidence` | `HIGH` / `LOW` |
| `matched_by` | `prfcast` / `prfnm` / `manual` |
| `approved` | LOW 매칭의 관리자 승인 여부. HIGH는 항상 `true`. |
