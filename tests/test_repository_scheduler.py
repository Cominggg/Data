"""repository.py의 스케줄러용 신규 함수 단위 테스트."""
from unittest.mock import MagicMock, patch

from db.repository import (
    get_all_aliases,
    get_all_artist_mbids,
    get_existing_kopis_ids,
    get_unmatched_concerts,
    save_concert_artists,
    update_artist_is_coming,
    update_concert_fetch_attempted,
)


def _make_session_ctx(mock_session):
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_session)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


class TestSaveConcertArtists:
    def test_insert_uses_on_conflict_do_nothing(self):
        """INSERT SQL에 ON CONFLICT가 포함되어야 한다."""
        mock_session = MagicMock()
        with patch("db.repository.get_session", return_value=_make_session_ctx(mock_session)):
            save_concert_artists([
                {"concert_id": 1, "artist_id": 10, "confidence": "HIGH", "matched_by": "prfcast"}
            ])

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


class TestUpdateArtistIsComing:
    def test_executes_single_bulk_update(self):
        """전체 아티스트를 단일 UPDATE로 갱신해야 한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.rowcount = 5
        with patch("db.repository.get_session", return_value=_make_session_ctx(mock_session)):
            update_artist_is_coming()

        assert mock_session.execute.call_count == 1

    def test_returns_updated_row_count(self):
        """갱신된 행 수를 반환해야 한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.rowcount = 3
        with patch("db.repository.get_session", return_value=_make_session_ctx(mock_session)):
            result = update_artist_is_coming()

        assert result == 3

    def test_update_sql_uses_end_date(self):
        """UPDATE SQL이 end_date >= CURRENT_DATE 조건으로 is_coming을 갱신해야 한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.rowcount = 0
        with patch("db.repository.get_session", return_value=_make_session_ctx(mock_session)):
            update_artist_is_coming()

        sql = str(mock_session.execute.call_args_list[0].args[0])
        assert "is_coming" in sql
        assert "end_date" in sql

    def test_update_sql_only_changes_differing_rows(self):
        """값이 실제로 바뀌는 행만 UPDATE해야 한다 (IS DISTINCT FROM)."""
        mock_session = MagicMock()
        mock_session.execute.return_value.rowcount = 0
        with patch("db.repository.get_session", return_value=_make_session_ctx(mock_session)):
            update_artist_is_coming()

        sql = str(mock_session.execute.call_args_list[0].args[0])
        assert "IS DISTINCT FROM" in sql


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


class TestGetExistingKopisIds:
    def test_returns_set_of_kopis_ids(self):
        """DB의 kopis_id를 집합으로 반환해야 한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = [
            ("PF001",), ("PF002",)
        ]

        with patch("db.repository.get_session", return_value=_make_session_ctx(mock_session)):
            result = get_existing_kopis_ids()

        assert result == {"PF001", "PF002"}

    def test_returns_empty_set_when_no_concerts(self):
        """공연이 없으면 빈 집합을 반환해야 한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = []

        with patch("db.repository.get_session", return_value=_make_session_ctx(mock_session)):
            result = get_existing_kopis_ids()

        assert result == set()

    def test_queries_concert_table(self):
        """concert 테이블을 SELECT해야 한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = []

        with patch("db.repository.get_session", return_value=_make_session_ctx(mock_session)):
            get_existing_kopis_ids()

        sql = str(mock_session.execute.call_args_list[0].args[0])
        assert "concert" in sql
        assert "kopis_id" in sql


class TestUpdateConcertFetchAttempted:
    def test_executes_update_on_concert_table(self):
        """concert 테이블의 fetch_attempted_at을 UPDATE해야 한다."""
        mock_session = MagicMock()

        with patch("db.repository.get_session", return_value=_make_session_ctx(mock_session)):
            update_concert_fetch_attempted(42)

        sql = str(mock_session.execute.call_args_list[0].args[0])
        assert "fetch_attempted_at" in sql
        assert "concert" in sql

    def test_uses_correct_concert_id(self):
        """전달된 concert_id가 UPDATE 쿼리에 바인딩되어야 한다."""
        mock_session = MagicMock()

        with patch("db.repository.get_session", return_value=_make_session_ctx(mock_session)):
            update_concert_fetch_attempted(99)

        params = mock_session.execute.call_args_list[0].args[1]
        assert params["id"] == 99
