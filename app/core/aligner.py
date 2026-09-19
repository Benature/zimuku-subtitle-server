import asyncio
import logging
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from .config import get_temp_path
from .subtitle_detector import SubtitleDetector

logger = logging.getLogger(__name__)


class SubtitleAlignError(ValueError):
    """字幕音轨对齐失败异常。"""


@dataclass(frozen=True)
class AlignerStatus:
    available: bool
    engine: Optional[str]
    ffmpeg_available: bool
    alass_path: Optional[str]
    ffsubsync_path: Optional[str]
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SubtitleAligner:
    """字幕音轨对齐核心引擎。"""

    SUPPORTED_SUBTITLE_FORMATS = {".srt", ".ass", ".ssa"}

    @classmethod
    def find_executable(cls, name: str, custom_path_env: Optional[str] = None) -> Optional[str]:
        if custom_path_env:
            custom_path = os.environ.get(custom_path_env)
            if custom_path and Path(custom_path).is_file() and os.access(custom_path, os.X_OK):
                return custom_path

        # 检查常规 PATH
        found = shutil.which(name)
        if found:
            return found

        # 额外针对容器和常见路径进行探测
        common_locations = [
            Path("/usr/local/bin") / name,
            Path("/usr/bin") / name,
            Path("/bin") / name,
        ]
        for loc in common_locations:
            if loc.is_file() and os.access(loc, os.X_OK):
                return str(loc)

        return None

    @classmethod
    def get_status(cls) -> AlignerStatus:
        ffmpeg_path = cls.find_executable("ffmpeg", "ZIMUKU_FFMPEG_PATH")
        alass_path = cls.find_executable("alass", "ZIMUKU_ALASS_PATH")
        ffsubsync_path = cls.find_executable("ffsubsync", "ZIMUKU_FFSUBSYNC_PATH")

        ffmpeg_ok = ffmpeg_path is not None
        engine = None
        if alass_path:
            engine = "alass"
        elif ffsubsync_path:
            engine = "ffsubsync"

        available = ffmpeg_ok and (engine is not None)

        if not ffmpeg_ok and engine is None:
            msg = "系统未检测到 ffmpeg 以及对齐工具 (alass 或 ffsubsync)"
        elif not ffmpeg_ok:
            msg = "系统未检测到 ffmpeg，无法提取视频音轨"
        elif engine is None:
            msg = "系统未检测到字幕对齐工具 (alass 或 ffsubsync)"
        else:
            msg = f"音轨对齐工具已就绪 (引擎: {engine})"

        return AlignerStatus(
            available=available,
            engine=engine,
            ffmpeg_available=ffmpeg_ok,
            alass_path=alass_path,
            ffsubsync_path=ffsubsync_path,
            message=msg,
        )

    @classmethod
    async def align(
        cls,
        reference_path: Path,
        subtitle_path: Path,
        output_path: Path,
        split_penalty: float = 7.0,
        timeout_seconds: int = 180,
    ) -> None:
        """调用底层引擎将字幕文件与音轨进行时间轴对齐。

        :param reference_path: 视频文件或基准字幕文件路径
        :param subtitle_path: 待调整的源字幕文件路径
        :param output_path: 输出调整后的目标字幕文件路径
        :param split_penalty: alass 拆分惩罚系数（默认 7.0）
        :param timeout_seconds: 最大超时时间（秒）
        """
        status = cls.get_status()
        if not status.available or not status.engine:
            raise SubtitleAlignError(f"音轨对齐不可用: {status.message}")

        if not reference_path.exists() or reference_path.stat().st_size == 0:
            raise SubtitleAlignError(f"参考视频文件不存在或为空: {reference_path}")

        if not subtitle_path.exists() or subtitle_path.stat().st_size == 0:
            raise SubtitleAlignError(f"待对齐字幕文件不存在或为空: {subtitle_path}")

        sub_ext = subtitle_path.suffix.lower()
        if sub_ext not in cls.SUPPORTED_SUBTITLE_FORMATS:
            raise SubtitleAlignError(
                f"不支持对齐格式为 '{sub_ext}' 的字幕文件。仅支持: {', '.join(sorted(cls.SUPPORTED_SUBTITLE_FORMATS))}"
            )

        temp_dir = Path(get_temp_path()) / "align"
        temp_dir.mkdir(parents=True, exist_ok=True)

        # 编码标准化为 UTF-8，避免因非标准编码导致底层对齐工具失败
        raw_bytes = subtitle_path.read_bytes()
        try:
            text_content, _ = SubtitleDetector.decode_subtitle_bytes(raw_bytes)
        except Exception as exc:
            raise SubtitleAlignError(f"解析待对齐字幕编码失败: {exc}") from exc

        temp_input = temp_dir / f"input_{os.getpid()}_{subtitle_path.name}"
        temp_output = temp_dir / f"output_{os.getpid()}_{subtitle_path.name}"

        try:
            temp_input.write_text(text_content, encoding="utf-8")

            if status.engine == "alass":
                await cls._run_alass(
                    alass_bin=status.alass_path or "alass",
                    reference_path=reference_path,
                    input_sub_path=temp_input,
                    output_sub_path=temp_output,
                    split_penalty=split_penalty,
                    timeout_seconds=timeout_seconds,
                )
            else:
                await cls._run_ffsubsync(
                    ffsubsync_bin=status.ffsubsync_path or "ffsubsync",
                    reference_path=reference_path,
                    input_sub_path=temp_input,
                    output_sub_path=temp_output,
                    timeout_seconds=timeout_seconds,
                )

            if not temp_output.exists() or temp_output.stat().st_size == 0:
                raise SubtitleAlignError("对齐工具未生成有效输出文件")

            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(temp_output), str(output_path))
            logger.info("Successfully aligned subtitle %s -> %s", subtitle_path, output_path)

        finally:
            if temp_input.exists():
                temp_input.unlink(missing_ok=True)
            if temp_output.exists():
                temp_output.unlink(missing_ok=True)

    @classmethod
    async def _run_alass(
        cls,
        alass_bin: str,
        reference_path: Path,
        input_sub_path: Path,
        output_sub_path: Path,
        split_penalty: float,
        timeout_seconds: int,
    ) -> None:
        cmd = [
            alass_bin,
            str(reference_path),
            str(input_sub_path),
            str(output_sub_path),
            "-p",
            str(split_penalty),
        ]
        logger.info("Running alass command: %s", " ".join(cmd))

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        except asyncio.TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise SubtitleAlignError(f"音轨对齐超时（超过 {timeout_seconds} 秒）") from exc

        if proc.returncode != 0:
            err_msg = stderr.decode("utf-8", errors="replace").strip()
            out_msg = stdout.decode("utf-8", errors="replace").strip()
            detail = err_msg or out_msg or f"退出码: {proc.returncode}"
            logger.error("alass failed with exit code %s: %s", proc.returncode, detail)
            raise SubtitleAlignError(f"对齐算法执行失败: {detail}")

    @classmethod
    async def _run_ffsubsync(
        cls,
        ffsubsync_bin: str,
        reference_path: Path,
        input_sub_path: Path,
        output_sub_path: Path,
        timeout_seconds: int,
    ) -> None:
        cmd = [
            ffsubsync_bin,
            str(reference_path),
            "-i",
            str(input_sub_path),
            "-o",
            str(output_sub_path),
        ]
        logger.info("Running ffsubsync command: %s", " ".join(cmd))

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        except asyncio.TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise SubtitleAlignError(f"音轨对齐超时（超过 {timeout_seconds} 秒）") from exc

        if proc.returncode != 0:
            err_msg = stderr.decode("utf-8", errors="replace").strip()
            out_msg = stdout.decode("utf-8", errors="replace").strip()
            detail = err_msg or out_msg or f"退出码: {proc.returncode}"
            logger.error("ffsubsync failed with exit code %s: %s", proc.returncode, detail)
            raise SubtitleAlignError(f"对齐算法执行失败: {detail}")
