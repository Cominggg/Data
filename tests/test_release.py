from unittest.mock import MagicMock, patch

import pytest
import requests

from collectors.release import (
    _fetch_cover_art_url,
    _fetch_tracks,
    _get_representative_release_mbid,
    _parse_tracks,
    collect_releases,
)
from db.repository import save_releases


class TestParseTracks:
    def test_extracts_tracks_from_media(self):
        release_data = {
            "media": [
                {
                    "tracks": [
                        {
                            "title": "Track 1",
                            "position": 1,
                            "length": 210000,
                            "recording": {"id": "rec-mbid-1"},
                        }
                    ]
                }
            ]
        }
        result = _parse_tracks(release_data)
        assert len(result) == 1
        assert result[0] == {
            "mbid": "rec-mbid-1",
            "title": "Track 1",
            "position": 1,
            "length_ms": 210000,
        }

    def test_aggregates_tracks_across_multiple_media(self):
        release_data = {
            "media": [
                {"tracks": [{"title": "A", "position": 1, "length": 100, "recording": {"id": "r1"}}]},
                {"tracks": [{"title": "B", "position": 1, "length": 200, "recording": {"id": "r2"}}]},
            ]
        }
        assert len(_parse_tracks(release_data)) == 2

    def test_returns_empty_for_no_media(self):
        assert _parse_tracks({}) == []

    def test_handles_missing_recording_id(self):
        release_data = {
            "media": [
                {"tracks": [{"title": "T", "position": 1, "length": 100, "recording": {}}]}
            ]
        }
        assert _parse_tracks(release_data)[0]["mbid"] is None


class TestGetRepresentativeReleaseMbid:
    def test_returns_none_when_no_releases(self):
        assert _get_representative_release_mbid({"releases": []}) is None

    def test_returns_none_when_releases_key_absent(self):
        assert _get_representative_release_mbid({}) is None

    def test_picks_release_matching_first_release_date(self):
        rg = {
            "first-release-date": "2020-01-15",
            "releases": [
                {"id": "r1", "date": "2020-06-01"},
                {"id": "r2", "date": "2020-01-15"},
            ],
        }
        assert _get_representative_release_mbid(rg) == "r2"

    def test_falls_back_to_first_release_when_no_date_match(self):
        rg = {
            "first-release-date": "2020-01-15",
            "releases": [
                {"id": "r1", "date": "2021-01-01"},
                {"id": "r2", "date": "2022-01-01"},
            ],
        }
        assert _get_representative_release_mbid(rg) == "r1"


