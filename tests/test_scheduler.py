"""scheduler.py 단위 테스트."""
from unittest.mock import MagicMock, call, patch

import pytest

from scheduler import (
    _build_scheduler,
    run_initial_collect,
    run_kopis_collect_and_match,
    run_release_update,
    run_setlist_collect,
    run_status_update,
)


class TestRunInitialCollect:
    def test_calls_collect_artists(self):
        """collect_artists가 1회 호출되어야 한다."""
        with (
            patch("scheduler.musicbrainz.collect_artists", return_value=[]) as mock_collect,
            patch("scheduler.save_artists"),
            patch("scheduler.release.collect_releases", return_value=[]),
            patch("scheduler.save_releases"),
        ):
            run_initial_collect()

        mock_collect.assert_called_once()

    def test_calls_save_artists(self):
        """save_artists가 collect_artists 결과로 호출되어야 한다."""
        artists = [{"mbid": "mbid-1", "name": "아이유"}]
        with (
            patch("scheduler.musicbrainz.collect_artists", return_value=artists),
            patch("scheduler.save_artists") as mock_save,
            patch("scheduler.release.collect_releases", return_value=[]),
            patch("scheduler.save_releases"),
        ):
            run_initial_collect()

        mock_save.assert_called_once_with(artists)

    def test_collects_releases_for_each_artist(self):
        """각 아티스트 MBID로 collect_releases가 호출되어야 한다."""
        artists = [{"mbid": "mbid-1"}, {"mbid": "mbid-2"}]
        with (
            patch("scheduler.musicbrainz.collect_artists", return_value=artists),
            patch("scheduler.save_artists"),
            patch("scheduler.release.collect_releases", return_value=[]) as mock_collect,
            patch("scheduler.save_releases"),
        ):
            run_initial_collect()

        assert mock_collect.call_count == 2
        mock_collect.assert_any_call("mbid-1")
        mock_collect.assert_any_call("mbid-2")

    def test_saves_releases_for_each_artist(self):
        """각 아티스트 릴리즈가 save_releases로 저장되어야 한다."""
        artists = [{"mbid": "mbid-1"}, {"mbid": "mbid-2"}]
        with (
            patch("scheduler.musicbrainz.collect_artists", return_value=artists),
            patch("scheduler.save_artists"),
            patch("scheduler.release.collect_releases", return_value=[{"title": "앨범"}]),
            patch("scheduler.save_releases") as mock_save,
        ):
            run_initial_collect()

        assert mock_save.call_count == 2


