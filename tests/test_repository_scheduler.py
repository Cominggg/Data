"""repository.py의 스케줄러용 신규 함수 단위 테스트."""
from unittest.mock import MagicMock, call, patch

import pytest

from db.repository import (
    get_all_aliases,
    get_all_artist_mbids,
    get_unmatched_concerts,
    save_concert_artists,
    save_to_review_queue,
    update_artist_is_coming,
)


def _make_session_ctx(mock_session):
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_session)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


class TestSaveConcertArtists:
    def test_high_match_sets_approved_true(self):
        """HIGH 매칭은 approved=True로 저장되어야 한다."""
        mock_session = MagicMock()
        with patch("db.repository.get_session", return_value=_make_session_ctx(mock_session)):
            save_concert_artists([{"concert_id": 1, "artist_id": 10, "confidence": "HIGH", "matched_by": "prfcast"}])

        params = mock_session.execute.call_args_list[0].args[1]
        assert params["approved"] is True

    def test_low_match_sets_approved_false(self):
        """LOW 매칭은 approved=False로 저장되어야 한다."""
        mock_session = MagicMock()
        with patch("db.repository.get_session", return_value=_make_session_ctx(mock_session)):
            save_concert_artists([{"concert_id": 1, "artist_id": 10, "confidence": "LOW", "matched_by": "prfnm"}])

        params = mock_session.execute.call_args_list[0].args[1]
        assert params["approved"] is False

    def test_insert_uses_on_conflict_do_nothing(self):
        """INSERT SQL에 ON CONFLICT가 포함되어야 한다."""
        mock_session = MagicMock()
        with patch("db.repository.get_session", return_value=_make_session_ctx(mock_session)):
            save_concert_artists([{"concert_id": 1, "artist_id": 10, "confidence": "HIGH", "matched_by": "prfcast"}])

        sql = str(mock_session.execute.call_args_list[0].args[0])
        assert "ON CONFLICT" in sql

    def test_multiple_matches_insert_all(self):
        """여러 매칭 결과가 모두 INSERT되어야 한다."""
        mock_session = MagicMock()
        matches = [
            {"concert_id": 1, "artist_id": 10, "confidence": "HIGH", "matched_by": "prfcast"},
            {"concert_id": 2, "artist_id": 20, "confidence": "LOW", "matched_by": "prfnm"},
        ]
        with patch("db.repository.get_session", return_value=_make_session_ctx(mock_session)):
            save_concert_artists(matches)

        assert mock_session.execute.call_count == 2

    def test_empty_list_does_not_call_execute(self):
        """빈 리스트이면 execute가 호출되지 않아야 한다."""
        mock_session = MagicMock()
        with patch("db.repository.get_session", return_value=_make_session_ctx(mock_session)):
            save_concert_artists([])

        mock_session.execute.assert_not_called()


class TestSaveToReviewQueue:
    def test_inserts_concert_id(self):
        """매칭 실패 concert_id가 INSERT되어야 한다."""
        mock_session = MagicMock()
        with patch("db.repository.get_session", return_value=_make_session_ctx(mock_session)):
            save_to_review_queue([{"concert_id": 99}])

        params = mock_session.execute.call_args_list[0].args[1]
        assert params["concert_id"] == 99

    def test_insert_uses_on_conflict(self):
        """INSERT SQL에 ON CONFLICT가 포함되어야 한다."""
        mock_session = MagicMock()
        with patch("db.repository.get_session", return_value=_make_session_ctx(mock_session)):
            save_to_review_queue([{"concert_id": 1}])

        sql = str(mock_session.execute.call_args_list[0].args[0])
        assert "ON CONFLICT" in sql

    def test_multiple_failures_insert_all(self):
        """여러 실패 항목이 모두 INSERT되어야 한다."""
        mock_session = MagicMock()
        with patch("db.repository.get_session", return_value=_make_session_ctx(mock_session)):
            save_to_review_queue([{"concert_id": 1}, {"concert_id": 2}, {"concert_id": 3}])

        assert mock_session.execute.call_count == 3


