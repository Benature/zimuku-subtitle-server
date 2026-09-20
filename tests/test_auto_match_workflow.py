from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel import Session, delete

from app.db.models import MediaPath, ScannedFile, SubtitleTask
from app.db.session import create_db_and_tables, engine, session_scope
from app.services.auto_match_workflow import (
    AutoMatchWorkflow,
    LibraryMatchWorkflow,
    SeasonMatchWorkflow,
    SubtitleCandidateScorer,
)


@pytest.fixture(autouse=True)
def clean_app_db():
    create_db_and_tables()
    with Session(engine) as session:
        session.exec(delete(ScannedFile))
        session.exec(delete(MediaPath))
        session.exec(delete(SubtitleTask))
        session.commit()


def test_subtitle_candidate_scorer_prefers_matching_episode_and_chs():
    wrong_episode = Path("Show.S01E01.ass")
    best_match = Path("Show.S01E02.chs.ass")

    wrong_score = SubtitleCandidateScorer.score(wrong_episode, season=1, episode=2)
    best_score = SubtitleCandidateScorer.score(best_match, season=1, episode=2)

    assert best_score > wrong_score


@pytest.mark.anyio
async def test_auto_match_retries_until_top_five_candidates(monkeypatch, tmp_path):
    video_path = tmp_path / "Show" / "Show.S01E02.mkv"
    video_path.parent.mkdir(parents=True)
    video_path.write_text("video", encoding="utf-8")

    scanned_file = ScannedFile(
        path_id=1,
        type="tv",
        file_path=str(video_path),
        filename=video_path.name,
        extracted_title="Show",
        season=1,
        episode=2,
    )
    with Session(engine) as session:
        session.add(scanned_file)
        session.commit()
        session.refresh(scanned_file)

    search_results = [SimpleNamespace(link=f"http://example.com/{index}") for index in range(6)]
    requested_links = []

    async def fake_links(link: str):
        requested_links.append(link)
        return [f"{link}.zip"]

    async def fake_download(_links, link: str):
        if link.endswith("/4"):
            return "Show.S01E02.chs.ass", b"subtitle"
        return "invalid.bin", b"not a subtitle"

    agent = SimpleNamespace(
        search=AsyncMock(return_value=search_results),
        get_download_page_links=AsyncMock(side_effect=fake_links),
        download_file=AsyncMock(side_effect=fake_download),
        close=AsyncMock(return_value=None),
    )

    monkeypatch.setattr("app.services.auto_match_workflow.ZimukuAgent", lambda: agent)
    monkeypatch.setattr("app.services.auto_match_workflow.get_temp_path", lambda: str(tmp_path / "storage" / "tmp"))

    service = AutoMatchWorkflow(session_factory=session_scope)
    matched = await service.run_for_file(scanned_file.id)

    assert matched is True
    assert requested_links == [f"http://example.com/{index}" for index in range(5)]
    assert (video_path.parent / "Show.S01E02.ass").exists()


@pytest.mark.anyio
async def test_season_match_service_runs_sequentially_with_throttle():
    with Session(engine) as session:
        first_file = ScannedFile(
            path_id=1,
            type="tv",
            file_path="/library/Show.S01E01.mkv",
            filename="Show.S01E01.mkv",
            extracted_title="Show",
            season=1,
            episode=1,
            has_subtitle=False,
        )
        second_file = ScannedFile(
            path_id=1,
            type="tv",
            file_path="/library/Show.S01E02.mkv",
            filename="Show.S01E02.mkv",
            extracted_title="Show (2024)",
            season=1,
            episode=2,
            has_subtitle=False,
        )
        session.add_all([first_file, second_file])
        session.commit()
        session.refresh(first_file)
        session.refresh(second_file)

    calls = []

    async def fake_auto_match(file_id: int):
        calls.append(("match", file_id))
        return True

    async def fake_sleep(seconds: float):
        calls.append(("sleep", seconds))

    service = SeasonMatchWorkflow(
        session_factory=session_scope,
        auto_match_runner=fake_auto_match,
        sleep_func=fake_sleep,
    )

    await service.run_for_season("Show (2024)", 1)

    assert calls == [
        ("match", first_file.id),
        ("sleep", 2),
        ("match", second_file.id),
        ("sleep", 2),
    ]


