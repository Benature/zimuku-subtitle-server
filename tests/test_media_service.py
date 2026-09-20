import json

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.models import ScannedFile
from app.services.media_service import MediaService

# Use in-memory database for testing
sqlite_url = "sqlite://"
test_engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})


@pytest.fixture(name="session")
def session_fixture():
    SQLModel.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        yield session
    SQLModel.metadata.drop_all(test_engine)


def test_list_paths(session):
    """Test listing all media paths"""
    # Add some paths
    MediaService.add_path(session, "/movies", "movie")
    MediaService.add_path(session, "/tv", "tv")

    paths = MediaService.list_paths(session)

    assert len(paths) == 2
    assert paths[0].path == "/movies"
    assert paths[1].path == "/tv"


def test_list_paths_empty(session):
    """Test listing paths when none exist"""
    paths = MediaService.list_paths(session)
    assert paths == []


def test_add_path_duplicate(session):
    """Test adding duplicate path raises ValueError"""
    MediaService.add_path(session, "/movies", "movie")

    with pytest.raises(ValueError, match="Path already exists"):
        MediaService.add_path(session, "/movies", "movie")


def test_add_path_success(session):
    """Test adding a new path"""
    path = MediaService.add_path(session, "/downloads", "tv")

    assert path.id is not None
    assert path.path == "/downloads"
    assert path.type == "tv"
    assert path.enabled is True


def test_delete_path(session):
    """Test deleting a path and its associated scanned files"""
    # Add path
    media_path = MediaService.add_path(session, "/movies", "movie")

    # Add scanned file associated with this path
    scanned_file = ScannedFile(
        path_id=media_path.id,
        type="movie",
        file_path="/movies/avatar.mp4",
        filename="avatar.mp4",
    )
    session.add(scanned_file)
    session.commit()

    # Delete path
    result = MediaService.delete_path(session, media_path.id)

    assert result is True

    # Verify path is deleted
    paths = MediaService.list_paths(session)
    assert len(paths) == 0

    # Verify scanned files are deleted
    files = session.exec(select(ScannedFile)).all()
    assert len(files) == 0


def test_delete_path_not_found(session):
    """Test deleting non-existent path returns False"""
    result = MediaService.delete_path(session, 9999)
    assert result is False


def test_update_path(session):
    """Test updating path properties"""
    media_path = MediaService.add_path(session, "/movies", "movie")

    # Update path
    updated = MediaService.update_path(session, media_path.id, enabled=False, path_type="tv")

    assert updated.enabled is False
    assert updated.type == "tv"


def test_update_path_partial(session):
    """Test updating only enabled property"""
    media_path = MediaService.add_path(session, "/movies", "movie")

    updated = MediaService.update_path(session, media_path.id, enabled=False)

    assert updated.enabled is False
    assert updated.type == "movie"  # Unchanged


def test_update_path_not_found(session):
    """Test updating non-existent path returns None"""
    result = MediaService.update_path(session, 9999, enabled=False)
    assert result is None


def test_list_files_no_filter(session):
    """Test listing all scanned files without filter"""
    # Add path
    media_path = MediaService.add_path(session, "/movies", "movie")

    # Add scanned files
    file1 = ScannedFile(path_id=media_path.id, type="movie", file_path="/movies/avatar.mp4", filename="avatar.mp4")
    file2 = ScannedFile(path_id=media_path.id, type="movie", file_path="/movies/test.mp4", filename="test.mp4")
    session.add_all([file1, file2])
    session.commit()

    files = MediaService.list_files(session)

    assert len(files) == 2


def test_list_files_filtered_by_type(session):
    """Test listing files filtered by type"""
    # Add paths
    movie_path = MediaService.add_path(session, "/movies", "movie")
    tv_path = MediaService.add_path(session, "/tv", "tv")

    # Add scanned files
    movie_file = ScannedFile(path_id=movie_path.id, type="movie", file_path="/movies/avatar.mp4", filename="avatar.mp4")
    tv_file = ScannedFile(path_id=tv_path.id, type="tv", file_path="/tv/show.mp4", filename="show.mp4")
    session.add_all([movie_file, tv_file])
    session.commit()

    # Filter by movie
    movie_files = MediaService.list_files(session, path_type="movie")

    assert len(movie_files) == 1
    assert movie_files[0].type == "movie"

    # Filter by tv
    tv_files = MediaService.list_files(session, path_type="tv")

    assert len(tv_files) == 1
    assert tv_files[0].type == "tv"


def test_list_files_empty(session):
    """Test listing files when none exist"""
    files = MediaService.list_files(session)
    assert files == []


