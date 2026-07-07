# 수집 파이프라인 상세

> ERD: https://github.com/Cominggg/Specification/blob/main/spec/erd.md

## ① MusicBrainz 아티스트 수집 (초기 1회)

- 조건: `country=JP`, `tag=j-pop`
- 이름·alias(한/영/일)·url-rels·멤버 구성·데뷔일 저장
- 멤버 구성: `relations` 배열에서 `type: "member of band"` 파싱, `ended` 필드로 전·현 멤버 구분
- 데뷔일: `life-span.begin` 저장 (없으면 null 허용)

## ② 릴리즈 수집 (초기 + 매일 05:00 갱신)

- release-group별 대표 release MBID 취득 후 트랙·커버 연속 수집
- `first-release-date` 기준 DB에 없는 항목만 INSERT
- 앨범 커버: Cover Art Archive 404 시 null 허용

## ③ KOPIS 수집 (매일: 상태 갱신 04:00 / 신규 공연 탐지 04:30)

- 조건: `visit=Y`, `genrenm=대중음악(GGGA)`
- 저장 전 `has_match()`로 alias 매칭 공연만 필터링하여 저장 (비매칭 공연은 DB에 저장하지 않음)
- 저장: `prfnm`, `prfcast`, 날짜, 장소, `updatedate`, `relates`(예매처 링크, 없으면 빈 배열)
- 상태 갱신(`run_concert_status_update`): `updatedate` 변화 감지 시 `prfstate` 갱신
- 신규 공연 탐지(`run_new_concert_collect`)는 마지막 수집일 이후 등록·수정된 공연만 증분 조회하며, 완료 후 ④ 매칭까지 같은 잡 안에서 수행한다

## ④ 공연-아티스트 매칭

- 매칭 대상: `concert.title`(KOPIS `prfnm`)만 사용한다 — `prfcast`는 매칭에 쓰지 않는다
- 매칭 방식(`matchers/artist_matcher.py`): 정규화 후 구문(phrase) 일치
  - 단일 단어 alias: 정규화된 title token set에서 완전 일치
  - 다중 단어 alias: 공백 padding 기반 구문 포함 검사 (단어 경계 보장)
  - artist_id별로 가장 긴 매칭 alias를 채택해 특이도를 최대화하며, 복수 아티스트가 매칭되면 모두 반환
- rapidfuzz는 사용하지 않는다 (매칭 정확도 문제로 제거됨) — 신뢰도(HIGH/LOW) 등급 구분 없이 모든 매칭을 동일하게 처리한다
- `has_match()`(저장 전 boolean 필터)와 `match_concert()`(concert_id·artist_id 페어 반환)는 동일한 phrase-matching 로직을 공유한다
- 저장 대상은 수집 경로에 따라 갈린다:
  - 자동 배치 수집(`run_new_concert_collect`, 매일): 매칭 결과를 `concert_artist_candidate`(관리자 검수 대기)에 저장
  - 단건 API 수집(`collect_and_save_concert`, BE가 `api.py`로 트리거): 매칭 결과를 `concert_artist`에 즉시 저장 (검수 없음)

### concert_artist_candidate 테이블

Data는 `concert_id`, `artist_id`만 INSERT(`ON CONFLICT (concert_id, artist_id) DO NOTHING`)한다. `status`(기본값 `PENDING`) 등 나머지 컬럼은 DB 기본값이며 검수 승인/거절은 BE가 처리한다.

## ⑤ setlist.fm 수집 (매일 06:00, 공연완료 상태 대상)

- 대상: `prfstate=공연완료`
- 데이터 미존재 시 빈 상태 유지
