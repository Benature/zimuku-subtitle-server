import asyncio
import logging
import os
import re
import shutil
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from .config import get_temp_path
from .subtitle_detector import SubtitleDetector

logger = logging.getLogger(__name__)

# SRT: 00:00:01,000 --> 00:00:03,000（小时段兼容 1-2 位数字，如 0:01:58,774）
_SRT_TIME_PATTERN = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})")
# ASS/SSA: Dialogue: 0,0:00:01.00,0:00:03.00,...
_ASS_DIALOGUE_PATTERN = re.compile(r"^\s*Dialogue\s*:\s*\d+\s*,\s*(\d+):(\d{2}):(\d{2})\.(\d{2})\s*,", re.MULTILINE)


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


@dataclass(frozen=True)
class AlignmentCheckResult:
    """字幕与音轨对齐状态的判定结果。"""

    aligned: bool
    checked_cues: int
    max_shift_ms: float
    mean_shift_ms: float
    threshold_ms: float
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

        run_token = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
        # 临时文件统一使用小写扩展名（alass 对扩展名大小写敏感，.SRT 会被拒绝）
        temp_input = temp_dir / f"input_{run_token}{sub_ext}"
        temp_output = temp_dir / f"output_{run_token}{sub_ext}"

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
    async def check_alignment(
        cls,
        reference_path: Path,
        subtitle_path: Path,
        threshold_ms: float = 100.0,
        split_penalty: float = 7.0,
        timeout_seconds: int = 180,
    ) -> AlignmentCheckResult:
        """检查字幕与音轨是否已对齐。

        通过将字幕对齐到临时副本并比对原始/对齐后各条对白的起始时间偏移量，
        若最大偏移量不超过阈值（默认 100ms）则判定为已对齐。
        不修改原始字幕文件。
        """
        temp_dir = Path(get_temp_path()) / "align"
        temp_dir.mkdir(parents=True, exist_ok=True)
        run_token = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
        temp_output = temp_dir / f"check_{run_token}{subtitle_path.suffix.lower()}"

        try:
            await cls.align(
                reference_path=reference_path,
                subtitle_path=subtitle_path,
                output_path=temp_output,
                split_penalty=split_penalty,
                timeout_seconds=timeout_seconds,
            )

            original_starts = cls.extract_start_times(subtitle_path)
            aligned_starts = cls.extract_start_times(temp_output)
        finally:
            temp_output.unlink(missing_ok=True)

        if not original_starts or not aligned_starts:
            raise SubtitleAlignError("字幕中未解析到有效的对白时间戳，无法执行对齐检查")

        pair_count = min(len(original_starts), len(aligned_starts))
        shifts = [abs(aligned_starts[i] - original_starts[i]) for i in range(pair_count)]
        max_shift = max(shifts)
        mean_shift = sum(shifts) / len(shifts)
        aligned = max_shift <= threshold_ms

        if aligned:
            message = f"字幕与音轨已对齐（最大偏移 {max_shift:.0f}ms，阈值 {threshold_ms:.0f}ms）"
        else:
            message = (
                f"字幕与音轨未对齐（最大偏移 {max_shift:.0f}ms，"
                f"平均偏移 {mean_shift:.0f}ms，阈值 {threshold_ms:.0f}ms）"
            )

        return AlignmentCheckResult(
            aligned=aligned,
            checked_cues=pair_count,
            max_shift_ms=round(max_shift, 1),
            mean_shift_ms=round(mean_shift, 1),
            threshold_ms=threshold_ms,
            message=message,
        )

    @classmethod
    def extract_start_times(cls, subtitle_path: Path) -> list[float]:
        """提取字幕中每条对白的起始时间（毫秒）。"""
        raw_bytes = subtitle_path.read_bytes()
        try:
            text, _ = SubtitleDetector.decode_subtitle_bytes(raw_bytes)
        except Exception as exc:
            raise SubtitleAlignError(f"解析字幕编码失败: {exc}") from exc

        ext = subtitle_path.suffix.lower()
        starts: list[float] = []
        if ext in {".ass", ".ssa"}:
            for match in _ASS_DIALOGUE_PATTERN.finditer(text):
                hours, minutes, seconds, centis = (int(match.group(i)) for i in range(1, 5))
                starts.append(((hours * 3600 + minutes * 60 + seconds) * 1000) + centis * 10)
        else:
            for match in _SRT_TIME_PATTERN.finditer(text):
                hours, minutes, seconds, millis = (int(match.group(i)) for i in range(1, 5))
                starts.append((hours * 3600 + minutes * 60 + seconds) * 1000 + millis)
        return starts

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
        # 对齐属于后台批处理：通过 nice 降低 CPU 优先级，避免长时间打满宿主机 CPU
        # 而影响同机其他服务及本服务 API（含 /health）的响应。ffmpeg 子进程会继承该优先级。
        cmd = [
            "nice",
            "-n",
            "10",
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
        # 同 _run_alass：后台批处理降低 CPU 优先级，保护宿主机其他服务与 API 响应。
        cmd = [
            "nice",
            "-n",
            "10",
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
