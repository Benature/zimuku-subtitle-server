"""批量检查媒体库中字幕与音轨的对齐状态。

用法（容器内）：
    python -m app.scripts.check_library_alignment \
        [--threshold-ms 100] [--path-contains /media] [--limit N] [--output report.json]

说明：
- 仅执行只读判定（对齐到临时副本比对偏移量），不会修改任何字幕文件
- 跳过 .sup 图形字幕与无关联字幕的文件
"""

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sqlmodel import Session, select

from ..core.aligner import SubtitleAligner
from ..db.models import ScannedFile
from ..db.session import create_db_and_tables, engine
from ..services.subtitle_inspection_service import (
    ALIGNMENT_STATUS_ALIGNED,
    ALIGNMENT_STATUS_MISALIGNED,
    SubtitleInspectionService,
    record_alignment_result,
)

logger = logging.getLogger("check_library_alignment")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

TEXT_SUBTITLE_FORMATS = {".srt", ".ass", ".ssa"}


@dataclass
class CheckItem:
    file_id: int
    video_path: str
    subtitle_path: str


@dataclass
class CheckReport:
    aligned: list[dict] = field(default_factory=list)
    unaligned: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)


def collect_check_items(path_contains: str | None, limit: int | None) -> list[CheckItem]:
    items: list[CheckItem] = []
    with Session(engine) as session:
        files = list(session.exec(select(ScannedFile).where(ScannedFile.has_subtitle.is_(True))).all())

    for media in files:
        video_path = Path(media.file_path)
        if path_contains and path_contains not in str(video_path):
            continue
        if not video_path.is_file():
            continue

        subtitle_paths = SubtitleInspectionService._find_related_subtitle_files(video_path)
        text_subs = [p for p in subtitle_paths if p.suffix.lower() in TEXT_SUBTITLE_FORMATS]
        for sub in text_subs:
            items.append(CheckItem(file_id=media.id, video_path=str(video_path), subtitle_path=str(sub)))
            if limit and len(items) >= limit:
                break

    # 排序保证分片划分的确定性
    items.sort(key=lambda i: i.subtitle_path)
    if limit:
        return items[:limit]
    return items


async def run_checks(items: list[CheckItem], threshold_ms: float, timeout_seconds: int = 300) -> CheckReport:
    report = CheckReport()
    total = len(items)

    for index, item in enumerate(items, start=1):
        sub_path = Path(item.subtitle_path)
        video_path = Path(item.video_path)
        logger.info("[%s/%s] checking %s", index, total, sub_path.name)
        try:
            result = await SubtitleAligner.check_alignment(
                reference_path=video_path,
                subtitle_path=sub_path,
                threshold_ms=threshold_ms,
                timeout_seconds=timeout_seconds,
            )
            entry = {
                "file_id": item.file_id,
                "video_path": item.video_path,
                "subtitle_path": item.subtitle_path,
                "max_shift_ms": result.max_shift_ms,
                "mean_shift_ms": result.mean_shift_ms,
                "checked_cues": result.checked_cues,
            }
            if result.aligned:
                report.aligned.append(entry)
            else:
                report.unaligned.append(entry)
            try:
                record_alignment_result(
                    subtitle_path=sub_path,
                    file_id=item.file_id,
                    status=ALIGNMENT_STATUS_ALIGNED if result.aligned else ALIGNMENT_STATUS_MISALIGNED,
                    max_shift_ms=result.max_shift_ms,
                    mean_shift_ms=result.mean_shift_ms,
                )
            except Exception as state_exc:
                logger.warning("record alignment state failed for %s: %s", sub_path, state_exc)
        except Exception as exc:
            logger.warning("check failed for %s: %s", sub_path, exc)
            report.errors.append(
                {
                    "file_id": item.file_id,
                    "video_path": item.video_path,
                    "subtitle_path": item.subtitle_path,
                    "error": str(exc),
                }
            )

    return report


