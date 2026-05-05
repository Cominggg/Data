from unittest.mock import MagicMock, patch

import pytest
import requests

from collectors.release import (
    _fetch_cover_art_url,
    _fetch_tracks,
    _get_representative_release_mbid,
    _parse_label,
    _parse_release_date,
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

    def test_skips_track_with_missing_recording_id(self):
        """recording id가 없는 트랙은 track.mbid UNIQUE 제약 위반 방지를 위해 제외해야 한다."""
        release_data = {
            "media": [
                {"tracks": [{"title": "T", "position": 1, "length": 100, "recording": {}}]}
            ]
        }
        assert _parse_tracks(release_data) == []


class TestParseReleaseDate:
    def test_full_date_unchanged(self):
        assert _parse_release_date("2020-01-15") == "2020-01-15"

    def test_year_month_padded_to_first_day(self):
        assert _parse_release_date("2020-01") == "2020-01-01"

    def test_year_only_padded_to_january_first(self):
        assert _parse_release_date("2020") == "2020-01-01"

    def test_none_returns_none(self):
        assert _parse_release_date(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_release_date("") is None

    def test_unknown_format_returns_none(self):
        assert _parse_release_date("January 2020") is None


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
    def test_retries_on_network_error_then_succeeds(self, mock_sleep, mock_get):
        """네트워크 오류 후 재시도에서 성공 시 Location 반환해야 한다."""
        fail_response = MagicMock()
        fail_response.status_code = 503
        fail_response.raise_for_status.side_effect = requests.RequestException("503")

        ok_response = MagicMock()
        ok_response.status_code = 307
        ok_response.headers = {"Location": "https://archive.org/image.jpg"}

        mock_get.side_effect = [fail_response, ok_response]

        result = _fetch_cover_art_url("some-mbid")

        assert result == "https://archive.org/image.jpg"
        assert mock_get.call_count == 2

    @patch("collectors.release.requests.get")
    @patch("collectors.release.time.sleep")
    def test_raises_after_three_retries(self, mock_sleep, mock_get):
        """3회 재시도 모두 실패하면 예외를 전파해야 한다."""
        fail_response = MagicMock()
        fail_response.status_code = 503
        fail_response.raise_for_status.side_effect = requests.RequestException("503")
        mock_get.return_value = fail_response

        with pytest.raises(requests.RequestException):
            _fetch_cover_art_url("some-mbid")

        assert mock_get.call_count == 3

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
    def test_collect_includes_label_field(self, mock_fetch_rg, mock_fetch_tracks, mock_cover):
        """collect_releases() 반환값에 label 필드가 포함되어야 한다."""
        mock_fetch_rg.return_value = {
            "release-groups": [
                {
                    "id": "rg-1",
                    "title": "Album A",
                    "primary-type": "Album",
                    "first-release-date": "2020-01-01",
                    "releases": [{"id": "rel-1", "date": "2020-01-01"}],
                }
            ],
            "release-group-count": 1,
        }
        mock_fetch_tracks.return_value = {
            "media": [],
            "label-info": [{"label": {"name": "SME Records"}}],
        }
        mock_cover.return_value = None

        result = collect_releases("artist-mbid")

        assert result[0]["label"] == "SME Records"

    @patch("collectors.release._fetch_cover_art_url")
    @patch("collectors.release._fetch_tracks")
    @patch("collectors.release._fetch_release_groups")
    def test_label_is_none_when_label_info_absent(self, mock_fetch_rg, mock_fetch_tracks, mock_cover):
        """label-info가 없으면 label이 None이어야 한다."""
        mock_fetch_rg.return_value = {
            "release-groups": [
                {
                    "id": "rg-1",
                    "title": "Album A",
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

        assert result[0]["label"] is None

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


class TestParseLabel:
    def test_returns_label_name(self):
        release_data = {
            "label-info": [{"label": {"name": "SME Records"}}]
        }
        assert _parse_label(release_data) == "SME Records"

    def test_returns_none_when_label_info_empty(self):
        assert _parse_label({"label-info": []}) is None

    def test_returns_none_when_label_info_absent(self):
        assert _parse_label({}) is None

    def test_returns_none_when_label_key_missing(self):
        release_data = {"label-info": [{}]}
        assert _parse_label(release_data) is None

    def test_returns_none_when_label_name_missing(self):
        release_data = {"label-info": [{"label": {}}]}
        assert _parse_label(release_data) is None

    def test_uses_first_label_info_entry(self):
        release_data = {
            "label-info": [
                {"label": {"name": "First Label"}},
                {"label": {"name": "Second Label"}},
            ]
        }
        assert _parse_label(release_data) == "First Label"


class TestFetchTracks:
    @patch("collectors.release._get")
    def test_requests_recordings_and_labels_for_release(self, mock_get):
        mock_get.return_value = {"media": []}

        result = _fetch_tracks("release-mbid-1")

        mock_get.assert_called_once_with(
            "/release/release-mbid-1", {"inc": "recordings+labels", "fmt": "json"}
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

    def test_insert_sql_includes_label_column(self):
        """release_group INSERT SQL에 label 컬럼이 포함되어야 한다."""
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
                "label": "SME Records",
                "tracks": [],
            }
        ]

        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            save_releases(releases)

        insert_sql = next(
            str(c.args[0])
            for c in mock_session.execute.call_args_list
            if "INSERT INTO release_group" in str(c.args[0])
        )
        assert "label" in insert_sql

    def test_label_param_passed_to_insert(self):
        """save_releases() INSERT 파라미터에 label 값이 전달되어야 한다."""
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
                "label": "SME Records",
                "tracks": [],
            }
        ]

        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            save_releases(releases)

        insert_call = next(
            c for c in mock_session.execute.call_args_list
            if "INSERT INTO release_group" in str(c.args[0])
        )
        assert insert_call.args[1]["label"] == "SME Records"

    def test_label_none_when_key_absent(self):
        """release dict에 label 키가 없어도 INSERT가 정상 실행되어야 한다."""
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

        insert_call = next(
            c for c in mock_session.execute.call_args_list
            if "INSERT INTO release_group" in str(c.args[0])
        )
        assert insert_call.args[1]["label"] is None

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
