# Coming DB ERD

```sql
CREATE TABLE "user" (
    id bigint PRIMARY KEY,
    provider varchar(20),
    provider_id varchar(255),
    nickname varchar(50),
    profile_image_url text,
    role varchar(20),
    status varchar(20),
    created_at timestamp,
    updated_at timestamp
);

CREATE TABLE artist (
    id bigint PRIMARY KEY,
    mbid varchar(36) UNIQUE,
    name varchar(255),
    sort_name varchar(255),
    debut_date date,
    is_coming boolean,
    created_at timestamp,
    updated_at timestamp
);

CREATE TABLE artist_alias (
    id bigint PRIMARY KEY,
    artist_id bigint REFERENCES artist(id),
    name varchar(255),
    locale varchar(10),
    is_learned boolean,
    created_at timestamp
);

CREATE TABLE artist_url (
    id bigint PRIMARY KEY,
    artist_id bigint REFERENCES artist(id),
    type varchar(100),
    url text
);

CREATE TABLE user_follow_artist (
    id bigint PRIMARY KEY,
    user_id bigint REFERENCES "user"(id),
    artist_id bigint REFERENCES artist(id),
    created_at timestamp
);

CREATE TABLE concert (
    id bigint PRIMARY KEY,
    kopis_id varchar(50) UNIQUE,
    title varchar(500),
    cast text,
    start_date date,
    end_date date,
    venue_name varchar(255),
    venue_address varchar(500),
    poster_url text,
    status varchar(20),
    view_count bigint,
    kopis_update_date date,
    created_at timestamp,
    updated_at timestamp
);

CREATE TABLE concert_booking_link (
    id bigint PRIMARY KEY,
    concert_id bigint REFERENCES concert(id),
    name varchar(100),
    url text
);

CREATE TABLE concert_artist (
    id bigint PRIMARY KEY,
    concert_id bigint REFERENCES concert(id),
    artist_id bigint REFERENCES artist(id),
    confidence varchar(10),
    matched_by varchar(20),
    approved boolean,
    created_at timestamp
);

CREATE TABLE concert_status_log (
    id bigint PRIMARY KEY,
    concert_id bigint REFERENCES concert(id),
    previous_status varchar(20),
    new_status varchar(20),
    changed_by varchar(20),
    admin_user_id bigint REFERENCES "user"(id),
    changed_at timestamp
);

CREATE TABLE user_concert_calendar (
    id bigint PRIMARY KEY,
    user_id bigint REFERENCES "user"(id),
    concert_id bigint REFERENCES concert(id),
    created_at timestamp
);

CREATE TABLE setlist (
    id bigint PRIMARY KEY,
    concert_id bigint REFERENCES concert(id),
    setlist_fm_id varchar(50) UNIQUE,
    collected_at timestamp
);

CREATE TABLE setlist_track (
    id bigint PRIMARY KEY,
    setlist_id bigint REFERENCES setlist(id),
    position int,
    song_name varchar(255),
    info text
);

CREATE TABLE release_group (
    id bigint PRIMARY KEY,
    mbid varchar(36) UNIQUE,
    artist_id bigint REFERENCES artist(id),
    title varchar(500),
    type varchar(20),
    first_release_date date,
    cover_url text,
    label varchar(255),
    created_at timestamp,
    updated_at timestamp
);

CREATE TABLE track (
    id bigint PRIMARY KEY,
    release_group_id bigint REFERENCES release_group(id),
    mbid varchar(36) UNIQUE,
    title varchar(500),
    position int,
    length_ms int
);

CREATE TABLE inquiry (
    id bigint PRIMARY KEY,
    user_id bigint REFERENCES "user"(id),
    type varchar(20),
    concert_id bigint REFERENCES concert(id),
    artist_id bigint REFERENCES artist(id),
    title varchar(255),
    content text,
    status varchar(20),
    admin_note text,
    created_at timestamp,
    updated_at timestamp
);

CREATE TABLE matching_review_queue (
    id bigint PRIMARY KEY,
    concert_id bigint REFERENCES concert(id),
    matched_artist_id bigint REFERENCES artist(id),
    matched_alias varchar(255),
    score float,
    status varchar(20),
    reviewed_by bigint REFERENCES "user"(id),
    reviewed_at timestamp,
    created_at timestamp
);
```

## 테이블 관계 요약

| 테이블 | 설명 |
|--------|------|
| `user` | 서비스 유저 |
| `artist` | MusicBrainz 기반 아티스트 |
| `artist_alias` | 아티스트 별칭 (한/영/일) |
| `artist_url` | 아티스트 외부 링크 (SNS 등) |
| `user_follow_artist` | 유저 아티스트 팔로우 |
| `concert` | KOPIS 수집 공연 (공연장 정보 텍스트 포함) |
| `concert_booking_link` | 예매처 링크 |
| `concert_artist` | 공연-아티스트 매칭 결과 |
| `concert_status_log` | 공연 상태 변경 이력 |
| `user_concert_calendar` | 유저 공연 일정 저장 |
| `setlist` | setlist.fm 수집 셋리스트 |
| `setlist_track` | 셋리스트 트랙 목록 |
| `release_group` | 앨범·싱글·EP |
| `track` | 릴리즈 트랙 |
| `inquiry` | 유저 문의 |
| `matching_review_queue` | 매칭 검토 큐 |

## 변경 이력

| 날짜 | 내용 |
|------|------|
| 2026-04-23 | venue 테이블 제거, concert에 venue_name/venue_address 컬럼으로 통합 |
| 2026-04-24 | artist_member 테이블 제거 — 그룹 멤버 관계 미관리 결정 |
| 2026-04-24 | user.is_deleted → user.status varchar(20) 로 변경 |
| 2026-04-24 | inquiry에 title varchar(255) 컬럼 추가 |
| 2026-04-24 | release_group.lastfm_summary 컬럼 제거 — API·파이프라인 미사용 |
