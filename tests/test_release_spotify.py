"""collectors/release.py (Spotify) + db/repository.save_releases 단위 테스트."""
from unittest.mock import MagicMock, patch

import requests
from sqlalchemy.exc import SQLAlchemyError

from collectors.release import (
    _fetch_album_ids,
    _fetch_albums_individual,
    _parse_release_date,
    _parse_tracks,
    collect_releases,
)
from db.repository import save_releases


# ---------------------------------------------------------------------------
# _parse_release_date
# ---------------------------------------------------------------------------
class TestParseReleaseDate:
    def test_full_date_accepted(self):
        assert _parse_release_date("2020-01-15") == "2020-01-15"

    def test_year_month_returns_none(self):
        assert _parse_release_date("2020-01") is None

    def test_year_only_returns_none(self):
        assert _parse_release_date("2020") is None

    def test_none_returns_none(self):
        assert _parse_release_date(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_release_date("") is None

    def test_unknown_format_returns_none(self):
        assert _parse_release_date("January 2020") is None


# ---------------------------------------------------------------------------
# _parse_tracks
# ---------------------------------------------------------------------------
class TestParseTracks:
    def test_extracts_fields_from_spotify_track_items(self):
        items = [
            {
                "id": "spotify-track-1",
                "name": "Track A",
                "track_number": 1,
                "disc_number": 1,
                "duration_ms": 210000,
                "explicit": False,
            }
        ]
        result = _parse_tracks(items)
        assert len(result) == 1
        assert result[0] == {
            "spotify_id": "spotify-track-1",
            "title": "Track A",
            "position": 1,
            "disc_number": 1,
            "length_ms": 210000,
            "explicit": False,
        }

    def test_skips_item_without_spotify_id(self):
        items = [{"name": "No ID Track", "track_number": 1, "disc_number": 1}]
        assert _parse_tracks(items) == []

    def test_returns_empty_for_empty_list(self):
        assert _parse_tracks([]) == []

    def test_explicit_defaults_to_false_when_absent(self):
        items = [{"id": "t1", "name": "T", "track_number": 1, "disc_number": 1}]
        result = _parse_tracks(items)
        assert result[0]["explicit"] is False

    def test_aggregates_multiple_tracks(self):
        items = [
            {"id": f"t{i}", "name": f"T{i}", "track_number": i, "disc_number": 1}
            for i in range(1, 4)
        ]
        assert len(_parse_tracks(items)) == 3


# ---------------------------------------------------------------------------
# _fetch_album_ids
# ---------------------------------------------------------------------------
class TestFetchAlbumIds:
    def _make_page(self, ids, total, offset=0):
        return {
            "items": [{"id": aid} for aid in ids],
            "total": total,
            "offset": offset,
        }

    @patch("collectors.release.spotify_get")
    def test_single_page_returns_all_ids(self, mock_get):
        mock_get.return_value = self._make_page(["a1", "a2"], total=2)
        result = _fetch_album_ids("artist-001")
        assert result == ["a1", "a2"]

    @patch("collectors.release.spotify_get")
    def test_paginates_until_total_reached(self, mock_get):
        page1 = self._make_page(["a1", "a2"], total=3)
        page2 = self._make_page(["a3"], total=3)
        mock_get.side_effect = [page1, page2]

        result = _fetch_album_ids("artist-001")

        assert result == ["a1", "a2", "a3"]
        assert mock_get.call_count == 2

    @patch("collectors.release.spotify_get")
    def test_returns_partial_on_network_error(self, mock_get):
        page1 = self._make_page(["a1"], total=3)
        mock_get.side_effect = [page1, requests.ConnectionError("timeout")]

        result = _fetch_album_ids("artist-001")

        assert result == ["a1"]

    @patch("collectors.release.spotify_get")
    def test_empty_page_stops_loop(self, mock_get):
        mock_get.return_value = {"items": [], "total": 0}
        assert _fetch_album_ids("artist-001") == []


# ---------------------------------------------------------------------------
# _fetch_albums_individual
# ---------------------------------------------------------------------------
class TestFetchAlbumsIndividual:
    @patch("collectors.release.spotify_get")
    def test_single_id_makes_one_call(self, mock_get):
        mock_get.return_value = {"id": "a1"}

        result = _fetch_albums_individual(["a1"])

        mock_get.assert_called_once_with("/albums/a1", {"market": "JP"})
        assert len(result) == 1

    @patch("collectors.release.spotify_get")
    def test_multiple_ids_make_individual_calls(self, mock_get):
        mock_get.side_effect = [{"id": "a1"}, {"id": "a2"}, {"id": "a3"}]

        result = _fetch_albums_individual(["a1", "a2", "a3"])

        assert mock_get.call_count == 3
        assert len(result) == 3

    @patch("collectors.release.spotify_get")
    def test_market_jp_passed_in_each_call(self, mock_get):
        mock_get.side_effect = [{"id": "a1"}, {"id": "a2"}]

        _fetch_albums_individual(["a1", "a2"])

        for call_args in mock_get.call_args_list:
            assert call_args[0][1] == {"market": "JP"}

    @patch("collectors.release.spotify_get")
    def test_skips_failed_and_continues(self, mock_get):
        mock_get.side_effect = [requests.ConnectionError("fail"), {"id": "a2"}]

        result = _fetch_albums_individual(["a1", "a2"])

        assert len(result) == 1
        assert result[0]["id"] == "a2"

    @patch("collectors.release.spotify_get")
    def test_returns_empty_for_empty_list(self, mock_get):
        result = _fetch_albums_individual([])

        mock_get.assert_not_called()
        assert result == []


# ---------------------------------------------------------------------------
# collect_releases
# ---------------------------------------------------------------------------
class TestCollectReleases:
    def _make_album(self, album_id, album_type="album", tracks=None):
        return {
            "id": album_id,
            "name": f"Album {album_id}",
            "album_type": album_type,
            "release_date": "2023-11-15",
            "images": [{"url": f"https://i.scdn.co/{album_id}.jpg"}],
            "label": "Test Label",
            "total_tracks": len(tracks or []),
            "tracks": {"items": tracks or [], "next": None},
        }

    @patch("collectors.release._fetch_albums_individual")
    @patch("collectors.release._fetch_album_ids")
    def test_returns_correct_structure(self, mock_ids, mock_individual):
        track_item = {
            "id": "t1", "name": "Song A", "track_number": 1,
            "disc_number": 1, "duration_ms": 200000, "explicit": False,
        }
        mock_ids.return_value = ["alb1"]
        mock_individual.return_value = [self._make_album("alb1", tracks=[track_item])]

        result = collect_releases("artist-spotify-id")

        assert len(result) == 1
        r = result[0]
        assert r["spotify_id"] == "alb1"
        assert r["type"] == "Album"
        assert r["first_release_date"] == "2023-11-15"
        assert r["cover_url"] == "https://i.scdn.co/alb1.jpg"
        assert r["label"] == "Test Label"
        assert r["total_tracks"] == 1
        assert len(r["tracks"]) == 1

    @patch("collectors.release._fetch_albums_individual")
    @patch("collectors.release._fetch_album_ids")
    def test_compilation_is_excluded(self, mock_ids, mock_individual):
        mock_ids.return_value = ["c1", "a1"]
        mock_individual.return_value = [
            self._make_album("c1", album_type="compilation"),
            self._make_album("a1", album_type="album"),
        ]

        result = collect_releases("artist-spotify-id")

        assert len(result) == 1
        assert result[0]["spotify_id"] == "a1"

    @patch("collectors.release._fetch_albums_individual")
    @patch("collectors.release._fetch_album_ids")
    def test_single_type_mapped_correctly(self, mock_ids, mock_individual):
        mock_ids.return_value = ["s1"]
        mock_individual.return_value = [self._make_album("s1", album_type="single")]

        result = collect_releases("artist-spotify-id")

        assert result[0]["type"] == "Single"

    @patch("collectors.release._fetch_album_ids")
    def test_returns_empty_when_no_albums(self, mock_ids):
        mock_ids.return_value = []
        assert collect_releases("artist-spotify-id") == []

    @patch("collectors.release._fetch_albums_individual")
    @patch("collectors.release._fetch_album_ids")
    def test_cover_url_none_when_images_empty(self, mock_ids, mock_individual):
        album = self._make_album("a1")
        album["images"] = []
        mock_ids.return_value = ["a1"]
        mock_individual.return_value = [album]

        result = collect_releases("artist-spotify-id")

        assert result[0]["cover_url"] is None

    @patch("collectors.release._fetch_albums_individual")
    @patch("collectors.release._fetch_album_ids")
    def test_partial_release_date_stored_as_none(self, mock_ids, mock_individual):
        album = self._make_album("a1")
        album["release_date"] = "2023-11"
        mock_ids.return_value = ["a1"]
        mock_individual.return_value = [album]

        result = collect_releases("artist-spotify-id")

        assert result[0]["first_release_date"] is None

    @patch("collectors.release._fetch_albums_individual")
    @patch("collectors.release._fetch_album_ids")
    def test_warns_when_tracks_exceed_50(self, mock_ids, mock_individual):
        album = self._make_album("a1")
        album["tracks"]["next"] = "https://api.spotify.com/v1/albums/a1/tracks?offset=50"
        mock_ids.return_value = ["a1"]
        mock_individual.return_value = [album]

        import logging
        with patch.object(logging.getLogger("collectors.release"), "warning") as mock_warn:
            collect_releases("artist-spotify-id")
            mock_warn.assert_called_once()

    @patch("collectors.release._fetch_albums_individual")
    @patch("collectors.release._fetch_album_ids")
    def test_none_album_in_batch_is_skipped(self, mock_ids, mock_individual):
        mock_ids.return_value = ["a1", "a2"]
        mock_individual.return_value = [None, self._make_album("a2")]

        result = collect_releases("artist-spotify-id")

        assert len(result) == 1


# ---------------------------------------------------------------------------
# save_releases
# ---------------------------------------------------------------------------
class TestSaveReleases:
    def _make_release(self, spotify_id="rg-1", tracks=None):
        return {
            "spotify_id": spotify_id,
            "title": "Album",
            "type": "Album",
            "first_release_date": "2023-01-01",
            "cover_url": "https://cover.jpg",
            "label": "Test Label",
            "total_tracks": 1,
            "tracks": tracks or [],
        }

    def _patch_session(self, session):
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=session)
        ctx.__exit__ = MagicMock(return_value=False)
        return ctx

    def test_insert_sql_uses_spotify_id_conflict_key(self):
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = (1,)

        with patch("db.repository.get_session", return_value=self._patch_session(mock_session)):
            save_releases(42, [self._make_release()])

        rg_insert = next(
            str(c.args[0])
            for c in mock_session.execute.call_args_list
            if "INSERT INTO release_group" in str(c.args[0])
        )
        assert "ON CONFLICT (spotify_id)" in rg_insert

    def test_artist_id_bound_correctly(self):
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = (1,)

        with patch("db.repository.get_session", return_value=self._patch_session(mock_session)):
            save_releases(99, [self._make_release()])

        rg_call = next(
            c for c in mock_session.execute.call_args_list
            if "INSERT INTO release_group" in str(c.args[0])
        )
        assert rg_call.args[1]["artist_id"] == 99

    def test_saves_tracks_with_new_fields(self):
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = (1,)

        track = {
            "spotify_id": "t1",
            "title": "Song A",
            "position": 1,
            "disc_number": 1,
            "length_ms": 200000,
            "explicit": True,
        }
        with patch("db.repository.get_session", return_value=self._patch_session(mock_session)):
            save_releases(1, [self._make_release(tracks=[track])])

        track_call = next(
            c for c in mock_session.execute.call_args_list
            if "INSERT INTO track" in str(c.args[0])
        )
        params = track_call.args[1]
        assert params["spotify_id"] == "t1"
        assert params["disc_number"] == 1
        assert params["explicit"] is True

    def test_track_insert_uses_spotify_id_conflict_key(self):
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = (1,)

        track = {
            "spotify_id": "t1", "title": "T", "position": 1,
            "disc_number": 1, "length_ms": None, "explicit": False,
        }
        with patch("db.repository.get_session", return_value=self._patch_session(mock_session)):
            save_releases(1, [self._make_release(tracks=[track])])

        track_sql = next(
            str(c.args[0])
            for c in mock_session.execute.call_args_list
            if "INSERT INTO track" in str(c.args[0])
        )
        assert "ON CONFLICT (spotify_id)" in track_sql

    def test_one_failure_does_not_affect_others(self):
        ok_session = MagicMock()
        ok_session.execute.return_value.fetchone.return_value = (1,)

        fail_session = MagicMock()
        fail_session.execute.side_effect = SQLAlchemyError("duplicate key")

        sessions = [ok_session, fail_session, ok_session]
        idx = {"n": -1}

        def make_ctx():
            idx["n"] += 1
            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=sessions[idx["n"]])
            ctx.__exit__ = MagicMock(return_value=False)
            return ctx

        releases = [
            self._make_release("rg-ok"),
            self._make_release("rg-fail"),
        ]

        with patch("db.repository.get_session", side_effect=make_ctx):
            save_releases(1, releases)

        ok_inserts = [
            c for c in ok_session.execute.call_args_list
            if "INSERT INTO release_group" in str(c.args[0])
        ]
        assert len(ok_inserts) >= 1

    def test_total_tracks_bound_in_insert(self):
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = (1,)

        release = self._make_release()
        release["total_tracks"] = 12

        with patch("db.repository.get_session", return_value=self._patch_session(mock_session)):
            save_releases(1, [release])

        rg_call = next(
            c for c in mock_session.execute.call_args_list
            if "INSERT INTO release_group" in str(c.args[0])
        )
        assert rg_call.args[1]["total_tracks"] == 12
