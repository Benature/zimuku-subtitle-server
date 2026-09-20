import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app.api.system import get_subtitle_languages
from app.db.models import MediaPath, ScannedFile, SubtitleTask
from app.db.session import create_db_and_tables, engine
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    create_db_and_tables()
    # 清空数据以保证测试独立性
    with Session(engine) as session:
        session.exec(delete(SubtitleTask))
        session.exec(delete(MediaPath))
        session.commit()


def test_media_paths_api():
    # 1. 添加路径
    response = client.post("/media/paths", params={"path": "F:/movies", "path_type": "movie"})
    assert response.status_code == 200
    data = response.json()
    assert data["path"] == "F:/movies"
    assert data["type"] == "movie"
    path_id = data["id"]

    # 重复添加应报错
    response = client.post("/media/paths", params={"path": "F:/movies", "path_type": "movie"})
    assert response.status_code == 409

    # 2. 列出路径
    response = client.get("/media/paths")
    assert response.status_code == 200
    assert len(response.json()) >= 1

    # 3. 更新路径
    response = client.patch(f"/media/paths/{path_id}", params={"enabled": False})
    assert response.status_code == 200
    assert response.json()["enabled"] is False

    # 4. 删除路径
    # 先加一个文件关联到此路径
    with Session(engine) as session:
        session.add(ScannedFile(path_id=path_id, file_path="F:/movies/m1.mkv", filename="m1.mkv", type="movie"))
        session.commit()

    response = client.delete(f"/media/paths/{path_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    # 验证 ScannedFile 是否也被删除
    with Session(engine) as session:
        from sqlmodel import select

        res = session.exec(select(ScannedFile).where(ScannedFile.path_id == path_id)).first()
        assert res is None


def test_system_stats_api():
    # 准备一些数据
    with Session(engine) as session:
        session.add(SubtitleTask(title="T1", source_url="url1", status="completed"))
        session.add(SubtitleTask(title="T2", source_url="url2", status="failed"))
        session.commit()

    response = client.get("/system/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["tasks"]["completed"] == 1
    assert data["tasks"]["failed"] == 1
    assert "storage" in data


@pytest.mark.anyio
async def test_subtitle_languages_api():
    assert await get_subtitle_languages() == [
        {"code": "zh-CN", "display_name": "简体中文", "filename_tag": "zh-CN"},
        {"code": "zh-TW", "display_name": "繁体中文", "filename_tag": "zh-TW"},
        {"code": "en", "display_name": "英语", "filename_tag": "en"},
        {"code": "zh-CN-en", "display_name": "简英双语", "filename_tag": "zh-CN-en"},
    ]


def test_get_logs_api(tmp_path, monkeypatch):
    # 模拟日志文件
    log_file = tmp_path / "app.log"
    monkeypatch.setenv("ZIMUKU_LOG_FILE", str(log_file))

    with open(log_file, "w", encoding="utf-8") as f:
        f.write("Line 1\nLine 2\nLine 3\n")

    response = client.get("/system/logs", params={"lines": 2})
    assert response.status_code == 200
    logs = response.json()
    assert len(logs) == 2
    assert logs[-1].strip() == "Line 3"


def test_trigger_match_api():
    response = client.post("/media/match")
    assert response.status_code == 200
    assert "started" in response.json()["message"]
    assert response.json()["task_kind"] == "media_scan"


def test_media_task_status_api():
    response = client.get("/media/task-status")
    assert response.status_code == 200
    data = response.json()
    assert "is_scanning" in data
    assert "matching_files" in data
    assert "matching_seasons" in data


def test_media_library_api_returns_aggregated_show_results():
    with Session(engine) as session:
        media_path = MediaPath(path="/library-api-tv", type="tv", enabled=True)
        session.add(media_path)
        session.commit()
        session.refresh(media_path)
        session.add_all(
            [
                ScannedFile(
                    path_id=media_path.id,
                    type="tv",
                    file_path="/library-api-tv/Andor/S01E01.mkv",
                    filename="Andor.S01E01.mkv",
                    extracted_title="Andor",
                    nfo_title="安多",
                    nfo_original_title="Andor",
                    nfo_aliases='["星球大战：安多"]',
                    season=1,
                    episode=1,
                ),
                ScannedFile(
                    path_id=media_path.id,
                    type="tv",
                    file_path="/library-api-tv/Andor/S01E02.mkv",
                    filename="Andor.S01E02.mkv",
                    extracted_title="Andor",
                    season=1,
                    episode=2,
                    has_subtitle=True,
                ),
            ]
        )
        session.commit()

    response = client.get("/media/library", params={"level": "show", "query": "安多"})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "Andor"
    assert data["items"][0]["file_count"] == 2
    assert data["items"][0]["missing_subtitle_file_count"] == 1
    assert data["items"][0]["nfo_aliases"] == ["星球大战：安多"]


def test_media_metadata_api_moves_resolution_to_service(tmp_path):
    movie_dir = tmp_path / "Movie Title"
    movie_dir.mkdir(parents=True)
    video_path = movie_dir / "Movie.Title.2024.mkv"
    video_path.write_text("video", encoding="utf-8")
    (movie_dir / "movie.nfo").write_text(
        "<movie><title>Movie Title</title><year>2024</year></movie>",
        encoding="utf-8",
    )
    (movie_dir / "folder.jpg").write_text("image", encoding="utf-8")

    with Session(engine) as session:
        media_path = MediaPath(path=str(tmp_path), type="movie", enabled=True)
        session.add(media_path)
        session.commit()
        session.refresh(media_path)

        scanned_file = ScannedFile(
            path_id=media_path.id,
            file_path=str(video_path),
            filename=video_path.name,
            type="movie",
        )
        session.add(scanned_file)
        session.commit()
        session.refresh(scanned_file)
        file_id = scanned_file.id

    response = client.get(f"/media/metadata/{file_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["file_id"] == file_id
    assert data["filename"] == video_path.name
    assert data["nfo_data"]["title"] == "Movie Title"
    assert data["poster_path"] == f"{movie_dir.name}/folder.jpg"


def test_set_work_allow_no_subtitle_api():
    with Session(engine) as session:
        media_path = MediaPath(path="/library-api-movies", type="movie", enabled=True)
        session.add(media_path)
        session.commit()
        session.refresh(media_path)
        session.add(
            ScannedFile(
                path_id=media_path.id,
                type="movie",
                file_path="/library-api-movies/Silent/Silent.2024.mkv",
                filename="Silent.2024.mkv",
                extracted_title="Silent",
            )
        )
        session.commit()

    response = client.post(
        "/media/works/allow-no-subtitle",
        json={"media_type": "movie", "title": "Silent", "allow": True},
    )
    assert response.status_code == 200
    assert "Silent" in response.json()["message"]

    with Session(engine) as session:
        from sqlmodel import select

        scanned = session.exec(select(ScannedFile).where(ScannedFile.extracted_title == "Silent")).one()
        assert scanned.allow_no_subtitle is True

    # 未知作品返回 404
    response = client.post(
        "/media/works/allow-no-subtitle",
        json={"media_type": "movie", "title": "Ghost", "allow": True},
    )
    assert response.status_code == 404