def print_summary(report: CheckReport) -> None:
    print("\n========== 音轨对齐检查报告 ==========")
    print(f"已对齐:   {len(report.aligned)}")
    print(f"未对齐:   {len(report.unaligned)}")
    print(f"检查失败: {len(report.errors)}")

    if report.unaligned:
        print("\n--- 未对齐字幕清单 ---")
        for entry in report.unaligned:
            shift_info = f"max {entry['max_shift_ms']:>8.0f}ms / avg {entry['mean_shift_ms']:>8.0f}ms"
            print(f"  [{shift_info}] {entry['subtitle_path']}")

    if report.errors:
        print("\n--- 检查失败清单 ---")
        for entry in report.errors:
            print(f"  {entry['subtitle_path']}: {entry['error']}")


def import_report_states(report_path: str) -> int:
    """将历史检查报告（JSON）中的判定结果回写为字幕对齐状态属性。"""
    create_db_and_tables()
    data = json.loads(Path(report_path).read_text(encoding="utf-8"))
    imported = 0
    skipped = 0
    for status_key, status_value in (("aligned", ALIGNMENT_STATUS_ALIGNED), ("unaligned", ALIGNMENT_STATUS_MISALIGNED)):
        for entry in data.get(status_key, []):
            sub_path = Path(entry["subtitle_path"])
            if not sub_path.is_file():
                skipped += 1
                continue
            try:
                record_alignment_result(
                    subtitle_path=sub_path,
                    file_id=entry.get("file_id"),
                    status=status_value,
                    max_shift_ms=entry.get("max_shift_ms"),
                    mean_shift_ms=entry.get("mean_shift_ms"),
                )
                imported += 1
            except OSError:
                skipped += 1
    print(f"状态导入完成: {imported} 条, 跳过 {skipped} 条（文件不存在或不可读）")
    return 0


async def main_async(args: argparse.Namespace) -> int:
    status = SubtitleAligner.get_status()
    if not status.available:
        print(f"音轨对齐组件不可用: {status.message}", file=sys.stderr)
        return 2

    items = collect_check_items(path_contains=args.path_contains, limit=args.limit)

    if args.subtitle_paths_file:
        wanted = {
            line.strip()
            for line in Path(args.subtitle_paths_file).read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
        items = [item for item in items if item.subtitle_path in wanted]

    if not items:
        print("未找到任何待检查的文本字幕（媒体库中没有 has_subtitle=True 且含文本字幕的文件）")
        return 0

    total_collected = len(items)
    if args.shard_count > 1:
        items = [item for idx, item in enumerate(items) if idx % args.shard_count == args.shard_index]

    print(
        f"共发现 {total_collected} 个字幕，当前分片 {args.shard_index + 1}/{args.shard_count} "
        f"负责 {len(items)} 个（阈值 {args.threshold_ms}ms）..."
    )
    report = await run_checks(items, args.threshold_ms, timeout_seconds=args.timeout_seconds)
    print_summary(report)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(
                {
                    "threshold_ms": args.threshold_ms,
                    "aligned": report.aligned,
                    "unaligned": report.unaligned,
                    "errors": report.errors,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\n报告已保存: {output_path}")

    return 1 if report.unaligned else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="批量检查媒体库字幕与音轨对齐状态")
    parser.add_argument("--threshold-ms", type=float, default=100.0, help="对齐判定阈值（毫秒，默认 100）")
    parser.add_argument("--timeout-seconds", type=int, default=300, help="单个字幕检查超时秒数（默认 300）")
    parser.add_argument("--path-contains", type=str, default=None, help="仅检查路径包含该片段的媒体文件")
    parser.add_argument(
        "--subtitle-paths-file",
        type=str,
        default=None,
        help="仅检查该文件中列出的字幕路径（每行一个绝对路径）",
    )
    parser.add_argument("--limit", type=int, default=None, help="最多检查的字幕数量")
    parser.add_argument("--shard-count", type=int, default=1, help="并行分片总数（默认 1，不分片）")
    parser.add_argument("--shard-index", type=int, default=0, help="当前分片序号（0 起）")
    parser.add_argument("--output", type=str, default=None, help="将 JSON 报告写入指定文件")
    parser.add_argument(
        "--import-report",
        type=str,
        default=None,
        help="仅将指定历史检查报告 JSON 的判定结果回写为对齐状态，不执行实际检查",
    )
    args = parser.parse_args()
    if args.shard_count < 1 or not (0 <= args.shard_index < args.shard_count):
        parser.error("--shard-index 必须满足 0 <= shard-index < shard-count")
    if args.import_report:
        return import_report_states(args.import_report)
    create_db_and_tables()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
