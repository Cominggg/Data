# 수집 파이프라인 상세

> ERD: https://github.com/Cominggg/Specification/blob/main/spec/erd.md

## ① MusicBrainz 아티스트 수집 (초기 1회)

- 조건: `country=JP`, `tag=j-pop`
- 이름·alias(한/영/일)·url-rels·멤버 구성·데뷔일 저장
- 멤버 구성: `relations` 배열에서 `type: "member of band"` 파싱, `ended` 필드로 전·현 멤버 구분
- 데뷔일: `life-span.begin` 저장 (없으면 null 허용)

## ② 릴리즈 수집 (초기 + 주 1회 갱신)

- release-group별 대표 release MBID 취득 후 트랙·커버 연속 수집
- `first-release-date` 기준 DB에 없는 항목만 INSERT
- 앨범 커버: Cover Art Archive 404 시 null 허용

## ③ KOPIS 수집 (주 1회 이상)

- 조건: `visit=Y`, `genrenm=대중음악(GGGA)`
- 저장 전 `has_match()`로 alias 매칭 공연만 필터링하여 저장 (비매칭 공연은 DB에 저장하지 않음)
- 저장: `prfnm`, `prfcast`, 날짜, 장소, `updatedate`, `relates`(예매처 링크, 없으면 빈 배열)
- 상태 갱신: `updatedate` 변화 감지 시 `prfstate` 갱신 (매일 실행)

## ④ 공연-아티스트 매칭

| 단계 | 기준 | 신뢰도 | 노출 |
|------|------|--------|------|
| 매칭 ① | `prfcast` 각 이름 → Artist alias **완전 일치** | HIGH | 관리자 승인 없이 즉시 노출 |
| 매칭 ② | `prfcast` 각 이름 → `rapidfuzz.fuzz.token_set_ratio` ≥ 85 | LOW | 관리자 승인 후 노출 |
| 매칭 ③ | `prfnm` → `rapidfuzz.fuzz.token_set_ratio` ≥ 85 (prfcast 전체 실패 시 폴백) | LOW | 관리자 승인 후 노출 |

- `has_match()` 통과 공연은 반드시 매칭 ①~③ 중 하나가 성공하므로 별도 검토 큐 없음
- `prfcast` 구분자: `,` `·` `&` `×` `・` `/` — feat/featuring/ft 표기 자동 제거
- `prfcast`에 여러 아티스트 포함 시 각각 개별 매칭 후 모두 `concert_artist`에 INSERT
- 승인 시 alias 학습 → 다음 사이클 자동 매칭률 향상

### concert_artist 테이블

| 컬럼 | 설명 |
|------|------|
| `concert_id` | 공연 FK |
| `artist_id` | 아티스트 FK |
| `confidence` | `HIGH` / `LOW` |
| `matched_by` | `prfcast` / `prfnm` / `manual` |
| `approved` | LOW 매칭의 관리자 승인 여부. HIGH는 항상 `true`. |

## ⑤ setlist.fm 수집 (공연 완료 후 1일 이내)

- 대상: `prfstate=공연완료`
- 데이터 미존재 시 빈 상태 유지