class TestUpdateArtistIsComing:
    def test_empty_list_skips_db(self):
        """빈 리스트이면 DB 호출이 없어야 한다."""
        with patch("db.repository.get_session") as mock_get_session:
            update_artist_is_coming([])

        mock_get_session.assert_not_called()

    def test_executes_update_per_artist(self):
        """아티스트 수만큼 UPDATE가 실행되어야 한다."""
        mock_session = MagicMock()
        with patch("db.repository.get_session", return_value=_make_session_ctx(mock_session)):
            update_artist_is_coming([1, 2, 3])

        assert mock_session.execute.call_count == 3

    def test_update_sql_references_concert_status(self):
        """UPDATE SQL이 공연 상태를 기준으로 is_coming을 갱신해야 한다."""
        mock_session = MagicMock()
        with patch("db.repository.get_session", return_value=_make_session_ctx(mock_session)):
            update_artist_is_coming([1])

        sql = str(mock_session.execute.call_args_list[0].args[0])
        assert "is_coming" in sql
        assert "artist_id" in sql

    def test_correct_artist_id_passed_as_param(self):
        """UPDATE 파라미터에 올바른 artist_id가 전달되어야 한다."""
        mock_session = MagicMock()
        with patch("db.repository.get_session", return_value=_make_session_ctx(mock_session)):
            update_artist_is_coming([42])

        params = mock_session.execute.call_args_list[0].args[1]
        assert params["artist_id"] == 42


class TestGetAllAliases:
    def test_returns_list_of_dicts(self):
        """결과가 artist_id, name 키를 가진 dict 리스트여야 한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = [(1, "아이유"), (2, "BTS")]

        with patch("db.repository.get_session", return_value=_make_session_ctx(mock_session)):
            result = get_all_aliases()

        assert result == [{"artist_id": 1, "name": "아이유"}, {"artist_id": 2, "name": "BTS"}]

    def test_returns_empty_list_when_no_aliases(self):
        """alias가 없으면 빈 리스트를 반환해야 한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = []

        with patch("db.repository.get_session", return_value=_make_session_ctx(mock_session)):
            result = get_all_aliases()

        assert result == []

    def test_queries_artist_alias_table(self):
        """artist_alias 테이블을 SELECT해야 한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = []

        with patch("db.repository.get_session", return_value=_make_session_ctx(mock_session)):
            get_all_aliases()

        sql = str(mock_session.execute.call_args_list[0].args[0])
        assert "artist_alias" in sql


class TestGetAllArtistMbids:
    def test_returns_mbid_list(self):
        """MBID 문자열 리스트를 반환해야 한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = [
            ("mbid-1",), ("mbid-2",)
        ]

        with patch("db.repository.get_session", return_value=_make_session_ctx(mock_session)):
            result = get_all_artist_mbids()

        assert result == ["mbid-1", "mbid-2"]

    def test_returns_empty_list_when_no_artists(self):
        """아티스트가 없으면 빈 리스트를 반환해야 한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = []

        with patch("db.repository.get_session", return_value=_make_session_ctx(mock_session)):
            result = get_all_artist_mbids()

        assert result == []


class TestGetUnmatchedConcerts:
    def test_returns_concert_dicts(self):
        """concert_id, title, cast 키를 가진 dict 리스트를 반환해야 한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = [
            (1, "공연 A", "아이유"), (2, "공연 B", None)
        ]

        with patch("db.repository.get_session", return_value=_make_session_ctx(mock_session)):
            result = get_unmatched_concerts()

        assert result == [
            {"concert_id": 1, "title": "공연 A", "cast": "아이유"},
            {"concert_id": 2, "title": "공연 B", "cast": None},
        ]

    def test_uses_left_join_to_find_unmatched(self):
        """SQL이 LEFT JOIN으로 미매칭 공연을 찾아야 한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = []

        with patch("db.repository.get_session", return_value=_make_session_ctx(mock_session)):
            get_unmatched_concerts()

        sql = str(mock_session.execute.call_args_list[0].args[0])
        assert "LEFT JOIN" in sql
        assert "concert_artist" in sql
