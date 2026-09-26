<div align="center">
  <img src=".github/logo.png" alt="Coming" width="180" />

  <br />
  <br />

  **Jpop 아티스트 내한 공연 정보 통합 플랫폼**

  KOPIS·MusicBrainz·setlist.fm·Spotify 데이터를 수집·매칭해 적재하는 데이터 파이프라인 — Claude Code 서브에이전트·스킬 워크플로우로 개발 전 과정을 진행한 1인 프로젝트입니다.

  <br />

  [![Python](https://img.shields.io/badge/Python-3.9-3776AB?style=flat-square&logo=python&logoColor=white)](pyproject.toml)
  [![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](api.py)
  [![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=flat-square&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
  [![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white)](Dockerfile)
  [![CI](https://img.shields.io/github/actions/workflow/status/Cominggg/Data/ci.yml?style=flat-square&logo=githubactions&logoColor=white&label=CI)](https://github.com/Cominggg/Data/actions/workflows/ci.yml)
  [![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)

  <br />

  **[→ comingg.com](https://comingg.com)**

</div>

## 소개

`coming-data`는 Coming의 데이터 파트로, 다음 역할을 담당합니다.

- KOPIS(공연예술통합전산망)에서 국내 공연 정보를 수집하고, MusicBrainz 아티스트 데이터와 매칭
- MusicBrainz에서 아티스트·멤버 정보를 수집
- setlist.fm에서 공연 완료 후 셋리스트를 수집
- Spotify에서 릴리즈(앨범/싱글)·트랙·커버와 아티스트 프로필 이미지를 수집
- 위 파이프라인을 APScheduler로 정기 실행하고, 백엔드(Spring)의 트리거 요청을 내부 API로 수신

## 기술 스택

| 분류 | 사용 기술 |
|---|---|
| 언어 | Python 3.9 |
| 스케줄러 | APScheduler |
| 내부 API 서버 | FastAPI + Uvicorn |
| DB 연동 | SQLAlchemy + psycopg2 (DML 전용, DDL은 백엔드 Flyway가 관리) |
| 테스트/린트 | pytest, pytest-cov, ruff |
| 배포 | Docker, GitHub Actions (CI/CD), GHCR |

## 수집 파이프라인

| 단계 | 수집 주기 | 진입점 |
|------|---------|--------|
| ① MusicBrainz 아티스트 | 초기 1회 | `run_initial_collect()` |
| ② 공연 상태 갱신 | 매일 00:00 | `run_concert_status_update()` |
| ③ 신규 공연 수집·매칭 | 매일 00:30 | `run_new_concert_collect()` |
| ④ 릴리즈 (앨범·트랙·커버) | 초기 + 매일 05:00 | `run_release_update()` |
| ⑤ 아티스트 이미지 | 매주 목 02:00 | `run_artist_image_update()` |
| ⑥ 로마자→한글 alias 변환 | 매주 목 03:00 | `run_ja_romanize_collect()` |
| ⑦ setlist.fm | 매일 06:00 (공연완료 대상) | `run_setlist_collect()` |

공연-아티스트 매칭은 ③ 단계 안에서 함께 수행됩니다. 전체 크론 목록은 [`scheduler.py`](scheduler.py)의 `_build_scheduler()`를 참고하세요.

## 외부 API 연동

| API | 엔드포인트 | Rate Limit | 비고 |
|-----|-----------|------------|------|
| KOPIS | `GET /openApi/restful/pblprfr` | 없음 | 주 1회 이상 권장 |
| MusicBrainz | `GET /ws/2/artist/` | 1 req/sec | 요청마다 1.1초 대기 |
| setlist.fm | `GET /rest/1.0/search/setlists` | - | `x-api-key`, `Accept: application/json` 헤더 필요 |
| Spotify Web API | `POST /api/token`, `GET /v1/artists/{id}`, `GET /v1/artists/{id}/albums`, `GET /v1/albums/{id}`, `GET /v1/search` | rolling 30초 윈도우 | Client Credentials Flow, 릴리즈·이미지 수집 |
| Discord Webhook | `POST {webhook_url}` | 웹훅당 분당 약 30건 | 신규 공연 알림, 미설정 시 생략 |

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
├── docs/
│   └── pipeline.md        # 파이프라인 상세 로직·매칭 알고리즘
├── .claude/               # Claude Code 설정 (아래 "AI 협업 워크플로우" 참고)
│   ├── agents/            # data-implementer, write-tests 로컬 에이전트
│   ├── skills/            # data-review, test 로컬 스킬
│   └── settings.json      # 권한·훅 설정
├── scheduler.py           # APScheduler 진입점 (내부 API 서버도 함께 기동)
├── api.py                 # 내부 FastAPI 서버 — BE→Data 수집 트리거 (X-Internal-Secret 인증)
├── Dockerfile
└── pyproject.toml
```

## 시작하기

### 설치

```bash
git clone https://github.com/Cominggg/Data.git coming-data
cd coming-data
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### 환경변수

`.env` 파일에 아래 값을 설정합니다.

```
DB_HOST=
DB_PORT=
DB_NAME=
DB_USER=
DB_PASSWORD=
KOPIS_API_KEY=
MUSICBRAINZ_USER_AGENT=
SETLISTFM_API_KEY=
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
INTERNAL_SECRET=       # 미설정 시 내부 API 요청이 모두 401
DISCORD_WEBHOOK_URL=   # 선택 — 미설정 시 알림 생략
API_HOST=              # 선택 — 내부 API 바인딩 호스트 (기본 0.0.0.0)
API_PORT=              # 선택 — 내부 API 포트 (기본 8000)
```

### 실행

```bash
# 초기 1회 수집 (아티스트 → KOPIS 매칭 → 릴리즈)
python scheduler.py init
# init 전용 플래그: --skip-artists / --force-artists / --skip-kopis / --skip-ja-romanize
#                  --skip-releases / --skip-artist-image / --skip-setlist / --log-file {경로}

# 상시 데몬 (APScheduler 크론 + 내부 API 서버, 기본 포트 8000)
python scheduler.py

# 단일 잡 즉시 실행
python scheduler.py run-job --job {concert-status-update|new-concert-collect|release-update|ja-romanize|artist-image|setlist}

# 누락 이미지·릴리즈 재수집 (--skip-releases / --skip-artist-image 사용 가능)
python scheduler.py recover

# 단건 수집
python scheduler.py collect-release --artist-id {id}   # 아티스트 1명의 릴리즈
python scheduler.py collect-setlist                    # 공연완료 공연 셋리스트
```

## 테스트 & 린트

```bash
pytest          # 단위 테스트 (통합 테스트 제외)
ruff check .    # 린트
```

## CI/CD

- **CI** ([`ci.yml`](.github/workflows/ci.yml)): 모든 브랜치 push 및 main 대상 PR에서 `ruff check .` + `pytest` 실행
- **CD** ([`cd.yml`](.github/workflows/cd.yml)): main 브랜치 push 시 Docker 이미지를 빌드해 GHCR에 푸시하고, SSH로 운영 서버에 접속해 `docker compose`로 배포

## AI 협업 워크플로우

Claude Code 에이전트·스킬·훅으로 이슈부터 PR까지 진행합니다. 프로젝트 규칙은 [`CLAUDE.md`](CLAUDE.md)에 모여 있고, 아래 도구들이 그 규칙을 역할별로 나눠 강제합니다.

### 흐름

```
/issue → /plan-issue → data-implementer ∥ write-tests → /test → /data-review → /commit → /pr
```

| 단계 | 도구 | 하는 일 |
|------|------|--------|
| 이슈·브랜치 | `/issue` | GitHub 이슈 생성 + `{type}/#{번호}-...` 브랜치 체크아웃 |
| 계획 | `/plan-issue` | 이슈 체크리스트를 코드 현황과 대조하고, 남은 작업을 커밋 단위로 순서화 |
| 구현 | `data-implementer` 에이전트 | `collectors/`, `matchers/`, `db/`, `notifier/` 구현 |
| 테스트 작성 | `write-tests` 에이전트 | `tests/` 단위 테스트 작성 |
| 테스트 실행 | `/test` | 변경 파일과 매핑되는 테스트만 선별 실행, 실패 시 원인 분석 |
| 리뷰 | `/data-review` | 프로젝트 규칙 위반 검토 — 🔴 critical 0건이어야 커밋 |
| 커밋·PR | `/commit`, `/pr` | 컨벤션(`[{type}] 요약`)에 맞춘 커밋·PR 작성 |

`data-review`, `test` 스킬과 두 에이전트는 이 레포의 [`.claude/`](.claude/)에 포함돼 있습니다. `/issue`, `/plan-issue`, `/commit`, `/pr`은 작성자의 전역 Claude Code 스킬이라 레포에는 없습니다.

### 에이전트 역할 분리와 병렬 실행

두 에이전트는 수정 가능한 디렉터리가 겹치지 않아 동시에 실행해도 충돌하지 않습니다.

| 에이전트 | 수정 가능 | 수정 금지 |
|---------|----------|----------|
| [`data-implementer`](.claude/agents/data-implementer.md) | `collectors/`, `matchers/`, `db/`, `notifier/`, (패키지 등록 시) `pyproject.toml` | `tests/`, 지시 없는 `scheduler.py`·`api.py` |
| [`write-tests`](.claude/agents/write-tests.md) | `tests/` | 구현 코드 전체 |

다음 중 하나라도 해당하면 병렬로 실행하고, 두 에이전트에 같은 함수 시그니처·동작 명세를 전달합니다.

- 새 public 함수(수집기·매처·DML)를 추가한다
- 구현 파일 2개 이상을 수정한다
- 새 테스트 파일이 필요하다

구현 파일 1개의 소규모 수정은 에이전트 없이 처리하거나 구현 → 테스트 순으로 순차 실행합니다.

### 코드 리뷰 (`/data-review`)

[체크리스트](.claude/skills/data-review/references/data-checklist.md)는 grep 자동 검사와 diff 기반 수동 검토로 나뉩니다.

- **DB**: DML만 허용, DDL 금지 (스키마는 백엔드 Flyway가 관리)
- **로깅**: `print` 금지, `logging.getLogger(__name__)` 사용
- **Python 3.9 문법**: `X | Y` 유니온·`match` 문 금지 — ruff `target-version`이 py311이라 린트로는 잡히지 않아 별도로 검사
- **외부 API**: MusicBrainz 1.1초 대기, setlist.fm 필수 헤더, Spotify 토큰은 공통 클라이언트로만 발급
- **환경변수·패키지**: 필수 키 미설정 시 모듈 로드 단계에서 `ValueError`, 선택 기능은 no-op, 신규 최상위 패키지의 `pyproject.toml` 등록

### 훅 ([`.claude/settings.json`](.claude/settings.json))

| 시점 | 대상 | 동작 |
|------|------|------|
| PreToolUse | Write·Edit | 경로에 `.env`·`.secret`·`credentials`가 포함되면 수정 차단 (Bash 경유 쓰기는 검사 대상 아님) |
| PostToolUse | `.py` 파일 Write·Edit | `ruff check --fix` + `ruff format` 후 같은 이름의 `tests/test_{모듈}.py`가 있을 때만 자동 실행 (테스트 파일 자체를 수정하면 실행되지 않음) |

## 관련 레포지토리

- [Backend](https://github.com/Cominggg/Backend) — Spring Boot API 서버
- [Frontend](https://github.com/Cominggg/Frontend) — 웹 클라이언트
- [Specification](https://github.com/Cominggg/Specification) — ERD·API 명세

## License

MIT © [You-Hyuk](https://github.com/You-Hyuk)
