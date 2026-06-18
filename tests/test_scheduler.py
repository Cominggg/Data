"""scheduler.py 단위 테스트."""
import json
import os
from unittest.mock import patch

import pytest

from scheduler import (
    _CHECKPOINT_PATH,
    _build_scheduler,
    _clear_checkpoint,
    _is_banned,
    _load_checkpoint,
    _save_checkpoint,
    _sort_releases,
    register_artist_by_mbid,
    run_artist_image_update,
    run_initial_collect,
    run_missing_release_update,
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



class TestRunStatusUpdate:
    # ── 상태 갱신 경로 ─────────────────────────────────────────────────────────

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
            patch("scheduler.kopis.collect", return_value=[]),
            patch("scheduler.get_existing_kopis_ids", return_value=set()),
            patch("scheduler.get_all_aliases", return_value=[]),
            patch("scheduler.update_artist_is_coming"),
        ):
            run_status_update()

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
            patch("scheduler.kopis.collect", return_value=[]),
            patch("scheduler.get_existing_kopis_ids", return_value=set()),
            patch("scheduler.get_all_aliases", return_value=[]),
            patch("scheduler.update_artist_is_coming"),
        ):
            run_status_update()

        mock_update.assert_called_once_with([fetched])

    def test_skips_status_update_when_no_active_concerts(self):
        """활성 공연이 없으면 collect_by_id·update_concert_status가 호출되지 않아야 한다."""
        with (
            patch("scheduler.get_active_concerts", return_value=[]),
            patch("scheduler.kopis.collect_by_id") as mock_by_id,
            patch("scheduler.update_concert_status") as mock_update,
            patch("scheduler.kopis.collect", return_value=[]),
            patch("scheduler.get_existing_kopis_ids", return_value=set()),
            patch("scheduler.get_all_aliases", return_value=[]),
            patch("scheduler.update_artist_is_coming"),
        ):
            run_status_update()

        mock_by_id.assert_not_called()
        mock_update.assert_not_called()

    def test_skips_none_results_from_collect_by_id(self):
        """collect_by_id가 None을 반환하면 update_concert_status 호출 대상에서 제외되어야 한다."""
        active = [{"kopis_id": "PF001", "kopis_update_date": "2024-01-01"}]
        with (
            patch("scheduler.get_active_concerts", return_value=active),
            patch("scheduler.kopis.collect_by_id", return_value=None),
            patch("scheduler.update_concert_status") as mock_update,
            patch("scheduler.kopis.collect", return_value=[]),
            patch("scheduler.get_existing_kopis_ids", return_value=set()),
            patch("scheduler.get_all_aliases", return_value=[]),
            patch("scheduler.update_artist_is_coming"),
        ):
            run_status_update()

        mock_update.assert_not_called()

    # ── 신규 발견 경로 ─────────────────────────────────────────────────────────

    def test_updates_is_coming_after_status_update(self):
        """상태 갱신 후 update_artist_is_coming이 인자 없이 호출되어야 한다."""
        with (
            patch("scheduler.get_active_concerts", return_value=[]),
            patch("scheduler.kopis.collect", return_value=[]),
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
            patch("scheduler.get_active_concerts", return_value=[]),
            patch("scheduler.kopis.collect", return_value=[new_concert]),
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
            patch("scheduler.get_active_concerts", return_value=[]),
            patch("scheduler.kopis.collect", return_value=[new_concert]),
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
            patch("scheduler.get_active_concerts", return_value=[]),
            patch("scheduler.kopis.collect", return_value=[existing_concert]),
            patch("scheduler.get_existing_kopis_ids", return_value={"PF001"}),
            patch("scheduler.get_all_aliases", return_value=[]),
            patch("scheduler.has_match", return_value=True),
            patch("scheduler.save_concerts") as mock_save,
            patch("scheduler.update_artist_is_coming"),
        ):
            run_status_update()

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
    def test_registers_five_jobs(self):
        """스케줄러에 5개의 잡이 등록되어야 한다."""
        scheduler = _build_scheduler()
        assert len(scheduler.get_jobs()) == 5

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

    def test_returns_true_on_success(self):
        """모든 단계 성공 시 True를 반환해야 한다."""
        with (
            patch("scheduler.musicbrainz.collect_single_artist", return_value=self._ARTIST),
            patch("scheduler.save_artists"),
            patch("scheduler.get_artist_by_mbid", return_value=self._SAVED),
            patch("scheduler.artist_image.collect_artist_image", return_value="http://img.url"),
            patch("scheduler.update_artist_image"),
            patch("scheduler.release.collect_releases", return_value=([], 0)),
            patch("scheduler.save_releases"),
        ):
            assert register_artist_by_mbid("mbid-test") is True

    def test_returns_false_when_collect_fails(self):
        """MusicBrainz 수집 실패 시 False를 반환해야 한다."""
        with patch("scheduler.musicbrainz.collect_single_artist", return_value=None):
            assert register_artist_by_mbid("mbid-bad") is False

    def test_returns_false_when_db_lookup_fails(self):
        """DB에서 아티스트를 찾지 못하면 False를 반환해야 한다."""
        with (
            patch("scheduler.musicbrainz.collect_single_artist", return_value=self._ARTIST),
            patch("scheduler.save_artists"),
            patch("scheduler.get_artist_by_mbid", return_value=None),
        ):
            assert register_artist_by_mbid("mbid-test") is False

    def test_saves_artist_before_image_and_releases(self):
        """save_artists가 이미지·릴리즈 수집보다 먼저 호출되어야 한다."""
        call_order = []
        with (
            patch(
                "scheduler.musicbrainz.collect_single_artist", return_value=self._ARTIST
            ),
            patch("scheduler.save_artists", side_effect=lambda _: call_order.append("save")),
            patch("scheduler.get_artist_by_mbid", return_value=self._SAVED),
            patch(
                "scheduler.artist_image.collect_artist_image",
                side_effect=lambda *a, **kw: call_order.append("image") or "http://img",
            ),
            patch("scheduler.update_artist_image"),
            patch(
                "scheduler.release.collect_releases",
                side_effect=lambda _: call_order.append("releases") or ([], 0),
            ),
            patch("scheduler.save_releases"),
        ):
            register_artist_by_mbid("mbid-test")

        assert call_order[0] == "save"

    def test_skips_image_and_releases_without_spotify(self):
        """Spotify URL이 없으면 이미지·릴리즈 수집을 건너뛰어야 한다."""
        saved_no_spotify = {"id": 99, "name": "NoSpot", "spotify_url": None}
        with (
            patch("scheduler.musicbrainz.collect_single_artist", return_value=self._ARTIST),
            patch("scheduler.save_artists"),
            patch("scheduler.get_artist_by_mbid", return_value=saved_no_spotify),
            patch("scheduler.artist_image.collect_artist_image") as mock_img,
            patch("scheduler.release.collect_releases") as mock_rel,
        ):
            result = register_artist_by_mbid("mbid-test")

        assert result is True
        mock_img.assert_not_called()
        mock_rel.assert_not_called()


