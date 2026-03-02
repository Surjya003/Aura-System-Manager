"""
System Telemetry Collector
==========================
Collects real-time RAM, CPU (per-core), and GPU metrics using psutil and GPUtil.
"""

from datetime import datetime
from typing import List

import psutil

from models.telemetry_models import (
    CpuCoreInfo,
    GpuInfo,
    MemoryInfo,
    SystemSnapshot,
    ProcessInfo,
)
from utils.logger import get_logger


def get_memory_info() -> MemoryInfo:
    """Collect current system memory statistics."""
    mem = psutil.virtual_memory()
    return MemoryInfo(
        total_mb=round(mem.total / (1024 ** 2), 1),
        available_mb=round(mem.available / (1024 ** 2), 1),
        used_mb=round(mem.used / (1024 ** 2), 1),
        percent=mem.percent,
    )


def get_cpu_info() -> List[CpuCoreInfo]:
    """Collect per-core CPU usage percentages and frequencies."""
    usages = psutil.cpu_percent(interval=0.1, percpu=True)
    freqs = psutil.cpu_freq(percpu=True) or []

    cores = []
    for i, usage in enumerate(usages):
        freq = freqs[i].current if i < len(freqs) else 0.0
        cores.append(CpuCoreInfo(
            core_id=i,
            usage_percent=usage,
            frequency_mhz=round(freq, 1),
        ))
    return cores


def get_gpu_info() -> List[GpuInfo]:
    """Collect GPU metrics (load, VRAM, temperature).

    Returns an empty list if no NVIDIA GPU is detected or GPUtil fails.
    """
    try:
        import GPUtil
        gpus = GPUtil.getGPUs()
        return [
            GpuInfo(
                id=gpu.id,
                name=gpu.name,
                load_percent=round(gpu.load * 100, 1),
                memory_total_mb=round(gpu.memoryTotal, 1),
                memory_used_mb=round(gpu.memoryUsed, 1),
                memory_free_mb=round(gpu.memoryFree, 1),
                temperature=gpu.temperature if gpu.temperature else 0.0,
            )
            for gpu in gpus
        ]
    except Exception as e:
        get_logger().debug(f"GPU info unavailable: {e}")
        return []


# Global mock variables for Fan Speed Simulation
MOCK_FAN_SPEED = 50.0

def set_mock_fan_speed(speed: float):
    global MOCK_FAN_SPEED
    MOCK_FAN_SPEED = max(0.0, min(100.0, speed))


def get_system_snapshot(processes: List[ProcessInfo] = None) -> SystemSnapshot:
    """Collect a complete system telemetry snapshot.

    Args:
        processes: Optional pre-scanned process list. If None, an empty list is used
                   (use process_scanner.scan_all_processes() to populate).

    Returns:
        A SystemSnapshot with current memory, CPU, GPU, and process data.
    """
    cpu_cores = get_cpu_info()
    cpu_overall = psutil.cpu_percent(interval=0.0)

    # Mock CPU Temperature based on overall CPU usage (baseline 40C + 0.5C per percent load)
    cpu_temp = 40.0 + (cpu_overall * 0.5)

    return SystemSnapshot(
        timestamp=datetime.now(),
        memory=get_memory_info(),
        cpu_cores=cpu_cores,
        cpu_overall_percent=cpu_overall,
        gpus=get_gpu_info(),
        processes=processes or [],
        total_processes=len(processes) if processes else 0,
        cpu_temperature_c=round(cpu_temp, 1),
        fan_speed_percent=MOCK_FAN_SPEED,
    )
