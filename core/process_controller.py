"""
Process Controller
==================
Handles terminating, suspending, and resuming processes with safety checks.
Uses both psutil and native Windows APIs for suspension.
"""

import ctypes
from ctypes import wintypes
from typing import Optional

import psutil

from core.lists_manager import ListsManager
from models.telemetry_models import ProcessInfo, OptimizationAction
from utils.logger import get_logger

logger = get_logger()

# Windows native process access constants
PROCESS_SUSPEND_RESUME = 0x0800
PROCESS_TERMINATE = 0x0001


def _nt_suspend_process(pid: int) -> bool:
    """Suspend a process using NtSuspendProcess (ntdll).

    Returns True on success.
    """
    try:
        ntdll = ctypes.WinDLL("ntdll")
        kernel32 = ctypes.WinDLL("kernel32")

        handle = kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
        if not handle:
            return False

        result = ntdll.NtSuspendProcess(handle)
        kernel32.CloseHandle(handle)
        return result == 0  # STATUS_SUCCESS
    except Exception as e:
        logger.error(f"NtSuspendProcess failed for PID {pid}: {e}")
        return False


def _nt_resume_process(pid: int) -> bool:
    """Resume a suspended process using NtResumeProcess (ntdll).

    Returns True on success.
    """
    try:
        ntdll = ctypes.WinDLL("ntdll")
        kernel32 = ctypes.WinDLL("kernel32")

        handle = kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
        if not handle:
            return False

        result = ntdll.NtResumeProcess(handle)
        kernel32.CloseHandle(handle)
        return result == 0
    except Exception as e:
        logger.error(f"NtResumeProcess failed for PID {pid}: {e}")
        return False


def terminate_process(pid: int, process_name: str = "", force: bool = False) -> OptimizationAction:
    """Terminate a process — graceful first, then force if needed.

    Args:
        pid: Process ID to terminate.
        process_name: Name for logging/action record.
        force: If True, skip graceful termination and force kill.

    Returns:
        OptimizationAction with success status.
    """
    action = OptimizationAction(
        pid=pid,
        process_name=process_name,
        action="terminate",
        reason="Memory threshold exceeded or blacklisted",
    )

    try:
        proc = psutil.Process(pid)
        process_name = process_name or proc.name()

        if not force:
            # Graceful termination
            proc.terminate()
            try:
                proc.wait(timeout=3)
                action.success = True
                action.detail = "Gracefully terminated"
                logger.info(f"✓ Terminated '{process_name}' (PID {pid})")
                return action
            except psutil.TimeoutExpired:
                logger.warning(f"Graceful terminate timed out for '{process_name}', forcing...")

        # Force kill
        proc.kill()
        proc.wait(timeout=3)
        action.success = True
        action.detail = "Force killed"
        logger.info(f"✓ Force killed '{process_name}' (PID {pid})")

    except psutil.NoSuchProcess:
        action.success = True
        action.detail = "Process already exited"
    except psutil.AccessDenied:
        action.success = False
        action.detail = "Access denied — insufficient privileges"
        logger.error(f"✗ Access denied terminating '{process_name}' (PID {pid})")
    except Exception as e:
        action.success = False
        action.detail = str(e)
        logger.error(f"✗ Failed to terminate '{process_name}' (PID {pid}): {e}")

    return action


def suspend_process(pid: int, process_name: str = "") -> OptimizationAction:
    """Suspend a process using Windows NtSuspendProcess.

    Args:
        pid: Process ID to suspend.
        process_name: Name for logging/action record.

    Returns:
        OptimizationAction with success status.
    """
    action = OptimizationAction(
        pid=pid,
        process_name=process_name or str(pid),
        action="suspend",
        reason="Memory threshold exceeded or blacklisted",
    )

    try:
        proc = psutil.Process(pid)
        process_name = process_name or proc.name()
        action.process_name = process_name

        # Try psutil suspend first (cross-platform)
        try:
            proc.suspend()
            action.success = True
            action.detail = "Suspended via psutil"
            logger.info(f"⏸ Suspended '{process_name}' (PID {pid})")
            return action
        except Exception:
            pass

        # Fallback to native Windows API
        if _nt_suspend_process(pid):
            action.success = True
            action.detail = "Suspended via NtSuspendProcess"
            logger.info(f"⏸ Suspended '{process_name}' (PID {pid}) [native]")
        else:
            action.success = False
            action.detail = "Both suspension methods failed"
            logger.error(f"✗ Failed to suspend '{process_name}' (PID {pid})")

    except psutil.NoSuchProcess:
        action.success = False
        action.detail = "Process no longer exists"
    except psutil.AccessDenied:
        action.success = False
        action.detail = "Access denied"
        logger.error(f"✗ Access denied suspending '{process_name}' (PID {pid})")

    return action


def resume_process(pid: int, process_name: str = "") -> OptimizationAction:
    """Resume a previously suspended process.

    Args:
        pid: Process ID to resume.
        process_name: Name for logging.

    Returns:
        OptimizationAction with success status.
    """
    action = OptimizationAction(
        pid=pid,
        process_name=process_name or str(pid),
        action="resume",
        reason="User request or process needed",
    )

    try:
        proc = psutil.Process(pid)
        process_name = process_name or proc.name()
        action.process_name = process_name

        try:
            proc.resume()
            action.success = True
            action.detail = "Resumed via psutil"
            logger.info(f"▶ Resumed '{process_name}' (PID {pid})")
            return action
        except Exception:
            pass

        if _nt_resume_process(pid):
            action.success = True
            action.detail = "Resumed via NtResumeProcess"
            logger.info(f"▶ Resumed '{process_name}' (PID {pid}) [native]")
        else:
            action.success = False
            action.detail = "Resume failed"

    except psutil.NoSuchProcess:
        action.success = False
        action.detail = "Process no longer exists"

    return action