# ---------------------------------------------------------------------------
# 체크포인트 헬퍼
# ---------------------------------------------------------------------------
class TestCheckpoint:
    def test_load_returns_empty_set_when_no_file(self, tmp_path, monkeypatch):
        """체크포인트 파일 없으면 빈 집합 반환."""
        monkeypatch.setattr("scheduler._CHECKPOINT_PATH", str(tmp_path / "release_sync.json"))
        assert _load_checkpoint() == set()

    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        """저장 후 로드하면 같은 집합이 복원되어야 한다."""
        path = str(tmp_path / "release_sync.json")
        monkeypatch.setattr("scheduler._CHECKPOINT_PATH", path)
        _save_checkpoint({1, 2, 3})
        assert _load_checkpoint() == {1, 2, 3}

    def test_clear_removes_file(self, tmp_path, monkeypatch):
        """_clear_checkpoint 후 파일이 삭제되어야 한다."""
        path = str(tmp_path / "release_sync.json")
        monkeypatch.setattr("scheduler._CHECKPOINT_PATH", path)
        _save_checkpoint({10})
        assert os.path.exists(path)
        _clear_checkpoint()
        assert not os.path.exists(path)

    def test_load_returns_empty_on_corrupt_file(self, tmp_path, monkeypatch):
        """파일이 손상됐을 때 빈 집합을 반환해야 한다."""
        path = str(tmp_path / "release_sync.json")
        monkeypatch.setattr("scheduler._CHECKPOINT_PATH", path)
        with open(path, "w") as f:
            f.write("not-json{{{")
        assert _load_checkpoint() == set()

    def test_load_handles_legacy_flat_list_format(self, tmp_path, monkeypatch):
        """이전 flat list 형식 파일도 정상 로드되어야 한다."""
        path = str(tmp_path / "release_sync.json")
        monkeypatch.setattr("scheduler._CHECKPOINT_PATH", path)
        with open(path, "w") as f:
            json.dump([10, 20, 30], f)
        assert _load_checkpoint() == {10, 20, 30}

    def test_save_includes_banned_until(self, tmp_path, monkeypatch):
        """저장된 파일에 banned_until 필드가 있어야 한다."""
        path = str(tmp_path / "release_sync.json")
        monkeypatch.setattr("scheduler._CHECKPOINT_PATH", path)
        _save_checkpoint({5, 6})
        data = json.load(open(path))
        assert "banned_until" in data
        assert set(data["completed_artist_ids"]) == {5, 6}


