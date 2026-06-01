"""scheduler.py 단위 테스트."""
from unittest.mock import patch

import pytest

from scheduler import (
    _build_scheduler,
    _sort_releases,
    run_initial_collect,
    run_release_update,
    run_setlist_collect,
    run_status_update,
)


class TestRunInitialCollect:
    @pytest.fixture(autouse=True)
    def mock_sub_jobs(self):
        with (
            patch("scheduler.run_wikipedia_collect"),
            patch("scheduler.run_status_update"),
            patch("scheduler.get_matched_artist_mbids", return_value=[]),
            patch("scheduler.run_cover_art_update"),
            patch("scheduler.run_artist_image_update"),
            patch("scheduler.run_setlist_collect"),
        ):
            yield

    def test_calls_collect_artists(self):
        """collect_artists가 1회 호출되어야 한다."""
        with (
            patch("scheduler.get_all_artist_mbids", return_value=[]),
            patch("scheduler.musicbrainz.collect_artists", return_value=[]) as mock_collect,
            patch("scheduler.save_artists"),
        ):
            run_initial_collect()

        mock_collect.assert_called_once()

    def test_calls_save_artists(self):
        """save_artists가 collect_artists 결과로 호출되어야 한다."""
        artists = [{"mbid": "mbid-1", "name": "아이유"}]
        with (
            patch("scheduler.get_all_artist_mbids", return_value=[]),
            patch("scheduler.musicbrainz.collect_artists", return_value=artists),
            patch("scheduler.save_artists") as mock_save,
        ):
            run_initial_collect()

        mock_save.assert_called_once_with(artists)

    def test_collects_releases_for_matched_artists(self):
        """매칭 아티스트 MBID 목록으로 collect_releases가 호출되어야 한다."""
        with (
            patch("scheduler.get_all_artist_mbids", return_value=[]),
            patch("scheduler.musicbrainz.collect_artists", return_value=[]),
            patch("scheduler.save_artists"),
            patch("scheduler.get_matched_artist_mbids", return_value=["mbid-1", "mbid-2"]),
            patch("scheduler.release.collect_releases", return_value=[]) as mock_collect,
            patch("scheduler.save_releases"),
        ):
            run_initial_collect()

        assert mock_collect.call_count == 2
        mock_collect.assert_any_call("mbid-1")
        mock_collect.assert_any_call("mbid-2")

    def test_saves_releases_for_each_matched_artist(self):
        """각 매칭 아티스트 릴리즈가 save_releases로 저장되어야 한다."""
        with (
            patch("scheduler.get_all_artist_mbids", return_value=[]),
            patch("scheduler.musicbrainz.collect_artists", return_value=[]),
            patch("scheduler.save_artists"),
            patch("scheduler.get_matched_artist_mbids", return_value=["mbid-1", "mbid-2"]),
            patch("scheduler.release.collect_releases", return_value=[{"title": "앨범"}]),
            patch("scheduler.save_releases") as mock_save,
        ):
            run_initial_collect()

        assert mock_save.call_count == 2

    def test_skip_artists_skips_collect_and_save(self):
        """--skip-artists 시 collect_artists와 save_artists가 호출되지 않아야 한다."""
        with (
            patch("scheduler.get_all_artist_mbids", return_value=[]),
            patch("scheduler.musicbrainz.collect_artists") as mock_collect,
            patch("scheduler.save_artists") as mock_save,
        ):
            run_initial_collect(skip_artists=True)

        mock_collect.assert_not_called()
        mock_save.assert_not_called()



