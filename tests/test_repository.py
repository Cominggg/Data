from unittest.mock import MagicMock, patch

from db.repository import (
    get_active_concerts,
    save_artists,
    save_concert_artists,
    update_artist_is_coming,
    upsert_artist_url,
)


class TestGetActiveConcerts:
    def _run(self, mock_rows):
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = mock_rows
        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            return get_active_concerts()

    def test_filters_by_active_status(self):
        """공연예정·공연중 상태 필터가 SQL에 포함되어야 한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = []
        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            get_active_concerts()

        sql = str(mock_session.execute.call_args_list[0].args[0])
        assert "UPCOMING" in sql
        assert "ONGOING" in sql

    def test_returns_kopis_id_and_update_date(self):
        """반환값에 kopis_id와 kopis_update_date 키가 포함되어야 한다."""
        result = self._run([("PF123", "2024-01-01"), ("PF456", "2024-02-01")])

        assert len(result) == 2
        assert result[0]["kopis_id"] == "PF123"
        assert result[0]["kopis_update_date"] == "2024-01-01"

    def test_handles_null_update_date(self):
        """kopis_update_date가 NULL이면 None으로 반환되어야 한다."""
        result = self._run([("PF789", None)])

        assert result[0]["kopis_update_date"] is None

    def test_returns_empty_list_when_no_active_concerts(self):
        """활성 공연이 없으면 빈 리스트를 반환해야 한다."""
        result = self._run([])

        assert result == []


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
            [
                {
                    "mbid": "mbid-1",
                    "name": "Artist A",
                    "sort_name": "A, Artist",
                    "debut_date": "2010-01-01",
                    "aliases": [],
                    "url_rels": [],
                }
            ],
            mock_session,
        )

        first_sql = str(mock_session.execute.call_args_list[0].args[0])
        assert "INSERT INTO artist" in first_sql

    def test_on_conflict_mbid_do_nothing(self):
        """중복 mbid 시 ON CONFLICT DO NOTHING이 포함되어야 한다."""
        mock_session = self._make_session_mock()
        self._run(
            [
                {
                    "mbid": "mbid-1",
                    "name": "Artist A",
                    "sort_name": "A, Artist",
                    "debut_date": None,
                    "aliases": [],
                    "url_rels": [],
                }
            ],
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

        sqls = [str(c.args[0]) for c in mock_session.execute.call_args_list]
        assert any("INSERT INTO artist_alias" in s for s in sqls)
        alias_calls = [
            c for c in mock_session.execute.call_args_list if "artist_alias" in str(c.args[0])
        ]
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

        url_calls = [
            c for c in mock_session.execute.call_args_list if "artist_url" in str(c.args[0])
        ]
        assert len(url_calls) == 2

    def test_falls_back_to_select_when_returning_is_none(self):
        """RETURNING id가 None(중복 충돌)이면 SELECT로 fallback해 alias를 정상 저장해야 한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.side_effect = [None, (7,)]
        self._run(
            [
                {
                    "mbid": "mbid-dup",
                    "name": "Dup Artist",
                    "sort_name": "Dup",
                    "debut_date": None,
                    "aliases": [{"name": "중복아티스트", "locale": "ko"}],
                    "url_rels": [],
                }
            ],
            mock_session,
        )

        alias_calls = [
            c for c in mock_session.execute.call_args_list if "artist_alias" in str(c.args[0])
        ]
        assert len(alias_calls) == 1

    def test_skips_artist_when_id_not_found(self):
        """RETURNING id가 없고 SELECT도 None이면 alias·url 삽입 없이 건너뛰어야 한다."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = None
        self._run(
            [
                {
                    "mbid": "mbid-x",
                    "name": "Ghost",
                    "sort_name": "Ghost",
                    "debut_date": None,
                    "aliases": [{"name": "고스트", "locale": "ko"}],
                    "url_rels": [],
                }
            ],
            mock_session,
        )

        sqls = [str(c.args[0]) for c in mock_session.execute.call_args_list]
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
            {
                "mbid": f"mbid-{i}",
                "name": f"Artist {i}",
                "sort_name": f"{i}",
                "debut_date": None,
                "aliases": [],
                "url_rels": [],
            }
            for i in range(3)
        ]
        self._run(artists, mock_session)

        artist_insert_calls = [
            c for c in mock_session.execute.call_args_list if "INSERT INTO artist" in str(c.args[0])
        ]
        assert len(artist_insert_calls) == 3


class TestUpsertArtistUrl:
    def _run(self, artist_id, url_type, url, mock_session):
        with patch("db.repository.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            upsert_artist_url(artist_id, url_type, url)

    def test_inserts_into_artist_url_table(self):
        """artist_url 테이블에 INSERT되어야 한다."""
        mock_session = MagicMock()
        self._run(5, "Spotify", "https://open.spotify.com/artist/abc123", mock_session)

        sql, params = mock_session.execute.call_args.args
        assert "INSERT INTO artist_url" in str(sql)
        assert params == {
            "artist_id": 5,
            "type": "Spotify",
            "url": "https://open.spotify.com/artist/abc123",
        }

    def test_on_conflict_artist_id_type_do_nothing(self):
        """(artist_id, type) 중복 시 ON CONFLICT DO NOTHING이 포함되어야 한다."""
        mock_session = MagicMock()
        self._run(5, "Spotify", "https://open.spotify.com/artist/abc123", mock_session)

        sql = str(mock_session.execute.call_args.args[0])
        assert "ON CONFLICT (artist_id, type) DO NOTHING" in sql


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
            [{"concert_id": 1, "artist_id": 10}],
            mock_session,
        )

        insert_sql = str(mock_session.execute.call_args_list[0].args[0])
        assert "INSERT INTO concert_artist" in insert_sql

    def test_confidence_column_not_in_sql(self):
        """confidence 컬럼이 INSERT SQL에 포함되지 않아야 한다."""
        mock_session = MagicMock()
        self._run(
            [{"concert_id": 1, "artist_id": 10}],
            mock_session,
        )

        insert_sql = str(mock_session.execute.call_args_list[0].args[0])
        assert "confidence" not in insert_sql

    def test_on_conflict_do_nothing_in_sql(self):
        """중복 매칭 방지를 위해 ON CONFLICT DO NOTHING이 포함되어야 한다."""
        mock_session = MagicMock()
        self._run(
            [{"concert_id": 1, "artist_id": 10}],
            mock_session,
        )

        insert_sql = str(mock_session.execute.call_args_list[0].args[0])
        assert "ON CONFLICT" in insert_sql

    def test_inserts_multiple_matches(self):
        """복수 매칭 결과가 모두 INSERT되어야 한다."""
        mock_session = MagicMock()
        matches = [
            {"concert_id": 1, "artist_id": 10},
            {"concert_id": 2, "artist_id": 20},
        ]
        self._run(matches, mock_session)

        assert mock_session.execute.call_count == 2

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

    def test_excludes_excluded_status_concerts(self):
        """status='EXCLUDED'인 공연은 is_coming 판단에서 제외되어야 한다."""
        mock_session = self._make_session_mock()
        self._run(mock_session)

        update_sql = str(mock_session.execute.call_args_list[0].args[0])
        assert "EXCLUDED" in update_sql

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