# ---------------------------------------------------------------------------
# _is_banned
# ---------------------------------------------------------------------------
class TestIsBanned:
    def test_returns_false_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("scheduler._CHECKPOINT_PATH", str(tmp_path / "release_sync.json"))
        assert _is_banned() is False

    def test_returns_true_within_ban_period(self, tmp_path, monkeypatch):
        from datetime import datetime, timedelta
        path = str(tmp_path / "release_sync.json")
        monkeypatch.setattr("scheduler._CHECKPOINT_PATH", path)
        future = (datetime.now() + timedelta(hours=20)).isoformat(timespec="seconds")
        with open(path, "w") as f:
            json.dump({"banned_until": future, "completed_artist_ids": []}, f)
        assert _is_banned() is True

    def test_returns_false_after_ban_expired(self, tmp_path, monkeypatch):
        from datetime import datetime, timedelta
        path = str(tmp_path / "release_sync.json")
        monkeypatch.setattr("scheduler._CHECKPOINT_PATH", path)
        past = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
        with open(path, "w") as f:
            json.dump({"banned_until": past, "completed_artist_ids": []}, f)
        assert _is_banned() is False

    def test_returns_false_for_legacy_flat_list(self, tmp_path, monkeypatch):
        path = str(tmp_path / "release_sync.json")
        monkeypatch.setattr("scheduler._CHECKPOINT_PATH", path)
        with open(path, "w") as f:
            json.dump([1, 2, 3], f)
        assert _is_banned() is False


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
        from datetime import datetime, timedelta
        path = str(tmp_path / "release_sync.json")
        monkeypatch.setattr("scheduler._CHECKPOINT_PATH", path)
        # 밴은 만료, 완료된 artist_id=1은 체크포인트에 잔류하는 시나리오
        past = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
        with open(path, "w") as f:
            json.dump({"banned_until": past, "completed_artist_ids": [1]}, f)
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

    def test_saves_checkpoint_on_429_and_clears_on_success(self, tmp_path, monkeypatch):
        """429 발생 시 체크포인트 저장, 정상 완료 시 체크포인트 삭제."""
        path = str(tmp_path / "release_sync.json")
        monkeypatch.setattr("scheduler._CHECKPOINT_PATH", path)
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

        assert os.path.exists(path)
        data = json.load(open(path))
        completed = set(data["completed_artist_ids"])
        assert "banned_until" in data
        assert 1 in completed  # artist_id=1 완료 후 저장
        assert 2 not in completed

    def test_clears_checkpoint_on_normal_completion(self, tmp_path, monkeypatch):
        """정상 완료 시 체크포인트 파일을 삭제해야 한다."""
        from datetime import datetime, timedelta
        path = str(tmp_path / "release_sync.json")
        monkeypatch.setattr("scheduler._CHECKPOINT_PATH", path)
        # 밴 만료 상태의 잔여 체크포인트
        past = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
        with open(path, "w") as f:
            json.dump({"banned_until": past, "completed_artist_ids": [99]}, f)

        with (
            patch("scheduler.get_matched_artists_with_spotify", return_value=self._ARTISTS),
            patch("scheduler.get_spotify_album_total", return_value=None),
            patch("scheduler.get_existing_release_spotify_ids", return_value=set()),
            patch("scheduler.release.collect_releases", return_value=([], 0)),
            patch("scheduler.update_spotify_album_total"),
            patch("scheduler.save_releases"),
        ):
            run_release_update()

        assert not os.path.exists(path)

    def test_updates_spotify_album_total_when_nonzero(self, tmp_path, monkeypatch):
        """spotify_total > 0이면 update_spotify_album_total이 호출되어야 한다."""
        monkeypatch.setattr(
            "scheduler._CHECKPOINT_PATH", str(tmp_path / "release_sync.json")
        )
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
        monkeypatch.setattr(
            "scheduler._CHECKPOINT_PATH", str(tmp_path / "release_sync.json")
        )
        artists = [{"artist_id": 7, "spotify_url": "https://open.spotify.com/artist/sp-7"}]
        with (
            patch("scheduler.get_matched_artists_with_spotify", return_value=artists),
            patch("scheduler.get_spotify_album_total", return_value=5),
            patch("scheduler.get_existing_release_spotify_ids", return_value=set()),
            patch("scheduler.release.collect_releases", return_value=([], 5)),  # total 동일
            patch("scheduler.update_spotify_album_total"),
            patch("scheduler.save_releases") as mock_save,
        ):
            run_release_update()

        mock_save.assert_not_called()

    def test_skips_all_when_banned(self, tmp_path, monkeypatch):
        """banned_until이 유효하면 collect_releases를 호출하지 않아야 한다."""
        from datetime import datetime, timedelta
        path = str(tmp_path / "release_sync.json")
        monkeypatch.setattr("scheduler._CHECKPOINT_PATH", path)
        future = (datetime.now() + timedelta(hours=20)).isoformat(timespec="seconds")
        with open(path, "w") as f:
            json.dump({"banned_until": future, "completed_artist_ids": []}, f)
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
        path = str(tmp_path / "release_sync.json")
        monkeypatch.setattr("scheduler._CHECKPOINT_PATH", path)
        future = (datetime.now() + timedelta(hours=20)).isoformat(timespec="seconds")
        with open(path, "w") as f:
            json.dump({"banned_until": future, "completed_artist_ids": []}, f)
        with patch("scheduler.artist_image.collect_artist_image") as mock_collect:
            run_artist_image_update()
        mock_collect.assert_not_called()
