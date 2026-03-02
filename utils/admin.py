"""
Admin Elevation Utility
=======================
Handles Windows UAC elevation checks and re-launch with admin privileges.
"""

import ctypes
import sys
import os


def is_admin() -> bool:
    """Check if the current process has administrator privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except (AttributeError, OSError):
        return False


def request_elevation() -> None:
    """Re-launch the current script with elevated (admin) privileges via UAC prompt.

    If already admin, this is a no-op. Otherwise, the current process exits
    and a new elevated process is started.
    """
    if is_admin():
        return

    # Re-run the script with elevation
    script = os.path.abspath(sys.argv[0])
    params = " ".join([f'"{arg}"' for arg in sys.argv[1:]])

    try:
        ctypes.windll.shell32.ShellExecuteW(
            None,           # hwnd
            "runas",        # operation — triggers UAC
            sys.executable, # program
            f'"{script}" {params}',  # parameters
            None,           # directory
            1               # SW_SHOWNORMAL
        )
    except Exception as e:
        print(f"[ERROR] Failed to elevate privileges: {e}")
        sys.exit(1)

    # Exit the non-elevated process
    sys.exit(0)


def ensure_admin() -> None:
    """Ensure the process is running with admin rights, or elevate and exit."""
    if not is_admin():
        print("[!] Administrator privileges required. Requesting elevation...")
        request_elevation()
