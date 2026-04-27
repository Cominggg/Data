import os

import pytest

# db/connection.py 가 모듈 임포트 시점에 환경변수를 검증하므로
# 테스트 수집 전에 미리 기본값을 주입한다.
# 실제 DB 연결이 필요한 테스트는 @pytest.mark.integration 으로 표시하고
# `pytest -m integration` 으로 별도 실행한다.
_TEST_ENV = {
    "DB_USER": "test_user",
    "DB_PASSWORD": "test_password",
    "DB_HOST": "localhost",
    "DB_PORT": "5432",
    "DB_NAME": "test_db",
    "MUSICBRAINZ_USER_AGENT": "coming-data-test/1.0 (test@example.com)",
    "KOPIS_API_KEY": "test_kopis_key",
    "SETLISTFM_API_KEY": "test_setlist_key",
}

for _key, _val in _TEST_ENV.items():
    os.environ.setdefault(_key, _val)


@pytest.fixture()
def mock_env(monkeypatch):
    """모든 외부 의존성 환경변수를 테스트용 값으로 고정한다."""
    for key, val in _TEST_ENV.items():
        monkeypatch.setenv(key, val)
