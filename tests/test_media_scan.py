from pathlib import Path

import pytest
from sqlmodel import Session, delete, select

from app.db.models import MediaPath, ScannedFile
from app.db.session import create_db_and_tables, engine
from app.services.media_service import MediaService


@pytest.fixture(autouse=True)
def clean_app_db():
    create_db_and_tables()
    with Session(engine) as session:
        session.exec(delete(ScannedFile))
        session.exec(delete(MediaPath))
        session.commit()


@pytest.fixture(name="temp_media_dir")
def temp_media_dir_fixture(tmp_path: Path):
    movie_dir = tmp_path / "Interstellar (2014)"
    movie_dir.mkdir()
    (movie_dir / "interstellar.1080p.mkv").touch()

    tv_dir = tmp_path / "The Last of Us"
    tv_dir.mkdir()
    (tv_dir / "The.Last.of.Us.S01E01.mkv").touch()
    (tv_dir / "The.Last.of.Us.S01E02.mkv").touch()

    (tmp_path / "lone_video.mp4").touch()
    return tmp_path


@pytest.mark.anyio
async def test_run_media_scan_logic(temp_media_dir):
    with Session(engine) as session:
        mp = MediaPath(path=str(temp_media_dir), type="movie", enabled=True)
        session.add(mp)
        session.commit()

    await MediaService.run_media_scan_and_match()

    with Session(engine) as session:
        files = session.exec(select(ScannedFile)).all()

    assert len(files) == 3

    interstellar_files = [file_record for file_record in files if "interstellar" in file_record.filename.lower()]
    assert len(interstellar_files) == 1
    assert interstellar_files[0].extracted_title == "Interstellar (2014)"

    tlou_files = [file_record for file_record in files if "the.last.of.us" in file_record.filename.lower()]
    assert len(tlou_files) == 2
    for file_record in tlou_files:
        assert file_record.extracted_title == "The Last of Us"
        assert file_record.season == 1
        assert file_record.episode in [1, 2]


@pytest.mark.anyio
async def test_scan_persists_nfo_search_fields(tmp_path):
    movie_root = tmp_path / "movies"
    movie_dir = movie_root / "Internal Name"
    movie_dir.mkdir(parents=True)
    (movie_dir / "Internal.Name.2024.mkv").touch()
    (movie_dir / "movie.nfo").write_text(
        """<movie>
<title>中文片名</title>
<originaltitle>Original Movie Title</originaltitle>
<alternativetitle>Alternate Movie Title</alternativetitle>
</movie>""",
        encoding="utf-8",
    )

    with Session(engine) as session:
        session.add(MediaPath(path=str(movie_root), type="movie", enabled=True))
        session.commit()

    await MediaService.run_media_scan_and_match("movie")

    with Session(engine) as session:
        scanned_file = session.exec(select(ScannedFile).where(ScannedFile.filename == "Internal.Name.2024.mkv")).one()

    assert scanned_file.nfo_title == "中文片名"
    assert scanned_file.nfo_original_title == "Original Movie Title"
    assert scanned_file.nfo_aliases == '["Alternate Movie Title"]'


@pytest.mark.anyio
async def test_scan_preserves_records_when_media_root_inaccessible(tmp_path):
    """媒体根目录不可访问（如挂载缺失）时，其下记录不得被清理，避免误删全库。"""
    missing_root = tmp_path / "unmounted"
    fake_path = missing_root / "Show" / "Show.S01E01.mkv"

    with Session(engine) as session:
        media_path = MediaPath(path=str(missing_root), type="tv", enabled=True)
        session.add(media_path)
        session.commit()
        session.refresh(media_path)
        session.add(
            ScannedFile(
                path_id=media_path.id,
                file_path=str(fake_path),
                filename=fake_path.name,
                extracted_title="Show",
                type="tv",
                allow_no_subtitle=True,
            )
        )
        session.commit()

    await MediaService.run_media_scan_and_match("tv")

    with Session(engine) as session:
        files = session.exec(select(ScannedFile)).all()

    assert len(files) == 1
    assert files[0].filename == fake_path.name
    assert files[0].allow_no_subtitle is True


@pytest.mark.anyio
async def test_cleanup_non_existent_files(temp_media_dir):
    fake_path = temp_media_dir / "non_existent.mkv"

    with Session(engine) as session:
        session.add(
            ScannedFile(
                path_id=1,
                file_path=str(fake_path),
                filename="non_existent.mkv",
                extracted_title="Fake",
                type="movie",
            )
        )
        session.add(MediaPath(path=str(temp_media_dir), type="movie", enabled=True))
        session.commit()

    await MediaService.run_media_scan_and_match()

    with Session(engine) as session:
        existing_fake = session.exec(select(ScannedFile).where(ScannedFile.file_path == str(fake_path))).first()
        files = session.exec(select(ScannedFile)).all()

    assert existing_fake is None
    assert len(files) == 3


