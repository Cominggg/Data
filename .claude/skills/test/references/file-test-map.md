# 소스 파일 → 테스트 파일 매핑

## 매핑 규칙

| 소스 파일 | 테스트 파일 |
|-----------|------------|
| `collectors/musicbrainz.py` | `tests/test_musicbrainz.py` |
| `collectors/kopis.py` | `tests/test_kopis.py` |
| `collectors/setlist.py` | `tests/test_setlist.py` |
| `collectors/release.py` | `tests/test_release.py` |
| `matchers/artist_matcher.py` | `tests/test_artist_matcher.py` |
| `db/repository.py` | `tests/test_repository.py` |
| `db/connection.py` | `tests/test_repository.py` |

## 전체 실행 조건

아래 경우에는 선별 실행 대신 전체 테스트(`python -m pytest`)를 실행한다:

- 변경된 파일이 없는 경우
- 변경 파일이 위 매핑 테이블에 없는 경우 (예: `scheduler.py`, `conftest.py`)
- 명시적으로 전체 실행을 요청한 경우
