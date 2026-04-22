import pytest

kopis = pytest.importorskip("collectors.kopis", reason="collectors.kopis 미구현")


class TestKopisCollect:
    def test_collect_returns_list(self):
        """collect() 호출 결과가 리스트여야 한다."""
        pytest.skip("미구현")

    def test_filters_visit_concerts_only(self):
        """visit=Y 조건으로 내한공연만 필터링되어야 한다."""
        pytest.skip("미구현")

    def test_filters_popular_music_genre(self):
        """genrenm=대중음악(GGGA) 장르만 수집되어야 한다."""
        pytest.skip("미구현")

    def test_stores_booking_links(self):
        """relates 필드에 예매처 링크가 저장되고, 없으면 빈 배열이어야 한다."""
        pytest.skip("미구현")

    def test_detects_status_change_by_updatedate(self):
        """updatedate 변화 감지 시 prfstate가 갱신되어야 한다."""
        pytest.skip("미구현")
