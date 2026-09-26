# coming-data (jpop-data-collector)

Jpop 아티스트 및 내한공연 수집 파이프라인 (KOPIS / MusicBrainz / Spotify / setlist.fm → DB)

## 레포지토리 구조

```
coming-data/
├── collectors/
│   ├── artist_image.py    # Spotify Web API 아티스트 프로필 이미지 수집
│   ├── kopis.py           # KOPIS API 수집
│   ├── ja_romanize.py     # sort_name 로마자 표기 → 한글 alias 규칙 변환
│   ├── musicbrainz.py     # MusicBrainz 아티스트·멤버 수집
│   ├── release.py         # Spotify 릴리즈(앨범·싱글) + 트랙·커버 수집
│   ├── setlist.py         # setlist.fm 셋리스트 수집
│   └── spotify_client.py  # Spotify Client Credentials 토큰 발급·공통 요청
├── matchers/
│   └── artist_matcher.py  # alias 기반 phrase-matching 로직
├── notifier/
│   └── discord.py         # Discord Webhook 알림 (신규 공연 수집 결과)
├── db/
│   ├── connection.py      # SQLAlchemy 엔진·세션 설정
│   └── repository.py      # DB 저장 함수 (DML)
├── tests/                 # pytest 단위 테스트
├── scheduler.py           # APScheduler 진입점 (내부 API 서버도 함께 기동)
├── api.py                 # 내부 FastAPI 서버 — BE→Data 수집 트리거 (X-Internal-Secret 인증)
└── pyproject.toml
```

## 실행 명령어

```bash
pytest          # 단위 테스트 (통합 테스트 제외)
ruff check .    # 린트

python scheduler.py    # 상시 데몬 (APScheduler 크론 + 내부 API 서버, 기본 포트 8000)

# 초기 1회 수집 (아티스트 → KOPIS 매칭 → 릴리즈). 플래그는 init 전용:
# --skip-artists / --force-artists / --skip-kopis / --skip-ja-romanize
# --skip-releases / --skip-artist-image / --skip-setlist / --log-file {경로}
python scheduler.py init [플래그...]

python scheduler.py run-job --job {concert-status-update|new-concert-collect|release-update|ja-romanize|artist-image|setlist}  # 단일 잡 즉시 실행
python scheduler.py recover                          # 누락 이미지·릴리즈 재수집 (--skip-releases / --skip-artist-image)
python scheduler.py collect-release --artist-id {id}  # 단건 릴리즈 수집
python scheduler.py collect-setlist                   # 단건 setlist 수집
```

## 파이썬 버전

- **Python 3.9.6** (런타임 및 `pyproject.toml` `requires-python = ">=3.9"`)
- 코드 작성 시 Python 3.9 호환 문법만 사용한다:
  - `X | Y` 타입 유니온 문법 사용 불가 → `Optional[X]` / `Union[X, Y]` 사용
  - `dict | None` 대신 `Optional[dict]` 사용
  - `match` 문 사용 불가 (3.10+)

## 코딩 규칙

- DML만 사용 — DDL은 백엔드(Spring) Flyway가 단일 관리
- `logging`만 사용 (`print` 금지), `.env` 커밋 금지, `.env.example` 미유지 (환경변수는 "외부 API 정보" 표에만 기록)
- 필수 API 키는 미설정 시 모듈 로드 단계에서 `raise ValueError`; 알림 등 선택 기능은 미설정 시 조용히 no-op
- 최상위 패키지 추가 시 `pyproject.toml`의 `packages.find.include`에도 등록
- 린터: `ruff check .` (`line-length=100`, `select=E,F,I`)

## 외부 API 정보

| API | 엔드포인트 | Rate Limit | 비고 |
|-----|-----------|------------|------|
| KOPIS | `GET /openApi/restful/pblprfr` | 없음 | 주 1회 이상 권장 |
| MusicBrainz | `GET /ws/2/artist/` | **1 req/sec** | `time.sleep(1.1)` 필수 |
| setlist.fm | `GET https://api.setlist.fm/rest/1.0/search/setlists` | - | Header: `x-api-key`, `Accept: application/json` 필수 |
| Spotify Web API | `POST https://accounts.spotify.com/api/token`, `GET https://api.spotify.com/v1/artists/{id}`, `GET /v1/artists/{id}/albums`, `GET /v1/albums/{id}`, `GET /v1/search` | rolling 30초 윈도우 (관대함) | Client Credentials Flow; `Authorization: Bearer {token}`; access_token 1h 캐시 |
| Discord Webhook | `POST {webhook_url}` | 웹훅당 분당 약 30건 | 신규 공연 수집 결과 알림; `DISCORD_WEBHOOK_URL` 미설정 시 알림 생략 |

