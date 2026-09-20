import logging
import os
import subprocess
import zipfile
from pathlib import Path
from typing import List, Optional

import py7zr

logger = logging.getLogger(__name__)


class ArchiveManager:
    """压缩包管理器，支持解压并修复文件名乱码"""

    SUPPORTED_ARCHIVE_EXTENSIONS = (".zip", ".7z", ".rar")

    @staticmethod
    def _resolve_safe_target(base_dir: str, relative_name: str) -> Path:
        target_root = Path(base_dir).resolve()
        target_path = (target_root / relative_name).resolve(strict=False)
        try:
            target_path.relative_to(target_root)
        except ValueError as exc:
            raise ValueError(f"Unsafe archive entry: {relative_name}") from exc
        return target_path

    @staticmethod
    def _normalize_archive_name(filename: str) -> Optional[Path]:
        normalized = Path(filename)
        safe_parts = [part for part in normalized.parts if part not in {"", "."}]
        if not safe_parts or any(part == ".." for part in safe_parts):
            return None
        return Path(*safe_parts)

    @staticmethod
    def _decode_zip_filename(filename: str) -> str:
        for encoding in ("gbk", "utf-8"):
            try:
                return filename.encode("cp437").decode(encoding)
            except Exception:
                continue
        return filename

    @staticmethod
    def _sniff_format(file_path: str) -> Optional[str]:
        """按文件头魔数识别压缩格式（站点上存在扩展名与实际格式不符的包，如 .zip 实为 RAR）。"""
        try:
            with open(file_path, "rb") as f:
                magic = f.read(8)
        except OSError:
            return None
        if magic.startswith(b"Rar!\x1a\x07"):
            return "rar"
        if magic.startswith(b"7z\xbc\xaf\x27\x1c"):
            return "7z"
        if magic[:2] == b"PK":
            return "zip"
        return None

    @staticmethod
    def extract(
        file_path: str,
        extract_to: str,
        *,
        max_files: Optional[int] = None,
        max_total_size: Optional[int] = None,
    ) -> List[str]:
        """解压文件并返回解压后的文件列表"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        os.makedirs(extract_to, exist_ok=True)

        archive_format = ArchiveManager._sniff_format(file_path)
        if archive_format is None:
            # 魔数无法识别时回退到扩展名判断（如空 ZIP 包）
            lower_path = file_path.lower()
            if lower_path.endswith(".zip"):
                archive_format = "zip"
            elif lower_path.endswith(".7z"):
                archive_format = "7z"
            elif lower_path.endswith(".rar"):
                archive_format = "rar"

        if archive_format == "zip":
            return ArchiveManager._extract_zip(file_path, extract_to, max_files, max_total_size)
        if archive_format == "7z":
            return ArchiveManager._extract_7z(file_path, extract_to, max_files, max_total_size)
        if archive_format == "rar":
            return ArchiveManager._extract_rar(file_path, extract_to, max_files, max_total_size)

        logger.warning(f"Unsupported archive format: {file_path}")
        return []

    @staticmethod
    def _extract_zip(
        file_path: str,
        extract_to: str,
        max_files: Optional[int] = None,
        max_total_size: Optional[int] = None,
    ) -> List[str]:
        extracted_files = []
        with zipfile.ZipFile(file_path, "r") as z:
            file_infos = [info for info in z.infolist() if not info.is_dir()]
            if max_files is not None and len(file_infos) > max_files:
                raise ValueError(f"Archive contains too many files: {len(file_infos)} > {max_files}")
            if max_total_size is not None:
                total_size = sum(info.file_size for info in file_infos)
                if total_size > max_total_size:
                    raise ValueError(f"Archive is too large after extraction: {total_size} > {max_total_size}")

            extracted_size = 0
            for info in file_infos:
                filename = ArchiveManager._decode_zip_filename(info.filename)
                relative_name = ArchiveManager._normalize_archive_name(filename)
                if relative_name is None:
                    continue

                target_path = ArchiveManager._resolve_safe_target(extract_to, str(relative_name))
                target_path.parent.mkdir(parents=True, exist_ok=True)
                content = z.read(info.filename)
                extracted_size += len(content)
                if max_total_size is not None and extracted_size > max_total_size:
                    raise ValueError(f"Archive is too large after extraction: {extracted_size} > {max_total_size}")
                with open(target_path, "wb") as f:
                    f.write(content)

                extracted_files.append(str(target_path))
                logger.info(f"Extracted: {relative_name}")

        return extracted_files

    @staticmethod
    def _extract_7z(
        file_path: str,
        extract_to: str,
        max_files: Optional[int] = None,
        max_total_size: Optional[int] = None,
    ) -> List[str]:
        extracted_files = []
        with py7zr.SevenZipFile(file_path, mode="r") as sz:
            archive_entries = sz.list()
            names = [entry.filename for entry in archive_entries]
            file_entries = [entry for entry in archive_entries if not entry.is_directory]
            if any(entry.is_symlink for entry in file_entries):
                raise ValueError("Archive contains unsupported symbolic links")
            if max_files is not None and len(file_entries) > max_files:
                raise ValueError(f"Archive contains too many files: {len(file_entries)} > {max_files}")
            if max_total_size is not None:
                total_size = sum(entry.uncompressed for entry in file_entries)
                if total_size > max_total_size:
                    raise ValueError(f"Archive is too large after extraction: {total_size} > {max_total_size}")
            for name in names:
                relative_name = ArchiveManager._normalize_archive_name(name)
                if relative_name is None:
                    raise ValueError(f"Unsafe archive entry: {name}")
                ArchiveManager._resolve_safe_target(extract_to, str(relative_name))

            sz.extractall(path=extract_to)
            # 7z 通常使用 UTF-16 编码，乱码较少，但我们仍记录文件
            extracted_size = 0
            for name in names:
                full_path = ArchiveManager._resolve_safe_target(extract_to, name)
                if os.path.isfile(full_path):
                    extracted_size += os.path.getsize(full_path)
                    if max_total_size is not None and extracted_size > max_total_size:
                        raise ValueError(f"Archive is too large after extraction: {extracted_size} > {max_total_size}")
                    extracted_files.append(str(full_path))
                    logger.info(f"Extracted (7z): {name}")

        return extracted_files

    @staticmethod
    def _extract_rar(
        file_path: str,
        extract_to: str,
        max_files: Optional[int] = None,
        max_total_size: Optional[int] = None,
    ) -> List[str]:
        # rarfile 库对 7zz/bsdtar 后端的输出解析在此场景不可靠，直接调用 bsdtar（libarchive）解压；
        # 先列出条目做路径安全校验，再整体解压
        list_proc = subprocess.run(["bsdtar", "-tf", file_path], capture_output=True, text=True)
        if list_proc.returncode != 0:
            raise ValueError(f"Failed to list RAR archive: {list_proc.stderr.strip()}")

        names = [line.strip() for line in list_proc.stdout.splitlines() if line.strip()]
        file_names = [name for name in names if not name.endswith("/")]
        if max_files is not None and len(file_names) > max_files:
            raise ValueError(f"Archive contains too many files: {len(file_names)} > {max_files}")

        for name in names:
            relative_name = ArchiveManager._normalize_archive_name(name)
            if relative_name is None:
                raise ValueError(f"Unsafe archive entry: {name}")
            ArchiveManager._resolve_safe_target(extract_to, str(relative_name))

        extract_proc = subprocess.run(["bsdtar", "-xf", file_path, "-C", extract_to], capture_output=True, text=True)
        if extract_proc.returncode != 0:
            raise ValueError(f"Failed to extract RAR archive: {extract_proc.stderr.strip()}")

        extracted_files = []
        extracted_size = 0
        for name in file_names:
            full_path = ArchiveManager._resolve_safe_target(extract_to, name)
            if os.path.isfile(full_path):
                extracted_size += os.path.getsize(full_path)
                if max_total_size is not None and extracted_size > max_total_size:
                    raise ValueError(f"Archive is too large after extraction: {extracted_size} > {max_total_size}")
                extracted_files.append(str(full_path))
                logger.info(f"Extracted (rar): {name}")

        return extracted_files

    @staticmethod
    def is_archive(file_path: str) -> bool:
        """判断是否为支持的压缩包格式"""
        return file_path.lower().endswith(ArchiveManager.SUPPORTED_ARCHIVE_EXTENSIONS)
