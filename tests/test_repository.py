from unittest.mock import MagicMock, call, patch

from db.repository import (
    save_artists,
    save_concert_artists,
    save_to_review_queue,
    update_artist_is_coming,
)


class TestSaveArtists:
    def _run(self, artists, mock_session):
        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            save_artists(artists)

    def _make_session_mock(self, artist_id=1):
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = (artist_id,)
        return mock_session

    def test_inserts_into_artist_table(self):
        """아티스트 정보가 artist 테이블에 INSERT되어야 한다."""
        mock_session = self._make_session_mock()
        self._run(
            [{"mbid": "mbid-1", "name": "Artist A", "sort_name": "A, Artist", "debut_date": "2010-01-01", "aliases": [], "url_rels": []}],
            mock_session,
        )

        first_sql = str(mock_session.execute.call_args_list[0].args[0])
        assert "INSERT INTO artist" in first_sql

    def test_on_conflict_mbid_do_nothing(self):
        """중복 mbid 시 ON CONFLICT DO NOTHING이 포함되어야 한다."""
        mock_session = self._make_session_mock()
        self._run(
            [{"mbid": "mbid-1", "name": "Artist A", "sort_name": "A, Artist", "debut_date": None, "aliases": [], "url_rels": []}],
            mock_session,
        )

        first_sql = str(mock_session.execute.call_args_list[0].args[0])
        assert "ON CONFLICT" in first_sql

    def test_inserts_aliases(self):
        """alias 목록이 artist_alias 테이블에 INSERT되어야 한다."""
        mock_session = self._make_session_mock(artist_id=5)
        self._run(
            [
                {
                    "mbid": "mbid-1",
                    "name": "Artist A",
                    "sort_name": "A, Artist",
                    "debut_date": None,
                    "aliases": [
                        {"name": "아티스트 A", "locale": "ko"},
                        {"name": "アーティスト A", "locale": "ja"},
                    ],
                    "url_rels": [],
                }
            ],
            mock_session,
        )

        sqls = [str(call.args[0]) for call in mock_session.execute.call_args_list]
        assert any("INSERT INTO artist_alias" in s for s in sqls)
        alias_calls = [c for c in mock_session.execute.call_args_list if "artist_alias" in str(c.args[0])]
        assert len(alias_calls) == 2

    def test_inserts_url_rels(self):
        """url_rels 목록이 artist_url 테이블에 INSERT되어야 한다."""
        mock_session = self._make_session_mock(artist_id=5)
        self._run(
            [
                {
                    "mbid": "mbid-1",
                    "name": "Artist A",
                    "sort_name": "A, Artist",
                    "debut_date": None,
                    "aliases": [],
                    "url_rels": [
                        {"type": "official homepage", "url": "https://example.com"},
                        {"type": "social network", "url": "https://twitter.com/artist"},
                    ],
                }
            ],
            mock_session,
        )

        url_calls = [c for c in mock_session.execute.call_args_list if "artist_url" in str(c.args[0])]
        assert len(url_calls) == 2

    def test_skips_artist_when_id_not_found(self):
        """RETURNING id가 없고 SELECT도 None이면 alias·url 삽입 없이 건너뛰어야 한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = None
        self._run(
            [{"mbid": "mbid-x", "name": "Ghost", "sort_name": "Ghost", "debut_date": None, "aliases": [{"name": "고스트", "locale": "ko"}], "url_rels": []}],
            mock_session,
        )

        sqls = [str(call.args[0]) for call in mock_session.execute.call_args_list]
        assert not any("artist_alias" in s for s in sqls)

    def test_handles_empty_list(self):
        """빈 리스트 입력 시 DB 호출 없이 종료되어야 한다."""
        mock_session = MagicMock()
        self._run([], mock_session)
        mock_session.execute.assert_not_called()

    def test_inserts_multiple_artists(self):
        """복수 아티스트가 모두 INSERT되어야 한다."""
        mock_session = self._make_session_mock()
        artists = [
            {"mbid": f"mbid-{i}", "name": f"Artist {i}", "sort_name": f"{i}", "debut_date": None, "aliases": [], "url_rels": []}
            for i in range(3)
        ]
        self._run(artists, mock_session)

        artist_insert_calls = [c for c in mock_session.execute.call_args_list if "INSERT INTO artist" in str(c.args[0])]
        assert len(artist_insert_calls) == 3


class TestSaveConcertArtists:
    def _run(self, matches, mock_session):
        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            save_concert_artists(matches)

    def test_inserts_into_concert_artist(self):
        """매칭 결과가 concert_artist 테이블에 INSERT되어야 한다."""
        mock_session = MagicMock()
        self._run(
            [{"concert_id": 1, "artist_id": 10, "confidence": "HIGH", "matched_by": "prfcast"}],
            mock_session,
        )

        insert_sql = str(mock_session.execute.call_args_list[0].args[0])
        assert "INSERT INTO concert_artist" in insert_sql

    def test_high_confidence_sets_approved_true(self):
        """confidence=HIGH이면 approved=true로 저장되어야 한다."""
        mock_session = MagicMock()
        self._run(
            [{"concert_id": 1, "artist_id": 10, "confidence": "HIGH", "matched_by": "prfcast"}],
            mock_session,
        )

        params = mock_session.execute.call_args_list[0].args[1]
        assert params["approved"] is True

    def test_low_confidence_sets_approved_false(self):
        """confidence=LOW이면 approved=false로 저장되어야 한다."""
        mock_session = MagicMock()
        self._run(
            [{"concert_id": 1, "artist_id": 10, "confidence": "LOW", "matched_by": "prfnm"}],
            mock_session,
        )

        params = mock_session.execute.call_args_list[0].args[1]
        assert params["approved"] is False

    def test_on_conflict_do_nothing_in_sql(self):
        """중복 매칭 방지를 위해 ON CONFLICT DO NOTHING이 포함되어야 한다."""
        mock_session = MagicMock()
        self._run(
            [{"concert_id": 1, "artist_id": 10, "confidence": "HIGH", "matched_by": "prfcast"}],
            mock_session,
        )

        insert_sql = str(mock_session.execute.call_args_list[0].args[0])
        assert "ON CONFLICT" in insert_sql

    def test_inserts_multiple_matches(self):
        """복수 매칭 결과가 모두 INSERT되어야 한다."""
        mock_session = MagicMock()
        matches = [
            {"concert_id": 1, "artist_id": 10, "confidence": "HIGH", "matched_by": "prfcast"},
            {"concert_id": 2, "artist_id": 20, "confidence": "LOW", "matched_by": "prfnm"},
        ]
        self._run(matches, mock_session)

        assert mock_session.execute.call_count == 2

    def test_handles_empty_list(self):
        """빈 리스트 입력 시 DB 호출 없이 종료되어야 한다."""
        mock_session = MagicMock()
        self._run([], mock_session)
        mock_session.execute.assert_not_called()


class TestSaveToReviewQueue:
    def _run(self, failures, mock_session):
        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            save_to_review_queue(failures)

    def test_inserts_into_matching_review_queue(self):
        """실패 공연이 matching_review_queue 테이블에 INSERT되어야 한다."""
        mock_session = MagicMock()
        self._run([{"concert_id": 5}], mock_session)

        insert_sql = str(mock_session.execute.call_args_list[0].args[0])
        assert "INSERT INTO matching_review_queue" in insert_sql

    def test_status_is_pending(self):
        """INSERT SQL에 PENDING 상태가 포함되어야 한다."""
        mock_session = MagicMock()
        self._run([{"concert_id": 5}], mock_session)

        insert_sql = str(mock_session.execute.call_args_list[0].args[0])
        assert "PENDING" in insert_sql

    def test_on_conflict_do_nothing_in_sql(self):
        """concert_id 중복 시 ON CONFLICT DO NOTHING이 적용되어야 한다."""
        mock_session = MagicMock()
        self._run([{"concert_id": 5}], mock_session)

        insert_sql = str(mock_session.execute.call_args_list[0].args[0])
        assert "ON CONFLICT" in insert_sql

    def test_inserts_multiple_failures(self):
        """복수 실패 공연이 모두 등록되어야 한다."""
        mock_session = MagicMock()
        self._run([{"concert_id": 1}, {"concert_id": 2}, {"concert_id": 3}], mock_session)

        assert mock_session.execute.call_count == 3

    def test_handles_empty_list(self):
        """빈 리스트 입력 시 DB 호출 없이 종료되어야 한다."""
        mock_session = MagicMock()
        self._run([], mock_session)
        mock_session.execute.assert_not_called()


class TestUpdateArtistIsComing:
    def _make_session_mock(self, rowcount=0):
        mock_session = MagicMock()
        mock_session.execute.return_value.rowcount = rowcount
        return mock_session

    def _run(self, mock_session):
        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            return update_artist_is_coming()

    def test_executes_update_statement(self):
        """artist 테이블에 UPDATE 쿼리가 실행되어야 한다."""
        mock_session = self._make_session_mock()
        self._run(mock_session)

        update_sql = str(mock_session.execute.call_args_list[0].args[0])
        assert "UPDATE artist" in update_sql

    def test_uses_current_date_for_comparison(self):
        """공연 종료일 비교에 CURRENT_DATE가 사용되어야 한다."""
        mock_session = self._make_session_mock()
        self._run(mock_session)

        update_sql = str(mock_session.execute.call_args_list[0].args[0])
        assert "CURRENT_DATE" in update_sql

    def test_filters_by_approved_true(self):
        """approved=true인 공연만 is_coming 판단에 반영되어야 한다."""
        mock_session = self._make_session_mock()
        self._run(mock_session)

        update_sql = str(mock_session.execute.call_args_list[0].args[0])
        assert "approved = true" in update_sql

    def test_sets_is_coming_field(self):
        """UPDATE 쿼리가 is_coming 필드를 갱신해야 한다."""
        mock_session = self._make_session_mock()
        self._run(mock_session)

        update_sql = str(mock_session.execute.call_args_list[0].args[0])
        assert "is_coming" in update_sql

    def test_only_updates_changed_rows(self):
        """값이 바뀌는 행만 UPDATE하도록 IS DISTINCT FROM 조건이 포함되어야 한다."""
        mock_session = self._make_session_mock()
        self._run(mock_session)

        update_sql = str(mock_session.execute.call_args_list[0].args[0])
        assert "IS DISTINCT FROM" in update_sql

    def test_returns_updated_row_count(self):
        """갱신된 행 수를 반환해야 한다."""
        mock_session = self._make_session_mock(rowcount=3)
        result = self._run(mock_session)

        assert result == 3
