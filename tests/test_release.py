import pytest

release = pytest.importorskip("collectors.release", reason="collectors.release 미구현")


class TestReleaseCollect:
    def test_collect_returns_list(self):
        """collect() 호출 결과가 리스트여야 한다."""
        pytest.skip("미구현")

    def test_inserts_only_new_releases(self):
        """first-release-date 기준으로 DB에 없는 항목만 INSERT되어야 한다."""
        pytest.skip("미구현")

    def test_cover_art_null_on_404(self):
        """Cover Art Archive 404 응답 시 커버 이미지를 null로 허용해야 한다."""
        pytest.skip("미구현")

    def test_rate_limit_sleep_applied(self):
        """MusicBrainz 요청마다 1.1초 sleep이 적용되어야 한다."""
        pytest.skip("미구현")
