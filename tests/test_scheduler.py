"""scheduler.py 단위 테스트."""
import json
import os
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from scheduler import (
    _build_scheduler,
    _clear_progress,
    _is_banned,
    _load_progress,
    _progress_path,
    _save_ban,
    _save_progress,
    _sort_releases,
    collect_and_save_concert,
    collect_and_save_setlist,
    register_artist_by_mbid,
    run_artist_image_update,
    run_concert_status_update,
    run_initial_collect,
    run_missing_release_update,
    run_new_concert_collect,
    run_release_update,
    run_setlist_collect,
)


class TestRunInitialCollect:
    @pytest.fixture(autouse=True)
    def mock_sub_jobs(self):
        with (
            patch("scheduler.run_wikipedia_collect"),
            patch("scheduler.run_new_concert_collect"),
            patch("scheduler.get_matched_artists_with_spotify", return_value=[]),
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
        """매칭 아티스트 Spotify ID로 collect_releases가 호출되어야 한다."""
        artists = [
            {"artist_id": 1, "spotify_url": "https://open.spotify.com/artist/sp-1"},
            {"artist_id": 2, "spotify_url": "https://open.spotify.com/artist/sp-2"},
        ]
        with (
            patch("scheduler.get_all_artist_mbids", return_value=[]),
            patch("scheduler.musicbrainz.collect_artists", return_value=[]),
            patch("scheduler.save_artists"),
            patch("scheduler.get_matched_artists_with_spotify", return_value=artists),
            patch("scheduler.get_spotify_album_total", return_value=None),
            patch("scheduler.get_existing_release_spotify_ids", return_value=set()),
            patch("scheduler.release.collect_releases", return_value=([], 0)) as mock_collect,
            patch("scheduler.update_spotify_album_total"),
            patch("scheduler.save_releases"),
        ):
            run_initial_collect()

        assert mock_collect.call_count == 2
        mock_collect.assert_any_call("sp-1", skip_spotify_ids=set(), cached_total=None)
        mock_collect.assert_any_call("sp-2", skip_spotify_ids=set(), cached_total=None)

    def test_saves_releases_for_each_matched_artist(self):
        """각 매칭 아티스트 릴리즈가 save_releases로 저장되어야 한다."""
        artists = [
            {"artist_id": 1, "spotify_url": "https://open.spotify.com/artist/sp-1"},
            {"artist_id": 2, "spotify_url": "https://open.spotify.com/artist/sp-2"},
        ]
        with (
            patch("scheduler.get_all_artist_mbids", return_value=[]),
            patch("scheduler.musicbrainz.collect_artists", return_value=[]),
            patch("scheduler.save_artists"),
            patch("scheduler.get_matched_artists_with_spotify", return_value=artists),
            patch("scheduler.get_spotify_album_total", return_value=None),
            patch("scheduler.get_existing_release_spotify_ids", return_value=set()),
            patch("scheduler.release.collect_releases", return_value=([{"title": "앨범"}], 1)),
            patch("scheduler.update_spotify_album_total"),
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

    def test_calls_new_concert_collect_with_init_stdate_and_use_prfstate(self):
        """초기 수집은 stdate=20230101, use_prfstate=True로 KOPIS 수집을 호출해야 한다."""
        with (
            patch("scheduler.get_all_artist_mbids", return_value=[]),
            patch("scheduler.musicbrainz.collect_artists", return_value=[]),
            patch("scheduler.save_artists"),
            patch("scheduler.run_new_concert_collect") as mock_new_concert,
        ):
            run_initial_collect()

        mock_new_concert.assert_called_once_with(stdate="20230101", use_prfstate=True)

    def test_skip_kopis_does_not_call_new_concert_collect(self):
        """--skip-kopis 시 run_new_concert_collect가 호출되지 않아야 한다."""
        with (
            patch("scheduler.get_all_artist_mbids", return_value=[]),
            patch("scheduler.musicbrainz.collect_artists", return_value=[]),
            patch("scheduler.save_artists"),
            patch("scheduler.run_new_concert_collect") as mock_new_concert,
        ):
            run_initial_collect(skip_kopis=True)

        mock_new_concert.assert_not_called()


class TestRunConcertStatusUpdate:
    # ── 활성 공연 상태 갱신 잡 ─────────────────────────────────────────────────

    def test_calls_collect_by_id_for_each_active_concert(self):
        """활성 공연마다 kopis.collect_by_id가 호출되어야 한다."""
        active = [
            {"kopis_id": "PF001", "kopis_update_date": "2024-01-01"},
            {"kopis_id": "PF002", "kopis_update_date": "2024-01-01"},
        ]
        fetched = {"kopis_id": "PF001", "prfstate": "공연중", "updatedate": "2024-01-01"}
        with (
            patch("scheduler.get_active_concerts", return_value=active),
            patch("scheduler.kopis.collect_by_id", return_value=fetched) as mock_by_id,
            patch("scheduler.update_concert_status"),
            patch("scheduler.update_artist_is_coming"),
        ):
            run_concert_status_update()

        assert mock_by_id.call_count == 2
        mock_by_id.assert_any_call("PF001")
        mock_by_id.assert_any_call("PF002")

    def test_update_concert_status_called_with_fetched_results(self):
        """collect_by_id 결과로 update_concert_status가 호출되어야 한다."""
        active = [{"kopis_id": "PF001", "kopis_update_date": "2024-01-01"}]
        fetched = {"kopis_id": "PF001", "prfstate": "공연완료", "updatedate": "2024-02-01"}
        with (
            patch("scheduler.get_active_concerts", return_value=active),
            patch("scheduler.kopis.collect_by_id", return_value=fetched),
            patch("scheduler.update_concert_status") as mock_update,
            patch("scheduler.update_artist_is_coming"),
        ):
            run_concert_status_update()

        mock_update.assert_called_once_with([fetched])

    def test_skips_status_update_when_no_active_concerts(self):
        """활성 공연이 없으면 collect_by_id·update_concert_status가 호출되지 않아야 한다."""
        with (
            patch("scheduler.get_active_concerts", return_value=[]),
            patch("scheduler.kopis.collect_by_id") as mock_by_id,
            patch("scheduler.update_concert_status") as mock_update,
            patch("scheduler.update_artist_is_coming"),
        ):
            run_concert_status_update()

        mock_by_id.assert_not_called()
        mock_update.assert_not_called()

    def test_skips_none_results_from_collect_by_id(self):
        """collect_by_id가 None을 반환하면 update_concert_status 호출 대상에서 제외되어야 한다."""
        active = [{"kopis_id": "PF001", "kopis_update_date": "2024-01-01"}]
        with (
            patch("scheduler.get_active_concerts", return_value=active),
            patch("scheduler.kopis.collect_by_id", return_value=None),
            patch("scheduler.update_concert_status") as mock_update,
            patch("scheduler.update_artist_is_coming"),
        ):
            run_concert_status_update()

        mock_update.assert_not_called()

    def test_updates_is_coming_after_status_update(self):
        """상태 갱신 후 update_artist_is_coming이 인자 없이 호출되어야 한다."""
        with (
            patch("scheduler.get_active_concerts", return_value=[]),
            patch("scheduler.update_artist_is_coming") as mock_update,
        ):
            run_concert_status_update()

        mock_update.assert_called_once_with()


class TestRunNewConcertCollect:
    # ── 신규 공연 탐지 잡 ─────────────────────────────────────────────────────

    def test_updates_is_coming_after_new_concert_collect(self):
        """신규 공연 탐지 후 update_artist_is_coming이 인자 없이 호출되어야 한다."""
        with (
            patch("scheduler.kopis.collect", return_value=[]),
            patch("scheduler.get_existing_kopis_ids", return_value=set()),
            patch("scheduler.get_all_aliases", return_value=[]),
            patch("scheduler.update_artist_is_coming") as mock_update,
        ):
            run_new_concert_collect()

        mock_update.assert_called_once_with()

    def test_saves_new_concerts_with_alias_match(self):
        """DB에 없는 신규 공연이 alias 매칭 통과 시 save_concerts로 저장되어야 한다."""
        new_concert = {"kopis_id": "PF999", "prfstate": "공연예정"}
        with (
            patch("scheduler.kopis.collect", return_value=[new_concert]),
            patch("scheduler.get_existing_kopis_ids", return_value=set()),
            patch("scheduler.get_all_aliases", return_value=[]),
            patch("scheduler.has_match", return_value=True),
            patch("scheduler.save_concerts") as mock_save,
            patch("scheduler.get_unmatched_concerts", return_value=[]),
            patch("scheduler.save_concert_artists"),
            patch("scheduler.update_artist_is_coming"),
        ):
            run_new_concert_collect()

        mock_save.assert_called_once_with([new_concert], use_prfstate=False)

    def test_saves_with_actual_prfstate_when_use_prfstate_true(self):
        """use_prfstate=True로 호출 시 save_concerts에 use_prfstate=True가 전달되어야 한다."""
        new_concert = {"kopis_id": "PF999", "prfstate": "공연예정"}
        with (
            patch("scheduler.kopis.collect", return_value=[new_concert]),
            patch("scheduler.get_existing_kopis_ids", return_value=set()),
            patch("scheduler.get_all_aliases", return_value=[]),
            patch("scheduler.has_match", return_value=True),
            patch("scheduler.save_concerts") as mock_save,
            patch("scheduler.get_unmatched_concerts", return_value=[]),
            patch("scheduler.save_concert_artists"),
            patch("scheduler.update_artist_is_coming"),
        ):
            run_new_concert_collect(use_prfstate=True)

        mock_save.assert_called_once_with([new_concert], use_prfstate=True)

    def test_skips_new_concerts_without_alias_match(self):
        """alias 매칭 없는 신규 공연은 save_concerts가 호출되지 않아야 한다."""
        new_concert = {"kopis_id": "PF999", "prfstate": "공연예정"}
        with (
            patch("scheduler.kopis.collect", return_value=[new_concert]),
            patch("scheduler.get_existing_kopis_ids", return_value=set()),
            patch("scheduler.get_all_aliases", return_value=[]),
            patch("scheduler.has_match", return_value=False),
            patch("scheduler.save_concerts") as mock_save,
            patch("scheduler.update_artist_is_coming"),
        ):
            run_new_concert_collect()

        mock_save.assert_not_called()

    def test_does_not_save_already_existing_concerts(self):
        """이미 DB에 있는 공연은 save_concerts가 호출되지 않아야 한다."""
        existing_concert = {"kopis_id": "PF001", "prfstate": "공연완료"}
        with (
            patch("scheduler.kopis.collect", return_value=[existing_concert]),
            patch("scheduler.get_existing_kopis_ids", return_value={"PF001"}),
            patch("scheduler.get_all_aliases", return_value=[]),
            patch("scheduler.has_match", return_value=True),
            patch("scheduler.save_concerts") as mock_save,
            patch("scheduler.update_artist_is_coming"),
        ):
            run_new_concert_collect()

        mock_save.assert_not_called()


class TestRunReleaseUpdate:
    def test_collects_releases_for_all_spotify_artists(self):
        """내한 매칭 아티스트에 대해 collect_releases가 호출되어야 한다."""
        artists = [
            {"artist_id": 1, "spotify_url": "https://open.spotify.com/artist/sp-1"},
            {"artist_id": 2, "spotify_url": "https://open.spotify.com/artist/sp-2"},
        ]
        with (
            patch("scheduler.get_matched_artists_with_spotify", return_value=artists),
            patch("scheduler.get_spotify_album_total", return_value=None),
            patch("scheduler.get_existing_release_spotify_ids", return_value=set()),
            patch("scheduler.release.collect_releases", return_value=([], 0)) as mock_collect,
            patch("scheduler.update_spotify_album_total"),
            patch("scheduler.save_releases"),
        ):
            run_release_update()

        assert mock_collect.call_count == 2
        mock_collect.assert_any_call("sp-1", skip_spotify_ids=set(), cached_total=None)
        mock_collect.assert_any_call("sp-2", skip_spotify_ids=set(), cached_total=None)

    def test_saves_releases_with_artist_id(self):
        """릴리즈가 artist_id와 함께 save_releases로 저장되어야 한다."""
        releases = [{"spotify_id": "alb-1"}]
        artists = [{"artist_id": 99, "spotify_url": "https://open.spotify.com/artist/sp-1"}]
        with (
            patch("scheduler.get_matched_artists_with_spotify", return_value=artists),
            patch("scheduler.get_spotify_album_total", return_value=None),
            patch("scheduler.get_existing_release_spotify_ids", return_value=set()),
            patch("scheduler.release.collect_releases", return_value=(releases, 1)),
            patch("scheduler.update_spotify_album_total"),
            patch("scheduler.save_releases") as mock_save,
        ):
            run_release_update()

        mock_save.assert_called_once_with(99, releases)

    def test_no_db_calls_when_no_artists(self):
        """아티스트가 없으면 collect_releases가 호출되지 않아야 한다."""
        with (
            patch("scheduler.get_matched_artists_with_spotify", return_value=[]),
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

    def test_includes_daily_concert_status_job(self):
        """매일 실행되는 공연 상태 갱신 잡이 등록되어야 한다."""
        scheduler = _build_scheduler()
        job_funcs = [job.func for job in scheduler.get_jobs()]
        assert run_concert_status_update in job_funcs

    def test_includes_daily_new_concert_collect_job(self):
        """매일 실행되는 신규 공연 탐지 잡이 등록되어야 한다."""
        scheduler = _build_scheduler()
        job_funcs = [job.func for job in scheduler.get_jobs()]
        assert run_new_concert_collect in job_funcs

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

    def test_album_single_order(self):
        """Album → Single 순서여야 한다 (EP는 Spotify에서 미지원)."""
        releases = [
            {"type": "Single", "title": "S"},
            {"type": "Album", "title": "A"},
        ]
        result = _sort_releases(releases)
        assert [r["type"] for r in result] == ["Album", "Single"]

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
        releases = [{"type": t} for t in ["Single", "Album", "Live"]]
        assert len(_sort_releases(releases)) == 3

    def test_empty_list(self):
        """빈 리스트를 넘기면 빈 리스트를 반환해야 한다."""
        assert _sort_releases([]) == []


class TestRegisterArtistByMbid:
    _ARTIST = {
        "mbid": "mbid-test",
        "name": "TestArtist",
        "sort_name": "TestArtist",
        "aliases": [],
        "url_rels": [{"type": "Spotify", "url": "https://open.spotify.com/artist/sp999"}],
    }
    _SAVED = {"id": 42, "name": "TestArtist", "spotify_url": "https://open.spotify.com/artist/sp999"}

    def test_returns_ok_status_on_success(self):
        """모든 단계 성공 시 status:ok와 아티스트 정보를 반환해야 한다."""
        with (
            patch("scheduler.musicbrainz.collect_single_artist", return_value=self._ARTIST),
            patch("scheduler.save_artists"),
            patch("scheduler.get_artist_by_mbid", return_value=self._SAVED),
            patch(
                "scheduler.artist_image.collect_artist_image",
                return_value=("http://img.url", "sp999"),
            ),
            patch("scheduler.update_artist_image"),
        ):
            result = register_artist_by_mbid("mbid-test")

        assert result == {
            "status": "ok",
            "artist_id": 42,
            "mbid": "mbid-test",
            "name": "TestArtist",
            "image_url": "http://img.url",
            "aliases": [],
        }

    def test_returns_not_found_when_collect_fails(self):
        """MusicBrainz 수집 실패 시 status:not_found를 반환해야 한다."""
        with patch("scheduler.musicbrainz.collect_single_artist", return_value=None):
            assert register_artist_by_mbid("mbid-bad") == {"status": "not_found"}

    def test_raises_when_db_lookup_fails(self):
        """저장 직후 DB에서 아티스트를 찾지 못하면 RuntimeError를 발생시켜야 한다."""
        with (
            patch("scheduler.musicbrainz.collect_single_artist", return_value=self._ARTIST),
            patch("scheduler.save_artists"),
            patch("scheduler.get_artist_by_mbid", return_value=None),
            pytest.raises(RuntimeError),
        ):
            register_artist_by_mbid("mbid-test")

    def test_saves_artist_before_image_collection(self):
        """save_artists가 이미지 수집보다 먼저 호출되어야 한다."""
        call_order = []
        with (
            patch(
                "scheduler.musicbrainz.collect_single_artist", return_value=self._ARTIST
            ),
            patch("scheduler.save_artists", side_effect=lambda _: call_order.append("save")),
            patch("scheduler.get_artist_by_mbid", return_value=self._SAVED),
            patch(
                "scheduler.artist_image.collect_artist_image",
                side_effect=lambda *a, **kw: call_order.append("image")
                or ("http://img", "sp999"),
            ),
            patch("scheduler.update_artist_image"),
        ):
            register_artist_by_mbid("mbid-test")

        assert call_order == ["save", "image"]

    def test_skips_image_collection_without_spotify(self):
        """Spotify URL이 없으면 이미지 수집을 건너뛰고 image_url은 None이어야 한다."""
        saved_no_spotify = {"id": 99, "name": "NoSpot", "spotify_url": None}
        with (
            patch("scheduler.musicbrainz.collect_single_artist", return_value=self._ARTIST),
            patch("scheduler.save_artists"),
            patch("scheduler.get_artist_by_mbid", return_value=saved_no_spotify),
            patch("scheduler.artist_image.collect_artist_image") as mock_img,
        ):
            result = register_artist_by_mbid("mbid-test")

        assert result["status"] == "ok"
        assert result["image_url"] is None
        mock_img.assert_not_called()


class TestCollectAndSaveConcert:
    _CONCERT_RAW = {"prfnm": "TestArtist Live", "visit": "Y"}
    _ALIASES = [{"artist_id": 1, "name": "TestArtist"}]
    _CONCERT_ROW = {"concert_id": 10, "title": "TestArtist Live", "cast": "TestArtist"}

    def test_returns_not_found_when_kopis_has_no_data(self):
        """KOPIS에 공연 데이터가 없으면 status:not_found를 반환해야 한다."""
        with patch("scheduler.kopis.collect_by_id", return_value=None):
            assert collect_and_save_concert("PF000") == {"status": "not_found"}

    def test_returns_skipped_when_not_touring(self):
        """내한 공연이 아니면 status:skipped, reason:not_touring을 반환해야 한다."""
        concert = {**self._CONCERT_RAW, "visit": "N"}
        with patch("scheduler.kopis.collect_by_id", return_value=concert):
            result = collect_and_save_concert("PF001")
        assert result == {"status": "skipped", "reason": "not_touring"}

    def test_returns_skipped_when_no_alias_match(self):
        """alias 매칭이 없으면 status:skipped, reason:no_alias_match를 반환해야 한다."""
        with (
            patch("scheduler.kopis.collect_by_id", return_value=self._CONCERT_RAW),
            patch("scheduler.get_all_aliases", return_value=self._ALIASES),
            patch("scheduler.has_match", return_value=False),
        ):
            result = collect_and_save_concert("PF001")
        assert result == {"status": "skipped", "reason": "no_alias_match"}

    def test_returns_ok_with_matched_artists_on_success(self):
        """매칭 성공 시 status:ok와 matched_artists를 반환해야 한다."""
        with (
            patch("scheduler.kopis.collect_by_id", return_value=self._CONCERT_RAW),
            patch("scheduler.get_all_aliases", return_value=self._ALIASES),
            patch("scheduler.has_match", return_value=True),
            patch("scheduler.save_concerts"),
            patch("scheduler.get_concert_by_kopis_id", return_value=self._CONCERT_ROW),
            patch(
                "scheduler.match_concert",
                return_value=([{"concert_id": 10, "artist_id": 1}], []),
            ),
            patch("scheduler.save_concert_artists"),
            patch("scheduler.update_artist_is_coming"),
        ):
            result = collect_and_save_concert("PF001")
        assert result == {
            "status": "ok",
            "concert_id": 10,
            "title": "TestArtist Live",
            "matched_artists": [{"artist_id": 1, "name": "TestArtist"}],
        }

    def test_returns_ok_with_empty_matches_when_no_match_found(self):
        """저장은 됐지만 실제 매칭이 0건이면 matched_artists 빈 리스트로 성공 반환해야 한다."""
        with (
            patch("scheduler.kopis.collect_by_id", return_value=self._CONCERT_RAW),
            patch("scheduler.get_all_aliases", return_value=self._ALIASES),
            patch("scheduler.has_match", return_value=True),
            patch("scheduler.save_concerts"),
            patch("scheduler.get_concert_by_kopis_id", return_value=self._CONCERT_ROW),
            patch("scheduler.match_concert", return_value=([], [{"concert_id": 10}])),
        ):
            result = collect_and_save_concert("PF001")
        assert result["status"] == "ok"
        assert result["matched_artists"] == []

    def test_raises_when_db_lookup_fails_after_save(self):
        """저장 직후 재조회에 실패하면 RuntimeError를 발생시켜야 한다."""
        with (
            patch("scheduler.kopis.collect_by_id", return_value=self._CONCERT_RAW),
            patch("scheduler.get_all_aliases", return_value=self._ALIASES),
            patch("scheduler.has_match", return_value=True),
            patch("scheduler.save_concerts"),
            patch("scheduler.get_concert_by_kopis_id", return_value=None),
            pytest.raises(RuntimeError),
        ):
            collect_and_save_concert("PF001")


class TestCollectAndSaveSetlist:
    _CONCERT = {
        "concert_id": 10,
        "start_date": "2024-06-01",
        "end_date": "2024-06-02",
        "artist_mbid": "mbid-test",
    }
    _SETLIST_RESULT = {
        "concert_id": 10,
        "setlist_fm_id": "abc123",
        "attribution_url": "https://setlist.fm/abc123",
        "tracks": [{"position": 1, "song_name": "Song A", "info": None}],
    }

    def test_returns_not_found_when_concert_missing(self):
        """공연 조회 실패 시 status:not_found를 반환해야 한다."""
        with patch("scheduler.get_concert_with_artist", return_value=None):
            assert collect_and_save_setlist(999) == {"status": "not_found"}

    def test_returns_skipped_when_no_setlist_found(self):
        """셋리스트가 없으면 status:skipped, reason:no_setlist_found를 반환해야 한다."""
        with (
            patch("scheduler.get_concert_with_artist", return_value=self._CONCERT),
            patch("scheduler.setlist.collect_for_concert", return_value=None),
        ):
            result = collect_and_save_setlist(10)
        assert result == {"status": "skipped", "reason": "no_setlist_found"}

    def test_returns_ok_with_tracks_on_success(self):
        """셋리스트 수집 성공 시 status:ok와 트랙 정보를 반환해야 한다."""
        with (
            patch("scheduler.get_concert_with_artist", return_value=self._CONCERT),
            patch(
                "scheduler.setlist.collect_for_concert",
                return_value=self._SETLIST_RESULT,
            ),
            patch("scheduler.save_setlists") as mock_save,
        ):
            result = collect_and_save_setlist(10)
        mock_save.assert_called_once_with([self._SETLIST_RESULT])
        assert result == {
            "status": "ok",
            "concert_id": 10,
            "setlist_fm_id": "abc123",
            "attribution_url": "https://setlist.fm/abc123",
            "tracks": [{"position": 1, "song_name": "Song A", "info": None}],
        }


# ---------------------------------------------------------------------------
# 체크포인트 헬퍼 — progress (잡별 진행 상태)
# ---------------------------------------------------------------------------
class TestCheckpointProgress:
    def test_load_returns_empty_set_when_no_file(self, tmp_path, monkeypatch):
        """체크포인트 파일 없으면 빈 집합 반환."""
        monkeypatch.setattr("scheduler._CHECKPOINT_DIR", str(tmp_path))
        assert _load_progress("release_update") == set()

    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        """저장 후 로드하면 같은 집합이 복원되어야 한다."""
        monkeypatch.setattr("scheduler._CHECKPOINT_DIR", str(tmp_path))
        _save_progress("release_update", {1, 2, 3})
        assert _load_progress("release_update") == {1, 2, 3}

    def test_clear_removes_file(self, tmp_path, monkeypatch):
        """_clear_progress 후 파일이 삭제되어야 한다."""
        monkeypatch.setattr("scheduler._CHECKPOINT_DIR", str(tmp_path))
        _save_progress("release_update", {10})
        assert os.path.exists(_progress_path("release_update"))
        _clear_progress("release_update")
        assert not os.path.exists(_progress_path("release_update"))

    def test_load_returns_empty_on_corrupt_file(self, tmp_path, monkeypatch):
        """파일이 손상됐을 때 빈 집합을 반환해야 한다."""
        monkeypatch.setattr("scheduler._CHECKPOINT_DIR", str(tmp_path))
        path = _progress_path("release_update")
        with open(path, "w") as f:
            f.write("not-json{{{")
        assert _load_progress("release_update") == set()

    def test_jobs_use_separate_files(self, tmp_path, monkeypatch):
        """잡마다 독립적인 파일을 사용해야 한다."""
        monkeypatch.setattr("scheduler._CHECKPOINT_DIR", str(tmp_path))
        _save_progress("release_update", {1, 2})
        _save_progress("missing_release", {10, 20})
        assert _load_progress("release_update") == {1, 2}
        assert _load_progress("missing_release") == {10, 20}


# ---------------------------------------------------------------------------
# 체크포인트 헬퍼 — ban (Spotify API 밴 상태)
# ---------------------------------------------------------------------------
class TestIsBanned:
    def test_returns_false_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("scheduler._BAN_PATH", str(tmp_path / "spotify_ban.json"))
        assert _is_banned() is False

    def test_returns_true_within_ban_period(self, tmp_path, monkeypatch):
        from datetime import datetime, timedelta
        ban_path = str(tmp_path / "spotify_ban.json")
        monkeypatch.setattr("scheduler._BAN_PATH", ban_path)
        future = (datetime.now() + timedelta(hours=20)).isoformat(timespec="seconds")
        with open(ban_path, "w") as f:
            json.dump({"banned_until": future}, f)
        assert _is_banned() is True

    def test_returns_false_after_ban_expired(self, tmp_path, monkeypatch):
        from datetime import datetime, timedelta
        ban_path = str(tmp_path / "spotify_ban.json")
        monkeypatch.setattr("scheduler._BAN_PATH", ban_path)
        past = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
        with open(ban_path, "w") as f:
            json.dump({"banned_until": past}, f)
        assert _is_banned() is False

    def test_save_ban_writes_banned_until(self, tmp_path, monkeypatch):
        """_save_ban 후 spotify_ban.json에 banned_until이 저장되어야 한다."""
        ban_path = str(tmp_path / "spotify_ban.json")
        monkeypatch.setattr("scheduler._BAN_PATH", ban_path)
        monkeypatch.setattr("scheduler._CHECKPOINT_DIR", str(tmp_path))
        _save_ban()
        data = json.load(open(ban_path))
        assert "banned_until" in data

    def test_save_ban_without_retry_after_uses_fixed_margin(self, tmp_path, monkeypatch):
        """retry_after 없으면 기존 고정 _BAN_MARGIN_HOURS 기준으로 계산해야 한다."""
        ban_path = str(tmp_path / "spotify_ban.json")
        monkeypatch.setattr("scheduler._BAN_PATH", ban_path)
        monkeypatch.setattr("scheduler._CHECKPOINT_DIR", str(tmp_path))
        before = datetime.now()
        banned_until = _save_ban()
        expected = before + timedelta(hours=25)
        assert abs((banned_until - expected).total_seconds()) < 5

    def test_save_ban_with_retry_after_uses_measured_value(self, tmp_path, monkeypatch):
        """retry_after가 있으면 실측값 + 5초 마진 기준으로 계산해야 한다."""
        ban_path = str(tmp_path / "spotify_ban.json")
        monkeypatch.setattr("scheduler._BAN_PATH", ban_path)
        monkeypatch.setattr("scheduler._CHECKPOINT_DIR", str(tmp_path))
        before = datetime.now()
        banned_until = _save_ban(retry_after_seconds=30)
        expected = before + timedelta(seconds=35)
        assert abs((banned_until - expected).total_seconds()) < 5


# ---------------------------------------------------------------------------
# run_release_update — 체크포인트 + total 캐시
# ---------------------------------------------------------------------------
class TestRunReleaseUpdateCheckpoint:
    _ARTISTS = [
        {"artist_id": 1, "spotify_url": "https://open.spotify.com/artist/sp-1"},
        {"artist_id": 2, "spotify_url": "https://open.spotify.com/artist/sp-2"},
    ]

    def test_skips_already_completed_artist(self, tmp_path, monkeypatch):
        """체크포인트에 있는 artist_id는 collect_releases 호출 없이 건너뜀."""
        monkeypatch.setattr("scheduler._CHECKPOINT_DIR", str(tmp_path))
        monkeypatch.setattr("scheduler._BAN_PATH", str(tmp_path / "spotify_ban.json"))
        _save_progress("release_update", {1})
        with (
            patch("scheduler.get_matched_artists_with_spotify", return_value=self._ARTISTS),
            patch("scheduler.get_spotify_album_total", return_value=None),
            patch("scheduler.get_existing_release_spotify_ids", return_value=set()),
            patch("scheduler.release.collect_releases", return_value=([], 0)) as mock_collect,
            patch("scheduler.update_spotify_album_total"),
            patch("scheduler.save_releases"),
        ):
            run_release_update()

        assert mock_collect.call_count == 1
        mock_collect.assert_called_once_with("sp-2", skip_spotify_ids=set(), cached_total=None)

    def test_saves_ban_and_progress_on_429(self, tmp_path, monkeypatch):
        """429 발생 시 spotify_ban.json과 잡별 progress 파일이 저장되어야 한다."""
        monkeypatch.setattr("scheduler._CHECKPOINT_DIR", str(tmp_path))
        ban_path = str(tmp_path / "spotify_ban.json")
        monkeypatch.setattr("scheduler._BAN_PATH", ban_path)
        from collectors.spotify_client import SpotifyRateLimitError

        with (
            patch("scheduler.get_matched_artists_with_spotify", return_value=self._ARTISTS),
            patch("scheduler.get_spotify_album_total", return_value=None),
            patch("scheduler.get_existing_release_spotify_ids", return_value=set()),
            patch(
                "scheduler.release.collect_releases",
                side_effect=[([], 0), SpotifyRateLimitError()],
            ),
            patch("scheduler.update_spotify_album_total"),
            patch("scheduler.save_releases"),
        ):
            run_release_update()

        assert os.path.exists(ban_path)
        assert "banned_until" in json.load(open(ban_path))
        completed = _load_progress("release_update")
        assert 1 in completed
        assert 2 not in completed

    def test_reschedules_on_ban_lift_when_429(self, tmp_path, monkeypatch):
        """429 발생 시 밴 해제 시각에 run_release_update를 재등록해야 한다."""
        monkeypatch.setattr("scheduler._CHECKPOINT_DIR", str(tmp_path))
        monkeypatch.setattr("scheduler._BAN_PATH", str(tmp_path / "spotify_ban.json"))
        from unittest.mock import MagicMock

        from collectors.spotify_client import SpotifyRateLimitError

        mock_scheduler = MagicMock()
        monkeypatch.setattr("scheduler._scheduler", mock_scheduler)

        with (
            patch("scheduler.get_matched_artists_with_spotify", return_value=self._ARTISTS),
            patch("scheduler.get_spotify_album_total", return_value=None),
            patch("scheduler.get_existing_release_spotify_ids", return_value=set()),
            patch(
                "scheduler.release.collect_releases",
                side_effect=[([], 0), SpotifyRateLimitError(retry_after=30)],
            ),
            patch("scheduler.update_spotify_album_total"),
            patch("scheduler.save_releases"),
        ):
            run_release_update()

        mock_scheduler.add_job.assert_called_once()
        _, kwargs = mock_scheduler.add_job.call_args
        assert kwargs["id"] == "resume_run_release_update"
        assert kwargs["replace_existing"] is True

    def test_clears_progress_on_normal_completion(self, tmp_path, monkeypatch):
        """정상 완료 시 잡별 progress 파일을 삭제해야 한다."""
        monkeypatch.setattr("scheduler._CHECKPOINT_DIR", str(tmp_path))
        monkeypatch.setattr("scheduler._BAN_PATH", str(tmp_path / "spotify_ban.json"))
        _save_progress("release_update", {99})

        with (
            patch("scheduler.get_matched_artists_with_spotify", return_value=self._ARTISTS),
            patch("scheduler.get_spotify_album_total", return_value=None),
            patch("scheduler.get_existing_release_spotify_ids", return_value=set()),
            patch("scheduler.release.collect_releases", return_value=([], 0)),
            patch("scheduler.update_spotify_album_total"),
            patch("scheduler.save_releases"),
        ):
            run_release_update()

        assert not os.path.exists(_progress_path("release_update"))

    def test_updates_spotify_album_total_when_nonzero(self, tmp_path, monkeypatch):
        """spotify_total > 0이면 update_spotify_album_total이 호출되어야 한다."""
        monkeypatch.setattr("scheduler._CHECKPOINT_DIR", str(tmp_path))
        monkeypatch.setattr("scheduler._BAN_PATH", str(tmp_path / "spotify_ban.json"))
        artists = [{"artist_id": 5, "spotify_url": "https://open.spotify.com/artist/sp-5"}]
        with (
            patch("scheduler.get_matched_artists_with_spotify", return_value=artists),
            patch("scheduler.get_spotify_album_total", return_value=None),
            patch("scheduler.get_existing_release_spotify_ids", return_value=set()),
            patch("scheduler.release.collect_releases", return_value=([], 10)),
            patch("scheduler.update_spotify_album_total") as mock_update,
            patch("scheduler.save_releases"),
        ):
            run_release_update()

        mock_update.assert_called_once_with(5, 10)

    def test_skips_save_releases_when_no_new_releases(self, tmp_path, monkeypatch):
        """신규 릴리즈 없으면 save_releases가 호출되지 않아야 한다."""
        monkeypatch.setattr("scheduler._CHECKPOINT_DIR", str(tmp_path))
        monkeypatch.setattr("scheduler._BAN_PATH", str(tmp_path / "spotify_ban.json"))
        artists = [{"artist_id": 7, "spotify_url": "https://open.spotify.com/artist/sp-7"}]
        with (
            patch("scheduler.get_matched_artists_with_spotify", return_value=artists),
            patch("scheduler.get_spotify_album_total", return_value=5),
            patch("scheduler.get_existing_release_spotify_ids", return_value=set()),
            patch("scheduler.release.collect_releases", return_value=([], 5)),
            patch("scheduler.update_spotify_album_total"),
            patch("scheduler.save_releases") as mock_save,
        ):
            run_release_update()

        mock_save.assert_not_called()

    def test_skips_all_when_banned(self, tmp_path, monkeypatch):
        """banned_until이 유효하면 collect_releases를 호출하지 않아야 한다."""
        from datetime import datetime, timedelta
        ban_path = str(tmp_path / "spotify_ban.json")
        monkeypatch.setattr("scheduler._BAN_PATH", ban_path)
        future = (datetime.now() + timedelta(hours=20)).isoformat(timespec="seconds")
        with open(ban_path, "w") as f:
            json.dump({"banned_until": future}, f)
        with patch("scheduler.release.collect_releases") as mock_collect:
            run_release_update()
        mock_collect.assert_not_called()


# ---------------------------------------------------------------------------
# run_artist_image_update — ban 가드
# ---------------------------------------------------------------------------
class TestRunArtistImageUpdateBanGuard:
    def test_skips_when_banned(self, tmp_path, monkeypatch):
        """banned_until이 유효하면 이미지 수집을 실행하지 않아야 한다."""
        from datetime import datetime, timedelta
        ban_path = str(tmp_path / "spotify_ban.json")
        monkeypatch.setattr("scheduler._BAN_PATH", ban_path)
        future = (datetime.now() + timedelta(hours=20)).isoformat(timespec="seconds")
        with open(ban_path, "w") as f:
            json.dump({"banned_until": future}, f)
        with patch("scheduler.artist_image.collect_artist_image") as mock_collect:
            run_artist_image_update()
        mock_collect.assert_not_called()

    def test_saves_ban_and_stops_on_429(self, tmp_path, monkeypatch):
        """429 발생 시 즉시 중단하고 ban을 저장하며, 이후 아티스트는 호출하지 않아야 한다."""
        from collectors.spotify_client import SpotifyRateLimitError

        monkeypatch.setattr("scheduler._CHECKPOINT_DIR", str(tmp_path))
        ban_path = str(tmp_path / "spotify_ban.json")
        monkeypatch.setattr("scheduler._BAN_PATH", ban_path)
        monkeypatch.setattr("scheduler._IMAGE_FAILED_PATH", str(tmp_path / "image_failed.json"))
        artists = [
            {"id": 1, "mbid": "mbid-1", "name": "A1", "spotify_url": None},
            {"id": 2, "mbid": "mbid-2", "name": "A2", "spotify_url": None},
        ]

        with (
            patch("scheduler.get_artists_without_image", return_value=artists),
            patch(
                "scheduler.artist_image.collect_artist_image",
                side_effect=SpotifyRateLimitError(),
            ) as mock_collect,
        ):
            run_artist_image_update()

        assert mock_collect.call_count == 1
        assert os.path.exists(ban_path)
        assert "banned_until" in json.load(open(ban_path))

    def test_reschedules_on_ban_lift_when_429(self, tmp_path, monkeypatch):
        """429 발생 시 밴 해제 시각에 run_artist_image_update를 재등록해야 한다."""
        from unittest.mock import MagicMock

        from collectors.spotify_client import SpotifyRateLimitError

        monkeypatch.setattr("scheduler._CHECKPOINT_DIR", str(tmp_path))
        monkeypatch.setattr("scheduler._BAN_PATH", str(tmp_path / "spotify_ban.json"))
        monkeypatch.setattr("scheduler._IMAGE_FAILED_PATH", str(tmp_path / "image_failed.json"))
        mock_scheduler = MagicMock()
        monkeypatch.setattr("scheduler._scheduler", mock_scheduler)
        artists = [{"id": 1, "mbid": "mbid-1", "name": "A1", "spotify_url": None}]

        with (
            patch("scheduler.get_artists_without_image", return_value=artists),
            patch(
                "scheduler.artist_image.collect_artist_image",
                side_effect=SpotifyRateLimitError(retry_after=30),
            ),
        ):
            run_artist_image_update()

        mock_scheduler.add_job.assert_called_once()
        _, kwargs = mock_scheduler.add_job.call_args
        assert kwargs["id"] == "resume_run_artist_image_update"
        assert kwargs["replace_existing"] is True


class TestRunArtistImageUpdate:
    """run_artist_image_update()의 fallback Spotify URL 백필 검증."""

    _ARTIST_NO_SPOTIFY = {"id": 1, "mbid": "mbid-1", "name": "NoSpotifyLink", "spotify_url": None}
    _ARTIST_WITH_SPOTIFY = {
        "id": 2,
        "mbid": "mbid-2",
        "name": "HasSpotifyLink",
        "spotify_url": "https://open.spotify.com/artist/existing",
    }

    @pytest.fixture(autouse=True)
    def isolate_image_failed_checkpoint(self, tmp_path, monkeypatch):
        monkeypatch.setattr("scheduler._IMAGE_FAILED_PATH", str(tmp_path / "image_failed.json"))

    def test_upserts_artist_url_when_fallback_finds_spotify_id(self):
        """spotify_url이 없었는데 fallback으로 찾았다면 artist_url에 저장해야 한다."""
        with (
            patch("scheduler.get_artists_without_image", return_value=[self._ARTIST_NO_SPOTIFY]),
            patch(
                "scheduler.artist_image.collect_artist_image",
                return_value=("http://img.url", "found-id"),
            ),
            patch("scheduler.update_artist_image") as mock_update_image,
            patch("scheduler.upsert_artist_url") as mock_upsert,
        ):
            run_artist_image_update()

        mock_update_image.assert_called_once_with(1, "http://img.url")
        mock_upsert.assert_called_once_with(
            1, "Spotify", "https://open.spotify.com/artist/found-id"
        )

    def test_does_not_upsert_when_spotify_url_already_present(self):
        """이미 spotify_url이 있던 아티스트는 artist_url을 다시 저장하지 않아야 한다."""
        with (
            patch(
                "scheduler.get_artists_without_image", return_value=[self._ARTIST_WITH_SPOTIFY]
            ),
            patch(
                "scheduler.artist_image.collect_artist_image",
                return_value=("http://img.url", "existing"),
            ),
            patch("scheduler.update_artist_image"),
            patch("scheduler.upsert_artist_url") as mock_upsert,
        ):
            run_artist_image_update()

        mock_upsert.assert_not_called()

    def test_does_not_upsert_when_spotify_id_not_found(self):
        """spotify_id조차 못 찾으면 artist_url을 저장하지 않아야 한다."""
        with (
            patch("scheduler.get_artists_without_image", return_value=[self._ARTIST_NO_SPOTIFY]),
            patch(
                "scheduler.artist_image.collect_artist_image",
                return_value=(None, None),
            ),
            patch("scheduler.update_artist_image") as mock_update_image,
            patch("scheduler.upsert_artist_url") as mock_upsert,
        ):
            run_artist_image_update()

        mock_update_image.assert_not_called()
        mock_upsert.assert_not_called()


# ---------------------------------------------------------------------------
# run_artist_image_update — image_failed 체크포인트 기반 재시도 보류
# ---------------------------------------------------------------------------
class TestRunArtistImageUpdateRetrySkip:
    _ARTIST = {"id": 1, "mbid": "mbid-1", "name": "아티스트", "spotify_url": None}

    def test_skips_artist_failed_within_retry_window(self, tmp_path, monkeypatch):
        """최근 실패 기록이 있는 아티스트는 재시도하지 않아야 한다."""
        failed_path = tmp_path / "image_failed.json"
        recent = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        failed_path.write_text(json.dumps({"1": recent}))
        monkeypatch.setattr("scheduler._IMAGE_FAILED_PATH", str(failed_path))

        with (
            patch("scheduler.get_artists_without_image", return_value=[self._ARTIST]),
            patch("scheduler.artist_image.collect_artist_image") as mock_collect,
        ):
            run_artist_image_update()

        mock_collect.assert_not_called()

    def test_retries_artist_failed_outside_retry_window(self, tmp_path, monkeypatch):
        """재시도 주기를 지난 실패 기록은 다시 시도해야 한다."""
        failed_path = tmp_path / "image_failed.json"
        old = (datetime.now() - timedelta(days=31)).strftime("%Y%m%d")
        failed_path.write_text(json.dumps({"1": old}))
        monkeypatch.setattr("scheduler._IMAGE_FAILED_PATH", str(failed_path))

        with (
            patch("scheduler.get_artists_without_image", return_value=[self._ARTIST]),
            patch(
                "scheduler.artist_image.collect_artist_image", return_value=(None, None)
            ) as mock_collect,
        ):
            run_artist_image_update()

        mock_collect.assert_called_once()

    def test_records_failure_when_image_not_found(self, tmp_path, monkeypatch):
        """이미지를 찾지 못하면 image_failed 체크포인트에 오늘 날짜로 기록해야 한다."""
        failed_path = tmp_path / "image_failed.json"
        monkeypatch.setattr("scheduler._IMAGE_FAILED_PATH", str(failed_path))

        with (
            patch("scheduler.get_artists_without_image", return_value=[self._ARTIST]),
            patch("scheduler.artist_image.collect_artist_image", return_value=(None, None)),
        ):
            run_artist_image_update()

        saved = json.loads(failed_path.read_text())
        assert saved == {"1": datetime.now().strftime("%Y%m%d")}

    def test_clears_failure_record_when_image_found(self, tmp_path, monkeypatch):
        """이미지를 새로 찾으면 기존 실패 기록을 제거해야 한다."""
        failed_path = tmp_path / "image_failed.json"
        old = (datetime.now() - timedelta(days=31)).strftime("%Y%m%d")
        failed_path.write_text(json.dumps({"1": old}))
        monkeypatch.setattr("scheduler._IMAGE_FAILED_PATH", str(failed_path))

        with (
            patch("scheduler.get_artists_without_image", return_value=[self._ARTIST]),
            patch(
                "scheduler.artist_image.collect_artist_image",
                return_value=("http://img.url", "found-id"),
            ),
            patch("scheduler.update_artist_image"),
            patch("scheduler.upsert_artist_url"),
        ):
            run_artist_image_update()

        saved = json.loads(failed_path.read_text())
        assert saved == {}


# ---------------------------------------------------------------------------
# 잡 간 체크포인트 격리
# ---------------------------------------------------------------------------
class TestJobIsolation:
    """run_missing_release_update의 progress가 run_release_update에 영향을 주지 않아야 한다."""

    _MATCHED_ARTISTS = [
        {"artist_id": 10, "spotify_url": "https://open.spotify.com/artist/sp-10"},
        {"artist_id": 20, "spotify_url": "https://open.spotify.com/artist/sp-20"},
    ]
    _MISSING_ARTISTS = [
        {"artist_id": 10, "spotify_url": "https://open.spotify.com/artist/sp-10"},
        {"artist_id": 20, "spotify_url": "https://open.spotify.com/artist/sp-20"},
    ]

    def test_missing_release_progress_does_not_skip_release_update(self, tmp_path, monkeypatch):
        """missing_release 잡이 저장한 completed_ids를 release_update 잡이 읽지 않아야 한다."""
        monkeypatch.setattr("scheduler._CHECKPOINT_DIR", str(tmp_path))
        monkeypatch.setattr("scheduler._BAN_PATH", str(tmp_path / "spotify_ban.json"))

        # missing_release 잡이 artist 10, 20 처리 후 429로 중단된 상황 시뮬레이션
        _save_progress("missing_release", {10, 20})

        # release_update 잡 실행 — missing_release progress를 읽어선 안 됨
        with (
            patch("scheduler.get_matched_artists_with_spotify", return_value=self._MATCHED_ARTISTS),
            patch("scheduler.get_spotify_album_total", return_value=None),
            patch("scheduler.get_existing_release_spotify_ids", return_value=set()),
            patch("scheduler.release.collect_releases", return_value=([], 0)) as mock_collect,
            patch("scheduler.update_spotify_album_total"),
            patch("scheduler.save_releases"),
        ):
            run_release_update()

        assert mock_collect.call_count == 2  # 두 아티스트 모두 처리되어야 함

    def test_release_update_progress_does_not_skip_missing_release(self, tmp_path, monkeypatch):
        """release_update 잡이 저장한 completed_ids를 missing_release 잡이 읽지 않아야 한다."""
        monkeypatch.setattr("scheduler._CHECKPOINT_DIR", str(tmp_path))
        monkeypatch.setattr("scheduler._BAN_PATH", str(tmp_path / "spotify_ban.json"))

        # release_update 잡이 artist 10, 20 처리 후 429로 중단된 상황 시뮬레이션
        _save_progress("release_update", {10, 20})

        # missing_release 잡 실행 — release_update progress를 읽어선 안 됨
        with (
            patch("scheduler.get_artists_without_releases", return_value=self._MISSING_ARTISTS),
            patch("scheduler.get_spotify_album_total", return_value=None),
            patch("scheduler.get_existing_release_spotify_ids", return_value=set()),
            patch("scheduler.release.collect_releases", return_value=([], 0)) as mock_collect,
            patch("scheduler.update_spotify_album_total"),
            patch("scheduler.save_releases"),
        ):
            run_missing_release_update()

        assert mock_collect.call_count == 2  # 두 아티스트 모두 처리되어야 함