class TestRunStatusUpdate:
    def test_collects_concerts_and_updates_status(self):
        """kopis.collect 후 update_concert_status가 호출되어야 한다."""
        concerts = [{"kopis_id": "PF001", "prfstate": "공연완료", "updatedate": "2024-01-01"}]
        with (
            patch("scheduler.kopis.collect", return_value=concerts),
            patch("scheduler.update_concert_status") as mock_update,
            patch("scheduler.get_existing_kopis_ids", return_value={"PF001"}),
            patch("scheduler.get_all_aliases", return_value=[]),
            patch("scheduler.update_artist_is_coming"),
        ):
            run_status_update()

        mock_update.assert_called_once_with(concerts)

    def test_updates_is_coming_after_status_update(self):
        """상태 갱신 후 update_artist_is_coming이 인자 없이 호출되어야 한다."""
        with (
            patch("scheduler.kopis.collect", return_value=[]),
            patch("scheduler.update_concert_status"),
            patch("scheduler.get_existing_kopis_ids", return_value=set()),
            patch("scheduler.get_all_aliases", return_value=[]),
            patch("scheduler.update_artist_is_coming") as mock_update,
        ):
            run_status_update()

        mock_update.assert_called_once_with()

    def test_saves_new_concerts_with_alias_match(self):
        """DB에 없는 신규 공연이 alias 매칭 통과 시 save_concerts로 저장되어야 한다."""
        new_concert = {"kopis_id": "PF999", "prfstate": "공연예정"}
        with (
            patch("scheduler.kopis.collect", return_value=[new_concert]),
            patch("scheduler.update_concert_status"),
            patch("scheduler.get_existing_kopis_ids", return_value=set()),
            patch("scheduler.get_all_aliases", return_value=[]),
            patch("scheduler.has_match", return_value=True),
            patch("scheduler.save_concerts") as mock_save,
            patch("scheduler.get_unmatched_concerts", return_value=[]),
            patch("scheduler.save_concert_artists"),
            patch("scheduler.update_artist_is_coming"),
        ):
            run_status_update()

        mock_save.assert_called_once_with([new_concert])

    def test_skips_new_concerts_without_alias_match(self):
        """alias 매칭 없는 신규 공연은 save_concerts가 호출되지 않아야 한다."""
        new_concert = {"kopis_id": "PF999", "prfstate": "공연예정"}
        with (
            patch("scheduler.kopis.collect", return_value=[new_concert]),
            patch("scheduler.update_concert_status"),
            patch("scheduler.get_existing_kopis_ids", return_value=set()),
            patch("scheduler.get_all_aliases", return_value=[]),
            patch("scheduler.has_match", return_value=False),
            patch("scheduler.save_concerts") as mock_save,
            patch("scheduler.update_artist_is_coming"),
        ):
            run_status_update()

        mock_save.assert_not_called()

    def test_does_not_save_already_existing_concerts(self):
        """이미 DB에 있는 공연은 save_concerts가 호출되지 않아야 한다."""
        existing_concert = {"kopis_id": "PF001", "prfstate": "공연완료"}
        with (
            patch("scheduler.kopis.collect", return_value=[existing_concert]),
            patch("scheduler.update_concert_status"),
            patch("scheduler.get_existing_kopis_ids", return_value={"PF001"}),
            patch("scheduler.get_all_aliases", return_value=[]),
            patch("scheduler.has_match", return_value=True),
            patch("scheduler.save_concerts") as mock_save,
            patch("scheduler.update_artist_is_coming"),
        ):
            run_status_update()

        mock_save.assert_not_called()


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
    def test_registers_six_jobs(self):
        """스케줄러에 6개의 잡이 등록되어야 한다."""
        scheduler = _build_scheduler()
        assert len(scheduler.get_jobs()) == 6

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


class TestSortReleases:
    def test_album_before_single(self):
        """Album이 Single보다 앞에 와야 한다."""
        releases = [
            {"type": "Single", "title": "S"},
            {"type": "Album", "title": "A"},
        ]
        result = _sort_releases(releases)
        assert result[0]["type"] == "Album"
        assert result[1]["type"] == "Single"

    def test_album_ep_single_order(self):
        """Album → EP → Single 순서여야 한다."""
        releases = [
            {"type": "Single", "title": "S"},
            {"type": "EP", "title": "E"},
            {"type": "Album", "title": "A"},
        ]
        result = _sort_releases(releases)
        assert [r["type"] for r in result] == ["Album", "EP", "Single"]

    def test_unknown_type_goes_last(self):
        """알 수 없는 타입은 맨 뒤에 위치해야 한다."""
        releases = [
            {"type": "Live", "title": "L"},
            {"type": "Album", "title": "A"},
        ]
        result = _sort_releases(releases)
        assert result[0]["type"] == "Album"
        assert result[1]["type"] == "Live"

    def test_preserves_all_releases(self):
        """정렬 후 릴리즈 개수가 유지되어야 한다."""
        releases = [{"type": t} for t in ["Single", "Album", "EP", "Live"]]
        assert len(_sort_releases(releases)) == 4

    def test_empty_list(self):
        """빈 리스트를 넘기면 빈 리스트를 반환해야 한다."""
        assert _sort_releases([]) == []