class TestRunKopisCollectAndMatch:
    def test_collects_and_saves_concerts(self):
        """kopis.collect 후 save_concerts가 호출되어야 한다."""
        concerts = [{"kopis_id": "PF001"}]
        with (
            patch("scheduler.kopis.collect", return_value=concerts),
            patch("scheduler.save_concerts") as mock_save,
            patch("scheduler.get_all_aliases", return_value=[]),
            patch("scheduler.get_unmatched_concerts", return_value=[]),
            patch("scheduler.save_concert_artists"),
            patch("scheduler.save_to_review_queue"),
            patch("scheduler.update_artist_is_coming"),
        ):
            run_kopis_collect_and_match()

        mock_save.assert_called_once_with(concerts)

    def test_saves_matched_concert_artists(self):
        """매칭 성공 결과가 save_concert_artists로 저장되어야 한다."""
        unmatched = [{"concert_id": 1, "title": "아이유 콘서트", "cast": "아이유"}]
        aliases = [{"artist_id": 10, "name": "아이유"}]
        with (
            patch("scheduler.kopis.collect", return_value=[]),
            patch("scheduler.save_concerts"),
            patch("scheduler.get_all_aliases", return_value=aliases),
            patch("scheduler.get_unmatched_concerts", return_value=unmatched),
            patch("scheduler.save_concert_artists") as mock_save_ca,
            patch("scheduler.save_to_review_queue"),
            patch("scheduler.update_artist_is_coming"),
        ):
            run_kopis_collect_and_match()

        mock_save_ca.assert_called_once()
        saved = mock_save_ca.call_args[0][0]
        assert len(saved) == 1
        assert saved[0]["concert_id"] == 1
        assert saved[0]["artist_id"] == 10

    def test_saves_to_review_queue_on_match_failure(self):
        """매칭 실패 공연이 review_queue에 등록되어야 한다."""
        unmatched = [{"concert_id": 99, "title": "알 수 없는 공연 xyzxyz", "cast": "미상"}]
        aliases = [{"artist_id": 1, "name": "아이유"}]
        with (
            patch("scheduler.kopis.collect", return_value=[]),
            patch("scheduler.save_concerts"),
            patch("scheduler.get_all_aliases", return_value=aliases),
            patch("scheduler.get_unmatched_concerts", return_value=unmatched),
            patch("scheduler.save_concert_artists"),
            patch("scheduler.save_to_review_queue") as mock_rq,
            patch("scheduler.update_artist_is_coming"),
        ):
            run_kopis_collect_and_match()

        mock_rq.assert_called_once()
        failures = mock_rq.call_args[0][0]
        assert any(f["concert_id"] == 99 for f in failures)

    def test_updates_is_coming_after_match(self):
        """매칭 성공 후 update_artist_is_coming이 호출되어야 한다."""
        unmatched = [{"concert_id": 1, "title": "아이유 콘서트", "cast": "아이유"}]
        aliases = [{"artist_id": 10, "name": "아이유"}]
        with (
            patch("scheduler.kopis.collect", return_value=[]),
            patch("scheduler.save_concerts"),
            patch("scheduler.get_all_aliases", return_value=aliases),
            patch("scheduler.get_unmatched_concerts", return_value=unmatched),
            patch("scheduler.save_concert_artists"),
            patch("scheduler.save_to_review_queue"),
            patch("scheduler.update_artist_is_coming") as mock_update,
        ):
            run_kopis_collect_and_match()

        mock_update.assert_called_once()
        artist_ids = mock_update.call_args[0][0]
        assert 10 in artist_ids

    def test_skips_save_concert_artists_when_no_matches(self):
        """매칭 결과가 없으면 save_concert_artists가 호출되지 않아야 한다."""
        with (
            patch("scheduler.kopis.collect", return_value=[]),
            patch("scheduler.save_concerts"),
            patch("scheduler.get_all_aliases", return_value=[]),
            patch("scheduler.get_unmatched_concerts", return_value=[]),
            patch("scheduler.save_concert_artists") as mock_save_ca,
            patch("scheduler.save_to_review_queue"),
            patch("scheduler.update_artist_is_coming"),
        ):
            run_kopis_collect_and_match()

        mock_save_ca.assert_not_called()


class TestRunStatusUpdate:
    def test_collects_concerts_and_updates_status(self):
        """kopis.collect 후 update_concert_status가 호출되어야 한다."""
        concerts = [{"kopis_id": "PF001", "prfstate": "공연완료", "updatedate": "2024-01-01"}]
        with (
            patch("scheduler.kopis.collect", return_value=concerts),
            patch("scheduler.update_concert_status") as mock_update,
            patch("scheduler.get_all_aliases", return_value=[]),
            patch("scheduler.update_artist_is_coming"),
        ):
            run_status_update()

        mock_update.assert_called_once_with(concerts)

    def test_updates_is_coming_for_all_aliased_artists(self):
        """모든 alias 아티스트에 대해 update_artist_is_coming이 호출되어야 한다."""
        aliases = [{"artist_id": 1, "name": "아이유"}, {"artist_id": 2, "name": "BTS"}]
        with (
            patch("scheduler.kopis.collect", return_value=[]),
            patch("scheduler.update_concert_status"),
            patch("scheduler.get_all_aliases", return_value=aliases),
            patch("scheduler.update_artist_is_coming") as mock_update,
        ):
            run_status_update()

        mock_update.assert_called_once()
        artist_ids = mock_update.call_args[0][0]
        assert set(artist_ids) == {1, 2}


