from pathlib import Path

import pytest

from app.core.system_load import (
    LOAD_PER_CORE_REJECT_THRESHOLD,
    MEM_AVAILABLE_REJECT_RATIO,
    SystemLoadSnapshot,
    ensure_system_not_busy,
    evaluate_system_load,
    read_system_load,
)
from app.services.errors import SystemBusyError


def _write_proc_files(tmp_path: Path, load1: str, mem_total_kb: int = 16_000_000, mem_available_kb: int = 8_000_000):
    loadavg = tmp_path / "loadavg"
    loadavg.write_text(f"{load1} 0.50 0.30 1/100 12345\n", encoding="ascii")
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(
        f"MemTotal:       {mem_total_kb} kB\nMemFree:        1000000 kB\nMemAvailable:   {mem_available_kb} kB\n",
        encoding="ascii",
    )
    return loadavg, meminfo


def test_read_system_load_parses_proc_files(tmp_path: Path, monkeypatch):
    loadavg, meminfo = _write_proc_files(tmp_path, "2.50")
    monkeypatch.setattr("os.cpu_count", lambda: 4)

    snapshot = read_system_load(loadavg_path=loadavg, meminfo_path=meminfo)

    assert snapshot.load1 == 2.5
    assert snapshot.cpu_count == 4
    assert snapshot.load_per_core == 0.625
    assert snapshot.mem_available_ratio == 0.5


def test_read_system_load_tolerates_missing_files(tmp_path: Path):
    missing = tmp_path / "nonexistent"
    snapshot = read_system_load(loadavg_path=missing, meminfo_path=missing)

    # 读取失败按空闲处理，不阻塞任务
    assert snapshot.load1 == 0.0
    assert snapshot.mem_available_ratio is None


def test_evaluate_system_load_idle_when_below_thresholds():
    snapshot = SystemLoadSnapshot(
        load1=1.0,
        cpu_count=4,
        load_per_core=LOAD_PER_CORE_REJECT_THRESHOLD - 0.1,
        mem_available_ratio=MEM_AVAILABLE_REJECT_RATIO + 0.1,
    )
    assert evaluate_system_load(snapshot) is None


def test_evaluate_system_load_busy_on_high_cpu():
    snapshot = SystemLoadSnapshot(
        load1=LOAD_PER_CORE_REJECT_THRESHOLD * 4,
        cpu_count=4,
        load_per_core=LOAD_PER_CORE_REJECT_THRESHOLD,
        mem_available_ratio=0.8,
    )
    reason = evaluate_system_load(snapshot)
    assert reason is not None
    assert "CPU 负载过高" in reason


def test_evaluate_system_load_busy_on_low_memory():
    snapshot = SystemLoadSnapshot(
        load1=0.1,
        cpu_count=4,
        load_per_core=0.025,
        mem_available_ratio=MEM_AVAILABLE_REJECT_RATIO - 0.01,
    )
    reason = evaluate_system_load(snapshot)
    assert reason is not None
    assert "可用内存不足" in reason


def test_evaluate_system_load_skips_memory_check_when_unknown():
    snapshot = SystemLoadSnapshot(load1=0.1, cpu_count=4, load_per_core=0.025, mem_available_ratio=None)
    assert evaluate_system_load(snapshot) is None


def test_ensure_system_not_busy_raises_when_busy(monkeypatch):
    busy_snapshot = SystemLoadSnapshot(load1=99.0, cpu_count=4, load_per_core=24.75, mem_available_ratio=0.9)
    monkeypatch.setattr("app.core.system_load.read_system_load", lambda: busy_snapshot)

    with pytest.raises(SystemBusyError, match="系统资源紧张"):
        ensure_system_not_busy()


def test_ensure_system_not_busy_passes_when_idle(monkeypatch):
    idle_snapshot = SystemLoadSnapshot(load1=0.5, cpu_count=4, load_per_core=0.125, mem_available_ratio=0.9)
    monkeypatch.setattr("app.core.system_load.read_system_load", lambda: idle_snapshot)

    ensure_system_not_busy()  # 不抛异常即通过
