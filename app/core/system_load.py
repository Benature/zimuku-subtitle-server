"""系统资源负载检查：音轨对齐等重任务执行前的资源守卫。

读取 /proc/loadavg 与 /proc/meminfo 评估当前系统繁忙程度，
超过阈值时拒绝启动新的重任务，避免在资源紧张时雪上加霜。
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..services.errors import SystemBusyError

logger = logging.getLogger(__name__)

# load1 / CPU 核数达到该值即视为系统繁忙（平均每核已有 1 个任务在排队）
LOAD_PER_CORE_REJECT_THRESHOLD = 1.0
# 可用内存占比低于该值即视为系统繁忙
MEM_AVAILABLE_REJECT_RATIO = 0.10

_PROC_LOADAVG = Path("/proc/loadavg")
_PROC_MEMINFO = Path("/proc/meminfo")


@dataclass
class SystemLoadSnapshot:
    """系统负载快照。"""

    load1: float
    cpu_count: int
    load_per_core: float
    mem_available_ratio: Optional[float]  # 无法读取时为 None（不参与判定）

    def to_dict(self) -> dict:
        return {
            "load1": self.load1,
            "cpu_count": self.cpu_count,
            "load_per_core": round(self.load_per_core, 2),
            "mem_available_ratio": round(self.mem_available_ratio, 3) if self.mem_available_ratio is not None else None,
        }


def _read_load1(loadavg_path: Path) -> float:
    return float(loadavg_path.read_text(encoding="ascii").split()[0])


def _read_mem_available_ratio(meminfo_path: Path) -> Optional[float]:
    total_kb: Optional[int] = None
    available_kb: Optional[int] = None
    for line in meminfo_path.read_text(encoding="ascii").splitlines():
        if line.startswith("MemTotal:"):
            total_kb = int(line.split()[1])
        elif line.startswith("MemAvailable:"):
            available_kb = int(line.split()[1])
        if total_kb is not None and available_kb is not None:
            break
    if not total_kb or available_kb is None:
        return None
    return available_kb / total_kb


def read_system_load(
    loadavg_path: Path = _PROC_LOADAVG,
    meminfo_path: Path = _PROC_MEMINFO,
) -> SystemLoadSnapshot:
    """读取当前系统负载快照。读取失败时返回宽松默认值（不阻塞任务）。"""
    cpu_count = os.cpu_count() or 1

    try:
        load1 = _read_load1(loadavg_path)
    except Exception as exc:
        logger.warning("读取系统负载失败，按空闲处理: %s", exc)
        load1 = 0.0

    try:
        mem_ratio = _read_mem_available_ratio(meminfo_path)
    except Exception as exc:
        logger.warning("读取内存信息失败，内存维度不参与判定: %s", exc)
        mem_ratio = None

    return SystemLoadSnapshot(
        load1=load1,
        cpu_count=cpu_count,
        load_per_core=load1 / cpu_count,
        mem_available_ratio=mem_ratio,
    )


def evaluate_system_load(snapshot: SystemLoadSnapshot) -> Optional[str]:
    """判定系统是否繁忙，返回繁忙原因描述；空闲时返回 None。"""
    if snapshot.load_per_core >= LOAD_PER_CORE_REJECT_THRESHOLD:
        return (
            f"CPU 负载过高（load1={snapshot.load1:.1f}，核数={snapshot.cpu_count}，"
            f"每核负载={snapshot.load_per_core:.2f} ≥ {LOAD_PER_CORE_REJECT_THRESHOLD}）"
        )
    if snapshot.mem_available_ratio is not None and snapshot.mem_available_ratio < MEM_AVAILABLE_REJECT_RATIO:
        available_pct = snapshot.mem_available_ratio * 100
        threshold_pct = MEM_AVAILABLE_REJECT_RATIO * 100
        return f"可用内存不足（仅剩 {available_pct:.1f}% < {threshold_pct:.0f}%）"
    return None


def ensure_system_not_busy() -> None:
    """系统资源紧张时抛出 SystemBusyError，用于重任务执行前守卫。"""
    snapshot = read_system_load()
    reason = evaluate_system_load(snapshot)
    if reason:
        raise SystemBusyError(
            f"系统资源紧张，拒绝执行音轨对齐：{reason}。可稍后再试，或在 MCP 中使用 force=true 强制执行。"
        )