class TestFetchCoverArtUrl:
    @patch("collectors.release.requests.get")
    @patch("collectors.release.time.sleep")
    def test_returns_location_on_redirect(self, mock_sleep, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 307
        mock_response.headers = {"Location": "https://archive.org/image.jpg"}
        mock_get.return_value = mock_response

        result = _fetch_cover_art_url("some-mbid")

        assert result == "https://archive.org/image.jpg"

    @patch("collectors.release.requests.get")
    @patch("collectors.release.time.sleep")
    def test_returns_none_on_404(self, mock_sleep, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        result = _fetch_cover_art_url("missing-mbid")

        assert result is None

    @patch("collectors.release.requests.get")
    @patch("collectors.release.time.sleep")
    def test_raises_on_unexpected_status(self, mock_sleep, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.HTTPError("500")
        mock_get.return_value = mock_response

        with pytest.raises(requests.HTTPError):
            _fetch_cover_art_url("err-mbid")

    @patch("collectors.release.requests.get")
    @patch("collectors.release.time.sleep")
    def test_sleep_applied_before_request(self, mock_sleep, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        _fetch_cover_art_url("any-mbid")

        mock_sleep.assert_called_with(1.1)


class TestReleaseCollect:
    @patch("collectors.release._fetch_cover_art_url")
    @patch("collectors.release._fetch_tracks")
    @patch("collectors.release._fetch_release_groups")
    def test_collect_returns_list(self, mock_fetch_rg, mock_fetch_tracks, mock_cover):
        """collect() 호출 결과가 리스트여야 한다."""
        mock_fetch_rg.return_value = {
            "release-groups": [
                {
                    "id": "rg-mbid-1",
                    "title": "Album A",
                    "primary-type": "Album",
                    "first-release-date": "2020-01-01",
                    "releases": [{"id": "rel-1", "date": "2020-01-01"}],
                }
            ],
            "release-group-count": 1,
        }
        mock_fetch_tracks.return_value = {"media": []}
        mock_cover.return_value = "https://example.com/cover.jpg"

        result = collect_releases("artist-mbid")

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["release_group_mbid"] == "rg-mbid-1"

    def test_inserts_only_new_releases(self):
        """first-release-date 기준으로 DB에 없는 항목만 INSERT되어야 한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = (1,)

        releases = [
            {
                "release_group_mbid": "rg-1",
                "artist_mbid": "artist-1",
                "title": "Album",
                "type": "Album",
                "first_release_date": "2020-01-01",
                "cover_url": None,
                "tracks": [],
            }
        ]

        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            save_releases(releases)

        insert_sqls = [
            str(c.args[0])
            for c in mock_session.execute.call_args_list
            if "INSERT" in str(c.args[0])
        ]
        assert len(insert_sqls) >= 1
        assert all("ON CONFLICT" in sql for sql in insert_sqls)

    @patch("collectors.release._fetch_cover_art_url")
    @patch("collectors.release._fetch_tracks")
    @patch("collectors.release._fetch_release_groups")
    def test_cover_art_null_on_404(self, mock_fetch_rg, mock_fetch_tracks, mock_cover):
        """Cover Art Archive 404 응답 시 커버 이미지를 null로 허용해야 한다."""
        mock_fetch_rg.return_value = {
            "release-groups": [
                {
                    "id": "rg-no-cover",
                    "title": "No Cover Album",
                    "primary-type": "Album",
                    "first-release-date": "2020-01-01",
                    "releases": [{"id": "rel-1", "date": "2020-01-01"}],
                }
            ],
            "release-group-count": 1,
        }
        mock_fetch_tracks.return_value = {"media": []}
        mock_cover.return_value = None

        result = collect_releases("artist-mbid")

        assert result[0]["cover_url"] is None

    @patch("collectors.release.time.sleep")
    @patch("collectors.release.requests.get")
    def test_rate_limit_sleep_applied(self, mock_get, mock_sleep):
        """MusicBrainz 요청마다 1.1초 sleep이 적용되어야 한다."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"release-groups": [], "release-group-count": 0}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        collect_releases("artist-mbid")

        mock_sleep.assert_called_with(1.1)

    @patch("collectors.release._fetch_cover_art_url")
    @patch("collectors.release._fetch_tracks")
    @patch("collectors.release._fetch_release_groups")
    def test_continues_when_track_fetch_fails(self, mock_fetch_rg, mock_fetch_tracks, mock_cover):
        """트랙 수집 HTTP 에러 시 빈 트랙으로 결과에 포함되어야 한다."""
        mock_fetch_rg.return_value = {
            "release-groups": [
                {
                    "id": "rg-1",
                    "title": "Album",
                    "primary-type": "Album",
                    "first-release-date": "2020-01-01",
                    "releases": [{"id": "rel-1", "date": "2020-01-01"}],
                }
            ],
            "release-group-count": 1,
        }
        mock_fetch_tracks.side_effect = requests.HTTPError("404")
        mock_cover.return_value = None

        result = collect_releases("artist-mbid")

        assert result[0]["tracks"] == []

    @patch("collectors.release._fetch_cover_art_url")
    @patch("collectors.release._fetch_tracks")
    @patch("collectors.release._fetch_release_groups")
    def test_continues_when_cover_art_fetch_fails(self, mock_fetch_rg, mock_fetch_tracks, mock_cover):
        """커버 아트 수집 HTTP 에러 시 cover_url이 None으로 결과에 포함되어야 한다."""
        mock_fetch_rg.return_value = {
            "release-groups": [
                {
                    "id": "rg-1",
                    "title": "Album",
                    "primary-type": "Album",
                    "first-release-date": "2020-01-01",
                    "releases": [{"id": "rel-1", "date": "2020-01-01"}],
                }
            ],
            "release-group-count": 1,
        }
        mock_fetch_tracks.return_value = {"media": []}
        mock_cover.side_effect = requests.HTTPError("500")

        result = collect_releases("artist-mbid")

        assert result[0]["cover_url"] is None


class TestFetchTracks:
    @patch("collectors.release._get")
    def test_requests_recordings_for_release(self, mock_get):
        mock_get.return_value = {"media": []}

        result = _fetch_tracks("release-mbid-1")

        mock_get.assert_called_once_with(
            "/release/release-mbid-1", {"inc": "recordings", "fmt": "json"}
        )
        assert result == {"media": []}


class TestSaveReleases:
    def test_skips_release_when_artist_not_found(self):
        """artist 미존재 시 INSERT 없이 건너뛰어야 한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = None

        releases = [
            {
                "release_group_mbid": "rg-1",
                "artist_mbid": "nonexistent-artist",
                "title": "Album",
                "type": "Album",
                "first_release_date": "2020-01-01",
                "cover_url": None,
                "tracks": [],
            }
        ]

        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            save_releases(releases)

        insert_calls = [
            c for c in mock_session.execute.call_args_list
            if "INSERT" in str(c.args[0])
        ]
        assert len(insert_calls) == 0

    def test_saves_tracks_when_present(self):
        """트랙이 있는 릴리즈는 track 테이블에도 INSERT되어야 한다."""
        mock_session = MagicMock()
        # SELECT artist → (1,), INSERT release_group, SELECT release_group → (2,), INSERT track
        mock_session.execute.return_value.fetchone.side_effect = [(1,), (2,)]

        releases = [
            {
                "release_group_mbid": "rg-1",
                "artist_mbid": "artist-1",
                "title": "Album",
                "type": "Album",
                "first_release_date": "2020-01-01",
                "cover_url": None,
                "tracks": [
                    {"mbid": "track-1", "title": "Song A", "position": 1, "length_ms": 180000}
                ],
            }
        ]

        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            save_releases(releases)

        track_inserts = [
            c for c in mock_session.execute.call_args_list
            if "INSERT INTO track" in str(c.args[0])
        ]
        assert len(track_inserts) == 1
