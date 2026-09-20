import os
import shutil
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.archive import ArchiveManager


def test_zip_extraction_with_encoding():
    # 准备测试环境
    test_dir = "tests/tmp_archive"
    extract_to = "tests/tmp_extracted"
    os.makedirs(test_dir, exist_ok=True)
    if os.path.exists(extract_to):
        shutil.rmtree(extract_to)

    zip_path = os.path.join(test_dir, "test.zip")

    # 创建一个包含中文文件名的 ZIP
    # 在 Windows 上，zipfile 默认可能使用 cp437 编码存储文件名
    # 我们模拟这种情况
    chinese_filename = "测试字幕文件.srt"

    with zipfile.ZipFile(zip_path, "w") as z:
        # 模拟 cp437 编码的文件名写入 (这是 Zimuku 常见的乱码来源)
        # 注意：现代 zipfile 在某些情况下会自动处理，我们尽量模拟原始字节
        z.writestr(chinese_filename.encode("gbk").decode("cp437"), "subtitle content")

    # 使用 ArchiveManager 解压
    files = ArchiveManager.extract(zip_path, extract_to)

    assert len(files) > 0
    # 检查解压后的文件名是否正确修复
    expected_path = os.path.join(extract_to, chinese_filename)
    assert os.path.exists(expected_path)
    print(f"成功验证解压乱码修复: {chinese_filename}")

    # 清理
    shutil.rmtree(test_dir)
    shutil.rmtree(extract_to)


def test_zip_extraction_preserves_safe_nested_paths(tmp_path):
    archive_path = tmp_path / "nested.zip"
    extract_to = tmp_path / "out"

    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("Season 01/episode.srt", "subtitle content")

    files = ArchiveManager.extract(str(archive_path), str(extract_to))

    expected_path = extract_to / "Season 01" / "episode.srt"
    assert files == [str(expected_path.resolve())]
    assert expected_path.exists()


def test_archive_manager_recognizes_supported_extensions():
    assert ArchiveManager.is_archive("subtitle.zip")
    assert ArchiveManager.is_archive("subtitle.7z")
    assert ArchiveManager.is_archive("subtitle.rar")
    assert not ArchiveManager.is_archive("subtitle.tar.gz")


def _fake_bsdtar_run(monkeypatch, names: list[str]):
    """模拟 bsdtar：-tf 返回条目列表，-xf 在目标目录创建对应文件。"""

    def fake_run(cmd, capture_output=False, text=False):
        if cmd[1] == "-tf":
            return SimpleNamespace(returncode=0, stdout="\n".join(names) + "\n", stderr="")
        if cmd[1] == "-xf":
            target_dir = Path(cmd[cmd.index("-C") + 1])
            for name in names:
                if name.endswith("/"):
                    continue
                file_path = target_dir / name
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text("srt!", encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr("app.core.archive.manager.subprocess.run", fake_run)


def test_extract_dispatches_by_magic_bytes_for_mislabeled_rar(monkeypatch, tmp_path):
    """扩展名为 .zip 但内容实为 RAR 的包，应按魔数识别走 RAR 解压。"""
    archive_path = tmp_path / "mislabeled.zip"
    archive_path.write_bytes(b"Rar!\x1a\x07\x00\xcf" + b"\x00" * 32)
    extract_to = tmp_path / "out"
    _fake_bsdtar_run(monkeypatch, ["episode.srt"])

    files = ArchiveManager.extract(str(archive_path), str(extract_to))

    assert files == [str((extract_to / "episode.srt").resolve())]
    assert (extract_to / "episode.srt").exists()


def test_extract_rar_extracts_entries(monkeypatch, tmp_path):
    archive_path = tmp_path / "pack.rar"
    archive_path.write_bytes(b"fake")
    extract_to = tmp_path / "out"
    _fake_bsdtar_run(monkeypatch, ["Season 04/摩登家庭S04E01.srt"])

    files = ArchiveManager.extract(str(archive_path), str(extract_to))

    expected_path = extract_to / "Season 04" / "摩登家庭S04E01.srt"
    assert files == [str(expected_path.resolve())]
    assert expected_path.exists()


def test_extract_rar_rejects_path_traversal(monkeypatch, tmp_path):
    archive_path = tmp_path / "unsafe.rar"
    archive_path.write_bytes(b"fake")
    _fake_bsdtar_run(monkeypatch, ["../../etc/passwd"])

    with pytest.raises(ValueError, match="Unsafe archive entry"):
        ArchiveManager.extract(str(archive_path), str(tmp_path / "out"))


def test_extract_rar_enforces_resource_limits(monkeypatch, tmp_path):
    archive_path = tmp_path / "large.rar"
    archive_path.write_bytes(b"fake")
    _fake_bsdtar_run(monkeypatch, ["a.srt", "b.srt"])

    with pytest.raises(ValueError, match="too many files"):
        ArchiveManager.extract(str(archive_path), str(tmp_path / "files"), max_files=1)

    with pytest.raises(ValueError, match="too large"):
        ArchiveManager.extract(str(archive_path), str(tmp_path / "size"), max_total_size=7)


def test_extract_zip_rejects_path_traversal(monkeypatch, tmp_path):
    archive_path = tmp_path / "unsafe.zip"
    archive_path.write_bytes(b"fake")
    extract_to = tmp_path / "out"

    class FakeZipInfo:
        filename = "../../etc/passwd"

        @staticmethod
        def is_dir():
            return False

    class FakeZipFile:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def infolist(self):
            return [FakeZipInfo()]

        def read(self, _name):
            return b"content"

    monkeypatch.setattr("app.core.archive.manager.zipfile.ZipFile", FakeZipFile)

    files = ArchiveManager.extract(str(archive_path), str(extract_to))

    assert files == []
    assert not list(Path(extract_to).rglob("*"))


def test_extract_zip_enforces_resource_limits(tmp_path):
    archive_path = tmp_path / "large.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("a.srt", "1234")
        archive.writestr("b.srt", "5678")

    with pytest.raises(ValueError, match="too many files"):
        ArchiveManager.extract(str(archive_path), str(tmp_path / "files"), max_files=1)

    with pytest.raises(ValueError, match="too large"):
        ArchiveManager.extract(str(archive_path), str(tmp_path / "size"), max_total_size=7)


if __name__ == "__main__":
    test_zip_extraction_with_encoding()
