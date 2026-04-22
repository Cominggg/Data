import pytest

setlist = pytest.importorskip("collectors.setlist", reason="collectors.setlist 미구현")


class TestSetlistCollect:
    def test_collect_returns_list(self):
        """collect() 호출 결과가 리스트여야 한다."""
        pytest.skip("미구현")

    def test_targets_completed_concerts_only(self):
        """prfstate=공연완료 건에 대해서만 수집을 시도해야 한다."""
        pytest.skip("미구현")

    def test_returns_empty_when_no_data(self):
        """setlist.fm에 데이터가 없으면 빈 상태를 유지해야 한다."""
        pytest.skip("미구현")

    def test_request_includes_required_headers(self):
        """x-api-key, Accept: application/json 헤더가 포함되어야 한다."""
        pytest.skip("미구현")