def test_list_media_groups_tv_by_show_season_and_episode(session):
    tv_path = MediaService.add_path(session, "/tv", "tv")
    files = [
        ScannedFile(
            path_id=tv_path.id,
            type="tv",
            file_path="/tv/Foundation/S01E01.mkv",
            filename="Foundation.S01E01.mkv",
            extracted_title="Foundation",
            nfo_title="基地",
            nfo_original_title="Foundation",
            nfo_aliases=json.dumps(["基地：起源"], ensure_ascii=False),
            season=1,
            episode=1,
            has_subtitle=True,
        ),
        ScannedFile(
            path_id=tv_path.id,
            type="tv",
            file_path="/tv/Foundation/S01E02.mkv",
            filename="Foundation.S01E02.mkv",
            extracted_title="Foundation",
            season=1,
            episode=2,
        ),
        ScannedFile(
            path_id=tv_path.id,
            type="tv",
            file_path="/tv/Foundation/S02E01.mkv",
            filename="Foundation.S02E01.mkv",
            extracted_title="Foundation",
            season=2,
            episode=1,
        ),
    ]
    session.add_all(files)
    session.commit()

    shows, total = MediaService.list_media_paginated(session, level="show", query="found")
    assert total == 1
    assert shows[0]["title"] == "Foundation"
    assert shows[0]["file_count"] == 3
    assert shows[0]["subtitle_file_count"] == 1
    assert shows[0]["missing_subtitle_file_count"] == 2
    assert shows[0]["nfo_title"] == "基地"
    assert shows[0]["nfo_aliases"] == ["基地：起源"]

    nfo_search_results, total = MediaService.list_media_paginated(session, level="show", query="起源")
    assert total == 1
    assert nfo_search_results[0]["title"] == "Foundation"

    seasons, total = MediaService.list_media_paginated(session, level="season", title="Foundation")
    assert total == 2
    assert [item["season"] for item in seasons] == [1, 2]

    episodes, total = MediaService.list_media_paginated(session, level="episode", title="Foundation", season=1)
    assert total == 2
    assert [item["episode"] for item in episodes] == [1, 2]
    assert all("file_path" not in item for item in episodes)


def test_list_media_groups_movies_and_paginates(session):
    movie_path = MediaService.add_path(session, "/movies", "movie")
    session.add_all(
        [
            ScannedFile(
                path_id=movie_path.id,
                type="movie",
                file_path="/movies/Arrival/Arrival.2016.mkv",
                filename="Arrival.2016.mkv",
                extracted_title="Arrival",
                year="2016",
            ),
            ScannedFile(
                path_id=movie_path.id,
                type="movie",
                file_path="/movies/Arrival/Arrival.2016.uhd.mkv",
                filename="Arrival.2016.uhd.mkv",
                extracted_title="Arrival",
                year="2016",
                has_subtitle=True,
            ),
        ]
    )
    session.commit()

    movies, total = MediaService.list_media_paginated(session, level="movie", query="2016", limit=1)
    assert total == 1
    assert movies[0]["media_key"] == "movie:Arrival:2016"
    assert movies[0]["file_count"] == 2


def test_set_work_allow_no_subtitle_updates_all_files_of_work(session):
    tv_path = MediaService.add_path(session, "/tv", "tv")
    session.add_all(
        [
            ScannedFile(
                path_id=tv_path.id,
                type="tv",
                file_path="/tv/Show/S01E01.mkv",
                filename="Show.S01E01.mkv",
                extracted_title="Show (2024)",
                season=1,
                episode=1,
            ),
            ScannedFile(
                path_id=tv_path.id,
                type="tv",
                file_path="/tv/Show/S01E02.mkv",
                filename="Show.S01E02.mkv",
                extracted_title="Show",
                season=1,
                episode=2,
            ),
            ScannedFile(
                path_id=tv_path.id,
                type="movie",
                file_path="/tv/Show.mkv",
                filename="Show.mkv",
                extracted_title="Show",
            ),
        ]
    )
    session.commit()

    # 与 _load_series_file_ids 口径一致：传入带年份标题可同时命中 "Show" 与 "Show (2024)"
    updated = MediaService.set_work_allow_no_subtitle(session, media_type="tv", title="Show (2024)", allow=True)

    assert updated == 2
    files = session.exec(select(ScannedFile).where(ScannedFile.type == "tv")).all()
    assert all(file_record.allow_no_subtitle for file_record in files)
    movie_file = session.exec(select(ScannedFile).where(ScannedFile.type == "movie")).one()
    assert movie_file.allow_no_subtitle is False

    updated = MediaService.set_work_allow_no_subtitle(session, media_type="tv", title="Show (2024)", allow=False)
    assert updated == 2
    files = session.exec(select(ScannedFile).where(ScannedFile.type == "tv")).all()
    assert not any(file_record.allow_no_subtitle for file_record in files)


def test_set_work_allow_no_subtitle_raises_for_unknown_title(session):
    with pytest.raises(LookupError):
        MediaService.set_work_allow_no_subtitle(session, media_type="movie", title="Ghost", allow=True)


def test_list_media_groups_reflects_allow_no_subtitle(session):
    movie_path = MediaService.add_path(session, "/movies", "movie")
    session.add_all(
        [
            ScannedFile(
                path_id=movie_path.id,
                type="movie",
                file_path="/movies/Silent/Silent.2024.mkv",
                filename="Silent.2024.mkv",
                extracted_title="Silent",
                year="2024",
                allow_no_subtitle=True,
            ),
            ScannedFile(
                path_id=movie_path.id,
                type="movie",
                file_path="/movies/Noisy/Noisy.2024.mkv",
                filename="Noisy.2024.mkv",
                extracted_title="Noisy",
                year="2024",
            ),
        ]
    )
    session.commit()

    movies, total = MediaService.list_media_paginated(session, level="movie")

    assert total == 2
    by_title = {item["title"]: item for item in movies}
    assert by_title["Silent"]["allow_no_subtitle"] is True
    assert by_title["Silent"]["missing_subtitle_file_count"] == 0
    assert by_title["Noisy"]["allow_no_subtitle"] is False
    assert by_title["Noisy"]["missing_subtitle_file_count"] == 1