def _add_scanned_file(session, filename: str, has_subtitle: bool) -> ScannedFile:
    record = ScannedFile(
        path_id=1,
        type="movie",
        file_path=f"/library/{filename}",
        filename=filename,
        extracted_title="Movie",
        has_subtitle=has_subtitle,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


@pytest.mark.anyio
async def test_library_match_only_processes_files_without_subtitle():
    with Session(engine) as session:
        pending_id = _add_scanned_file(session, "Pending.mkv", has_subtitle=False).id
        _add_scanned_file(session, "Done.mkv", has_subtitle=True)

    calls = []

    async def fake_auto_match(file_id: int):
        calls.append(("match", file_id))
        return file_id == pending_id

    async def fake_sleep(seconds: float):
        calls.append(("sleep", seconds))

    service = LibraryMatchWorkflow(
        session_factory=session_scope,
        auto_match_runner=fake_auto_match,
        sleep_func=fake_sleep,
    )

    stats = await service.run()

    assert calls == [("match", pending_id), ("sleep", 2)]
    assert stats.total == 1
    assert stats.matched == 1
    assert stats.failed_files == []


@pytest.mark.anyio
async def test_library_match_collects_failures():
    with Session(engine) as session:
        _add_scanned_file(session, "FailOne.mkv", has_subtitle=False)
        _add_scanned_file(session, "FailTwo.mkv", has_subtitle=False)

    async def fake_auto_match(file_id: int):
        return False

    async def fake_sleep(seconds: float):
        return None

    service = LibraryMatchWorkflow(
        session_factory=session_scope,
        auto_match_runner=fake_auto_match,
        sleep_func=fake_sleep,
    )

    stats = await service.run()

    assert stats.total == 2
    assert stats.matched == 0
    assert stats.failed == 2
    assert set(stats.failed_files) == {"FailOne.mkv", "FailTwo.mkv"}


def _add_pending(session, title: str, filename: str, media_type: str = "tv") -> None:
    session.add(
        ScannedFile(
            path_id=1,
            type=media_type,
            file_path=f"/library/{filename}",
            filename=filename,
            extracted_title=title,
            has_subtitle=False,
        )
    )
    session.commit()


@pytest.mark.anyio
async def test_library_match_respects_max_works_and_prefers_largest_gap():
    with Session(engine) as session:
        for index in range(3):
            _add_pending(session, "Big Show (2024)", f"BigShow.S01E0{index}.mkv")
        _add_pending(session, "Small Show", "SmallShow.S01E01.mkv")
        _add_pending(session, "Some Movie", "SomeMovie.2024.mkv", media_type="movie")

    matched_ids = []

    async def fake_auto_match(file_id: int):
        matched_ids.append(file_id)
        return True

    async def fake_sleep(seconds: float):
        return None

    service = LibraryMatchWorkflow(
        session_factory=session_scope,
        auto_match_runner=fake_auto_match,
        sleep_func=fake_sleep,
        max_works=1,
    )

    stats = await service.run()

    # 只补缺口最大的一部剧（3 集），且 "Big Show (2024)" 被归一化为 "Big Show"
    assert stats.titles == ["Big Show"]
    assert stats.total == 3
    assert stats.matched == 3
    assert stats.remaining_works == 2
    assert len(matched_ids) == 3


@pytest.mark.anyio
async def test_library_match_max_works_zero_processes_all():
    with Session(engine) as session:
        _add_pending(session, "Show A", "ShowA.S01E01.mkv")
        _add_pending(session, "Movie B", "MovieB.2024.mkv", media_type="movie")

    async def fake_auto_match(file_id: int):
        return True

    async def fake_sleep(seconds: float):
        return None

    service = LibraryMatchWorkflow(
        session_factory=session_scope,
        auto_match_runner=fake_auto_match,
        sleep_func=fake_sleep,
        max_works=0,
    )

    stats = await service.run()

    assert sorted(stats.titles) == ["Movie B", "Show A"]
    assert stats.total == 2
    assert stats.remaining_works == 0


@pytest.mark.anyio
async def test_library_match_skips_works_allowing_no_subtitle():
    with Session(engine) as session:
        _add_pending(session, "Show A", "ShowA.S01E01.mkv")
        flagged = ScannedFile(
            path_id=1,
            type="movie",
            file_path="/library/Silent.2024.mkv",
            filename="Silent.2024.mkv",
            extracted_title="Silent Movie",
            has_subtitle=False,
            allow_no_subtitle=True,
        )
        session.add(flagged)
        session.commit()
        session.refresh(flagged)
        flagged_id = flagged.id

    matched_ids = []

    async def fake_auto_match(file_id: int):
        matched_ids.append(file_id)
        return True

    async def fake_sleep(seconds: float):
        return None

    service = LibraryMatchWorkflow(
        session_factory=session_scope,
        auto_match_runner=fake_auto_match,
        sleep_func=fake_sleep,
    )

    stats = await service.run()

    assert stats.titles == ["Show A"]
    assert stats.total == 1
    assert flagged_id not in matched_ids


@pytest.mark.anyio
async def test_season_match_skips_files_allowing_no_subtitle():
    with Session(engine) as session:
        pending = ScannedFile(
            path_id=1,
            type="tv",
            file_path="/library/Show.S01E01.mkv",
            filename="Show.S01E01.mkv",
            extracted_title="Show",
            season=1,
            episode=1,
            has_subtitle=False,
        )
        flagged = ScannedFile(
            path_id=1,
            type="tv",
            file_path="/library/Show.S01E02.mkv",
            filename="Show.S01E02.mkv",
            extracted_title="Show",
            season=1,
            episode=2,
            has_subtitle=False,
            allow_no_subtitle=True,
        )
        session.add_all([pending, flagged])
        session.commit()
        session.refresh(pending)

    calls = []

    async def fake_auto_match(file_id: int):
        calls.append(file_id)
        return True

    async def fake_sleep(seconds: float):
        return None

    service = SeasonMatchWorkflow(
        session_factory=session_scope,
        auto_match_runner=fake_auto_match,
        sleep_func=fake_sleep,
    )

    await service.run_for_season("Show", 1)

    assert calls == [pending.id]