## 수집 파이프라인 단계

> 상세 로직 및 매칭 알고리즘: [docs/pipeline.md](docs/pipeline.md)

| 단계 | 수집 주기 | 진입점 |
|------|---------|--------|
| ① MusicBrainz 아티스트 | 초기 1회 | `run_initial_collect()` |
| ② 공연 상태 갱신 | 매일 00:00 | `run_concert_status_update()` |
| ③ 신규 공연 수집·매칭 | 매일 00:30 | `run_new_concert_collect()` |
| ④ 릴리즈 (앨범·트랙·커버) | 초기 + 매일 05:00 | `run_release_update()` |
| ⑤ 아티스트 이미지 | 매주 목 02:00 | `run_artist_image_update()` |
| ⑥ 로마자→한글 alias 변환 | 매주 목 03:00 | `run_ja_romanize_collect()` |
| ⑦ setlist.fm | 매일 06:00 (공연완료 대상) | `run_setlist_collect()` |

(공연-아티스트 매칭은 ③ 안에서 함께 수행. 크론 전체 목록은 `scheduler.py`의 `_build_scheduler()`)

## 참고 문서

- ERD: https://github.com/Cominggg/Specification/blob/main/spec/erd.md
- 파이프라인 상세: [docs/pipeline.md](docs/pipeline.md)

## 개발 워크플로우

### 테스트 mocking 컨벤션

`scheduler.py`는 import 방식이 대상마다 달라 `patch()` 경로도 달라진다:
- `collectors/*`: 모듈째로 import(`from collectors import kopis`) → `patch("scheduler.kopis.collect")`
- `db/repository.py`, `matchers/*`: 함수 단위로 import → `patch("scheduler.get_all_aliases")`처럼 함수명 직접 patch

### 서브에이전트 패턴

로컬 에이전트(`.claude/agents/`) 두 개로 구현과 테스트를 나눈다. 담당 범위가 겹치지 않아 병렬 실행해도 충돌하지 않는다.

| 에이전트 | 담당 | 수정 금지 |
|---------|------|----------|
| `data-implementer` | `collectors/`, `matchers/`, `db/`, `notifier/` (+ 패키지 등록 시 `pyproject.toml`) | `tests/`, 지시 없는 `scheduler.py`·`api.py` |
| `write-tests` | `tests/` | 구현 코드 전체 |

**병렬 실행 임계치** — 아래 중 하나라도 해당하면 두 에이전트를 병렬로 띄운다:
- 새 public 함수(수집기·매처·DML)를 추가한다
- 구현 파일 2개 이상을 수정한다
- 새 테스트 파일이 필요하다

병렬로 띄울 때는 두 프롬프트에 **같은 함수 시그니처·동작 명세**를 넣는다 (write-tests는 구현 완료 전에 작성을 시작하므로).

그 외(구현 파일 1개의 버그 수정·소규모 변경, 기존 테스트 파일에 케이스 1~2개 추가)는 에이전트 없이 직접 처리하거나 `data-implementer` → `write-tests` 순차 실행한다.

### 커밋 전 체크리스트

`/test` → `/data-review` → `/commit` → `/pr` 순으로 마무리한다.

- `/test`: 변경 파일 관련 테스트 통과
- `/data-review`: 🔴 critical 0건 (DML-only, `print` 금지, Python 3.9 문법, rate limit, 패키지 등록 등)
- `ruff check .` 통과 — `target-version`이 py311이라 `X | Y`·`match`는 ruff가 못 잡는다. `/data-review`에서 확인한다
- `.env`·시크릿 파일은 Write/Edit/Bash PreToolUse 훅이 차단한다 (`.claude/hooks/block_secrets.py`)
- `.py` 편집 후 PostToolUse 훅이 ruff 정리 + 관련 테스트를 실행하고, 실패하면 결과를 돌려준다 (`.claude/hooks/post_edit.py`)