@pytest.mark.anyio
async def test_scan_removes_records_not_found_in_latest_discovery(tmp_path, monkeypatch):
    movie_root = tmp_path / "movies"
    movie_dir = movie_root / "Arrival"
    movie_dir.mkdir(parents=True)
    new_file = movie_dir / "Arrival.2016.1080p.mkv"
    new_file.touch()
    old_file = movie_dir / "arrival.2016.1080p.mkv"

    original_exists = Path.exists

    def fake_exists(path: Path):
        if str(path) == str(old_file):
            return True
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", fake_exists)

    with Session(engine) as session:
        media_path = MediaPath(path=str(movie_root), type="movie", enabled=True)
        session.add(media_path)
        session.commit()
        session.refresh(media_path)
        session.add(
            ScannedFile(
                path_id=media_path.id,
                file_path=str(old_file),
                filename=old_file.name,
                extracted_title="Arrival",
                type="movie",
            )
        )
        session.commit()

    await MediaService.run_media_scan_and_match("movie")

    with Session(engine) as session:
        files = session.exec(select(ScannedFile)).all()

    assert [file_record.filename for file_record in files] == [new_file.name]


@pytest.mark.anyio
async def test_cleanup_orphan_records(temp_media_dir):
    with Session(engine) as session:
        session.add(
            ScannedFile(
                path_id=999,
                file_path="orphan.mkv",
                filename="orphan.mkv",
                extracted_title="Orphan",
                type="movie",
            )
        )
        session.add(MediaPath(path=str(temp_media_dir), type="movie", enabled=True))
        session.commit()

    await MediaService.run_media_scan_and_match()

    with Session(engine) as session:
        orphan = session.exec(select(ScannedFile).where(ScannedFile.path_id == 999)).first()

    assert orphan is None


@pytest.mark.anyio
async def test_scan_rules_are_explicit_for_movie_and_tv(tmp_path):
    movie_root = tmp_path / "movies"
    movie_dir = movie_root / "Dune Part Two"
    nested_movie_dir = movie_dir / "extras"
    nested_movie_dir.mkdir(parents=True)
    movie_dir.mkdir(exist_ok=True)
    (movie_dir / "Dune.Part.Two.2024.mkv").touch()
    (nested_movie_dir / "should_skip_nested_movie.mkv").touch()

    tv_root = tmp_path / "tv"
    show_dir = tv_root / "Severance"
    season_dir = show_dir / "Season 01"
    season_dir.mkdir(parents=True)
    (season_dir / "Severance.S01E01.mkv").touch()

    with Session(engine) as session:
        session.add(MediaPath(path=str(movie_root), type="movie", enabled=True))
        session.add(MediaPath(path=str(tv_root), type="tv", enabled=True))
        session.commit()

    await MediaService.run_media_scan_and_match()

    with Session(engine) as session:
        files = session.exec(select(ScannedFile)).all()

    assert len(files) == 2
    assert all(file_record.filename != "should_skip_nested_movie.mkv" for file_record in files)

    tv_file = next(file_record for file_record in files if file_record.type == "tv")
    assert tv_file.filename == "Severance.S01E01.mkv"
    assert tv_file.series_root_path == str(show_dir.absolute())


@pytest.mark.anyio
async def test_scan_new_files_inherit_allow_no_subtitle_flag(tmp_path):
    tv_root = tmp_path / "tv"
    show_dir = tv_root / "Severance"
    show_dir.mkdir(parents=True)
    (show_dir / "Severance.S01E01.mkv").touch()
    (show_dir / "Severance.S01E02.mkv").touch()

    with Session(engine) as session:
        media_path = MediaPath(path=str(tv_root), type="tv", enabled=True)
        session.add(media_path)
        session.commit()
        session.refresh(media_path)
        session.add(
            ScannedFile(
                path_id=media_path.id,
                file_path=str(show_dir / "Severance.S01E01.mkv"),
                filename="Severance.S01E01.mkv",
                extracted_title="Severance",
                type="tv",
                season=1,
                episode=1,
                allow_no_subtitle=True,
            )
        )
        session.commit()

    await MediaService.run_media_scan_and_match("tv")

    with Session(engine) as session:
        new_file = session.exec(select(ScannedFile).where(ScannedFile.filename == "Severance.S01E02.mkv")).one()
        old_file = session.exec(select(ScannedFile).where(ScannedFile.filename == "Severance.S01E01.mkv")).one()

    assert new_file.allow_no_subtitle is True
    assert old_file.allow_no_subtitle is True


@pytest.mark.anyio
async def test_media_scan_avoids_per_file_database_lookups(tmp_path, monkeypatch):
    movie_root = tmp_path / "movies"
    movie_root.mkdir()

    for index in range(20):
        folder = movie_root / f"Movie {index:02d}"
        folder.mkdir()
        (folder / f"Movie.{index:02d}.2024.1080p.mkv").touch()

    exec_calls = 0
    original_exec = Session.exec

    def counted_exec(self, statement, *args, **kwargs):
        nonlocal exec_calls
        sql = str(statement)
        if "scannedfile" in sql.lower() and "SELECT" in sql.upper():
            exec_calls += 1
        return original_exec(self, statement, *args, **kwargs)

    monkeypatch.setattr(Session, "exec", counted_exec)

    with Session(engine) as session:
        session.add(MediaPath(path=str(movie_root), type="movie", enabled=True))
        session.commit()

    await MediaService.run_media_scan_and_match("movie")

    with Session(engine) as session:
        files = session.exec(select(ScannedFile)).all()

    assert len(files) == 20
    # 扫描主流程 4 次常量查询（含「允许无字幕」标记加载）+ 本测试自身 1 次校验查询
    assert exec_calls <= 5