class TestRunReleaseUpdate:
    def test_collects_releases_for_all_mbids(self):
        """DB의 모든 MBID에 대해 collect_releases가 호출되어야 한다."""
        mbids = ["mbid-1", "mbid-2"]
        with (
            patch("scheduler.get_all_artist_mbids", return_value=mbids),
            patch("scheduler.release.collect_releases", return_value=[]) as mock_collect,
            patch("scheduler.save_releases"),
        ):
            run_release_update()

        assert mock_collect.call_count == 2
        mock_collect.assert_any_call("mbid-1")
        mock_collect.assert_any_call("mbid-2")

    def test_saves_releases_for_each_mbid(self):
        """각 MBID의 릴리즈가 save_releases로 저장되어야 한다."""
        releases = [{"release_group_mbid": "rg-1"}]
        with (
            patch("scheduler.get_all_artist_mbids", return_value=["mbid-1"]),
            patch("scheduler.release.collect_releases", return_value=releases),
            patch("scheduler.save_releases") as mock_save,
        ):
            run_release_update()

        mock_save.assert_called_once_with(releases)

    def test_no_db_calls_when_no_artists(self):
        """아티스트가 없으면 collect_releases가 호출되지 않아야 한다."""
        with (
            patch("scheduler.get_all_artist_mbids", return_value=[]),
            patch("scheduler.release.collect_releases") as mock_collect,
            patch("scheduler.save_releases"),
        ):
            run_release_update()

        mock_collect.assert_not_called()


class TestRunSetlistCollect:
    def test_collects_and_saves_setlists(self):
        """setlist.collect 후 save_setlists가 호출되어야 한다."""
        setlists = [{"concert_id": 1, "setlist_fm_id": "abc123", "tracks": []}]
        with (
            patch("scheduler.setlist.collect", return_value=setlists),
            patch("scheduler.save_setlists") as mock_save,
        ):
            run_setlist_collect()

        mock_save.assert_called_once_with(setlists)

    def test_calls_setlist_collect(self):
        """setlist.collect가 1회 호출되어야 한다."""
        with (
            patch("scheduler.setlist.collect", return_value=[]) as mock_collect,
            patch("scheduler.save_setlists"),
        ):
            run_setlist_collect()

        mock_collect.assert_called_once()


class TestBuildScheduler:
    def test_registers_four_jobs(self):
        """스케줄러에 4개의 잡이 등록되어야 한다."""
        scheduler = _build_scheduler()
        assert len(scheduler.get_jobs()) == 4

    def test_includes_monday_job(self):
        """월요일 KOPIS 수집·매칭 잡이 등록되어야 한다."""
        scheduler = _build_scheduler()
        job_funcs = [job.func for job in scheduler.get_jobs()]
        assert run_kopis_collect_and_match in job_funcs

    def test_includes_tuesday_job(self):
        """화요일 릴리즈 갱신 잡이 등록되어야 한다."""
        scheduler = _build_scheduler()
        job_funcs = [job.func for job in scheduler.get_jobs()]
        assert run_release_update in job_funcs

    def test_includes_daily_status_job(self):
        """매일 실행되는 공연 상태 갱신 잡이 등록되어야 한다."""
        scheduler = _build_scheduler()
        job_funcs = [job.func for job in scheduler.get_jobs()]
        assert run_status_update in job_funcs

    def test_includes_daily_setlist_job(self):
        """매일 실행되는 setlist 수집 잡이 등록되어야 한다."""
        scheduler = _build_scheduler()
        job_funcs = [job.func for job in scheduler.get_jobs()]
        assert run_setlist_collect in job_funcs
