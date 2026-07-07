# coming-data (jpop-data-collector)

Jpop 아티스트 및 내한공연 수집 파이프라인 (KOPIS / MusicBrainz / setlist.fm → DB)

## 레포지토리 구조

```
coming-data/
├── collectors/
│   ├── artist_image.py    # Spotify Web API 아티스트 프로필 이미지 수집
│   ├── kopis.py           # KOPIS API 수집
│   ├── lastfm.py          # Last.fm 월간 리스너 수 수집
│   ├── ja_romanize.py     # sort_name 로마자 표기 → 한글 alias 규칙 변환
│   ├── musicbrainz.py     # MusicBrainz 아티스트·멤버 수집
│   ├── release.py         # MusicBrainz 릴리즈(앨범·싱글·EP) + 트랙·커버 수집
│   └── setlist.py         # setlist.fm 셋리스트 수집
├── matchers/
│   └── artist_matcher.py  # alias 기반 매칭 로직 (rapidfuzz)
├── db/
│   ├── connection.py      # SQLAlchemy 엔진·세션 설정
│   └── repository.py      # DB 저장 함수 (DML)
├── tests/                 # pytest 단위 테스트
├── scheduler.py           # APScheduler 진입점
└── pyproject.toml
```

## 실행 명령어

```bash
# 단위 테스트 (통합 테스트 제외, pytest.ini_options 기본값)
pytest

# 린트
ruff check .

# 전체 파이프라인 실행
python scheduler.py

# 플래그
python scheduler.py --skip-artists    # 아티스트 수집 건너뜀
python scheduler.py --skip-kopis     # KOPIS 수집 건너뜀
python scheduler.py --skip-ja-romanize # 로마자→한글 alias 변환 건너뜀
python scheduler.py --force-artists  # 아티스트 강제 재수집
```

## 파이썬 버전

- **Python 3.9.6** (런타임 및 `pyproject.toml` `requires-python = ">=3.9"`)
- 코드 작성 시 Python 3.9 호환 문법만 사용한다:
  - `X | Y` 타입 유니온 문법 사용 불가 → `Optional[X]` / `Union[X, Y]` 사용
  - `dict | None` 대신 `Optional[dict]` 사용
  - `match` 문 사용 불가 (3.10+)

## 코딩 규칙

- DML만 사용 — DDL은 백엔드(Spring) Flyway가 단일 관리
- `logging`만 사용 (`print` 금지)
- `.env` 커밋 금지
- 린터: `ruff check .` (`line-length=100`, `select=E,F,I`)

## 외부 API 정보

| API | 엔드포인트 | Rate Limit | 비고 |
|-----|-----------|------------|------|
| KOPIS | `GET /openApi/restful/pblprfr` | 없음 | 주 1회 이상 권장 |
| MusicBrainz | `GET /ws/2/artist/`, `/ws/2/release-group/`, `/ws/2/release/` | **1 req/sec** | `time.sleep(1.1)` 필수 |
| Cover Art Archive | `GET https://coverartarchive.org/release-group/{mbid}/front` | 1 req/sec | 404 시 null 허용 |
| setlist.fm | `GET https://api.setlist.fm/rest/1.0/search/setlists` | - | Header: `x-api-key`, `Accept: application/json` 필수 |
| Spotify Web API | `POST https://accounts.spotify.com/api/token`, `GET https://api.spotify.com/v1/artists/{id}`, `GET /v1/search` | rolling 30초 윈도우 (관대함) | Client Credentials Flow; `Authorization: Bearer {token}`; access_token 1h 캐시 |
| Last.fm | `GET https://ws.audioscrobbler.com/2.0/` | - | method=`artist.getinfo`; 월간 리스너 수 수집 |
| Discord Webhook | `POST {webhook_url}` | 웹훅당 분당 약 30건 | 신규 공연 수집 결과 알림; `DISCORD_WEBHOOK_URL` 미설정 시 알림 생략 |

## 수집 파이프라인 단계

> 상세 로직 및 매칭 알고리즘: [docs/pipeline.md](docs/pipeline.md)

| 단계 | 수집 주기 | 진입점 |
|------|---------|--------|
| ① MusicBrainz 아티스트 | 초기 1회 | `run_initial_collect()` |
| ② 릴리즈 (앨범·트랙·커버) | 초기 + 주 1회 | `run_release_update()` |
| ③ KOPIS 공연 수집·매칭 | 주 1회 이상 | `run_initial_collect()` |
| ④ 공연-아티스트 매칭 | KOPIS 수집 후 자동 | `matchers/artist_matcher.py` |
| ⑤ setlist.fm | 공연 완료 후 1일 이내 | `run_setlist_update()` |

## 참고 문서

- ERD: https://github.com/Cominggg/Specification/blob/main/spec/erd.md
- 파이프라인 상세: [docs/pipeline.md](docs/pipeline.md)

## 개발 워크플로우

### 서브에이전트 패턴

새 기능 구현 시 두 에이전트를 병렬로 사용한다:
- **Agent A**: 기능 구현 (`collectors/`, `matchers/`, `db/`)
- **Agent B**: 대응 테스트 파일 작성 (`tests/`)

```
/start → Agent A(구현) + Agent B(테스트) 병렬 실행
       → PostToolUse 훅: .py 저장 시 pytest 자동 실행
       → /test: 결과 요약 및 실패 분석
       → /commit → /pr
```

