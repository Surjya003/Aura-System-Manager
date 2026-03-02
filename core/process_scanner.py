"""
Process Scanner & Fingerprinting
=================================
Scans all running processes, collects metadata, and identifies the foreground app.
"""

import ctypes
import ctypes.wintypes
from typing import List, Optional

import psutil

from models.telemetry_models import ProcessInfo
from utils.logger import get_logger

logger = get_logger()


def get_foreground_pid() -> Optional[int]:
    """Get the PID of the process that owns the current foreground window.

    Returns:
        PID of the foreground process, or None if detection fails.
    """
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if hwnd == 0:
            return None
        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value if pid.value else None
    except Exception as e:
        logger.debug(f"Could not detect foreground PID: {e}")
        return None


def scan_all_processes(foreground_pid: Optional[int] = None) -> List[ProcessInfo]:
    """Scan all running processes and collect their resource metadata.

    Args:
        foreground_pid: If provided, the process with this PID is marked as foreground.
                        If None, auto-detection is attempted.

    Returns:
        List of ProcessInfo dataclass instances sorted by memory usage (desc).
    """
    if foreground_pid is None:
        foreground_pid = get_foreground_pid()

    processes: List[ProcessInfo] = []

    for proc in psutil.process_iter(
        attrs=["pid", "name", "exe", "memory_info", "cpu_percent", "status", "num_threads", "create_time"]
    ):
        try:
            info = proc.info
            pid = info["pid"]
            mem_bytes = info["memory_info"].rss if info.get("memory_info") else 0

            processes.append(ProcessInfo(
                pid=pid,
                name=info.get("name", "Unknown"),
                exe_path=info.get("exe", "") or "",
                memory_mb=round(mem_bytes / (1024 ** 2), 2),
                cpu_percent=info.get("cpu_percent", 0.0) or 0.0,
                status=info.get("status", "unknown"),
                num_threads=info.get("num_threads", 0) or 0,
                is_foreground=(pid == foreground_pid),
                create_time=info.get("create_time", 0.0) or 0.0,
            ))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    # Sort by memory descending
    processes.sort(key=lambda p: p.memory_mb, reverse=True)
    return processes


def fingerprint_process(proc: ProcessInfo) -> dict:
    """Create a fingerprint dict for a process — used for classification.

    Returns:
        Dict with keys: name, exe_path, memory_mb, cpu_percent, is_foreground, thread_count.
    """
    return {
        "name": proc.name_lower,
        "exe_path": proc.exe_path.lower(),
        "memory_mb": proc.memory_mb,
        "cpu_percent": proc.cpu_percent,
        "is_foreground": proc.is_foreground,
        "thread_count": proc.num_threads,
    }
