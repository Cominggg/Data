# Data 코드 리뷰 체크리스트

## 심각도 기준

| 심각도 | 의미 |
|--------|------|
| 🔴 critical | 즉시 수정 필요 (규칙 위반, 런타임 오류 가능, 외부 API 차단 위험) |
| 🟡 warning  | 개선 권장 (운영 중 장애·누락 가능성, 유지보수성 저하) |
| 🔵 suggestion | 선택적 개선 (테스트 보강, 네이밍) |

---

## 자동 검사

`{FILES}`는 SKILL.md 1단계에서 확정한 대상 파일 목록이다. 매치는 후보일 뿐이므로 diff를 읽고 확정한다
(예: 정규식 문자열 `r"(?:twitter|x)\.com"`도 유니온 패턴에 걸린다).

zsh는 변수를 단어 분리하지 않으므로 `$FILES`로 넘기지 말고 파일 경로를 직접 나열하거나
`printf '%s\n' ... | xargs grep ...` 형태로 실행한다.

```bash
# 1. DDL (critical)
grep -nE '\b(CREATE|ALTER|DROP|TRUNCATE|RENAME)\s+(TABLE|INDEX|SCHEMA|SEQUENCE|VIEW|COLUMN|TYPE)\b' -i {FILES}

# 2. print (critical)
grep -nE '(^|[^.[:alnum:]_])print\(' {FILES}

# 3. Python 3.10+ 문법 (critical)
#    ruff target-version이 py311이라 ruff로는 잡히지 않는다 — 반드시 grep으로 확인
grep -nE '(:|->)\s*[^=#]*[][A-Za-z_]\s*\|\s*[A-Za-z_]' {FILES}   # X | Y 타입 유니온
grep -nE '^\s*match\s+.+:\s*$' {FILES}                            # match 문

# 4. 린트
ruff check {FILES}
```

---

## 1. DB (DML only)

### 🔴 critical
- DDL 구문(`CREATE`/`ALTER`/`DROP`/`TRUNCATE`) 또는 `metadata.create_all()`·`drop_all()` 호출 — 스키마는 Backend Flyway가 단일 관리
- 스키마에 없는 컬럼·테이블을 가정한 쿼리 (ERD와 다르면 "Backend 마이그레이션 선행 필요"로 보고)

### 🟡 warning
- `collectors/`·`matchers/`에서 세션·쿼리를 직접 다룸 (`db/repository.py` 함수로 모아야 함)
- 문자열 포맷으로 조립한 SQL (`f"... {value}"`) — 바인드 파라미터 사용
- 루프 안에서 건별 커밋 (대량 수집 시 느려지고 중간 실패 시 부분 반영)

---

## 2. 로깅

### 🔴 critical
- `print` 사용

### 🟡 warning
- `logging.getLogger(__name__)` 대신 root logger(`logging.info(...)`) 직접 사용
- 예외를 삼키면서 로그도 남기지 않는 `except: pass` / `except Exception: pass`
- API 키·토큰·webhook URL을 로그에 출력

---

## 3. Python 3.9 호환

### 🔴 critical
- `X | Y` 타입 유니온 (`dict | None` 포함) → `Optional[X]` / `Union[X, Y]`
- `match` 문 → `if/elif`
- 3.10+ 전용 API (`zip(strict=True)`, `int.bit_count()`, `itertools.pairwise` 등)

---

## 4. 외부 API

### 🔴 critical
- MusicBrainz / Cover Art Archive 요청 경로에 `time.sleep(1.1)` 이상 대기가 없음 — 기존 요청 헬퍼·`_RATE_LIMIT_SLEEP` 상수를 거치지 않는 새 호출부 포함
- setlist.fm 요청에 `x-api-key` 또는 `Accept: application/json` 헤더 누락
- Spotify 토큰을 `spotify_client.py` 밖에서 직접 발급

### 🟡 warning
- `requests` 호출에 `timeout` 미지정
- 429/5xx 재시도 로직 없이 한 번 실패로 수집 전체 중단
- Discord 알림 실패가 수집 로직으로 전파 (선택 기능은 실패해도 수집에 영향 없어야 함)

---

## 5. 환경변수·패키지

### 🔴 critical
- 필수 API 키 미설정 시 모듈 로드 단계 `raise ValueError`가 없음 (호출 시점에 `None`으로 요청)
- 신규 최상위 패키지가 `pyproject.toml`의 `packages.find.include`에 미등록
- `.env` 또는 실제 키 값이 diff에 포함

### 🟡 warning
- 선택 기능(알림 등)이 미설정 시 예외를 던짐 — 조용히 no-op 해야 함
- 새 환경변수가 CLAUDE.md "외부 API 정보" 표에 기록되지 않음 (`.env.example`은 만들지 않음)
- 새 필수 환경변수가 `tests/conftest.py`의 `_TEST_ENV`에 없음 (테스트 수집 단계에서 실패)

---

## 6. 테스트

### 🟡 warning
- 새 public 함수에 대응하는 `tests/test_{모듈}.py` 테스트 없음
- 단위 테스트가 `time.sleep`을 patch하지 않아 실제로 대기
- 실제 네트워크·DB 접근 테스트에 `@pytest.mark.integration` 누락

### 🔵 suggestion
- `scheduler.py` 테스트의 patch 경로가 import 방식과 불일치 (`collectors/*`는 `scheduler.{모듈}.함수`, `db`/`matchers`는 `scheduler.{함수}`)
- 실패 흐름(빈 응답, 404/429, 중복 데이터) 케이스 부족

---

## 7. 스케줄러 등록

### 🟡 warning
- 로직 없이 `scheduler.py`에 잡만 등록 (수집 로직 → 스케줄 등록 순서)
- 새 잡이 `run-job --job` 선택지나 CLAUDE.md "수집 파이프라인 단계" 표에 반영되지 않음
