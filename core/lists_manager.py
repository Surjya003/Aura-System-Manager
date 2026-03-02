"""
Whitelist / Blacklist Manager
==============================
Manages lists of protected and targeted processes.
"""

import os
from typing import List, Set
import psutil

from core.config import Config
from models.telemetry_models import ProcessInfo
from utils.logger import get_logger

logger = get_logger()


# Critical system processes that must NEVER be touched, regardless of config.
# Killing any of these can crash or destabilize Windows.
_SYSTEM_CRITICAL: Set[str] = {
    # ── Kernel & Session ──
    "system", "system idle process", "registry", "memory compression",
    "csrss.exe", "smss.exe", "lsass.exe", "lsaiso.exe", "services.exe",
    "wininit.exe", "winlogon.exe", "svchost.exe",
    # ── Desktop & Shell ──
    "dwm.exe", "explorer.exe", "sihost.exe", "fontdrvhost.exe",
    "conhost.exe", "dllhost.exe", "taskhostw.exe",
    "shellexperiencehost.exe", "startmenuexperiencehost.exe",
    "searchhost.exe", "searchui.exe", "searchapp.exe",
    "textinputhost.exe", "inputapp.exe",
    "applicationframehost.exe", "lockapp.exe",
    "runtimebroker.exe", "backgroundtaskhost.exe",
    # ── Security ──
    "securityhealthservice.exe", "securityhealthsystray.exe",
    "sgrmbroker.exe", "msmpeng.exe", "mpcmdrun.exe",
    "nissrv.exe", "smartscreen.exe",
    # ── Networking & System Services ──
    "spoolsv.exe", "audiodg.exe", "ctfmon.exe",
    "dashost.exe", "wmiprvse.exe", "wudfhost.exe",
    "lsm.exe", "msdtc.exe", "vssvc.exe",
    "searchindexer.exe", "searchprotocolhost.exe",
    "searchfilterhost.exe",
    # ── Windows Update & Store ──
    "tiworker.exe", "trustedinstaller.exe", "musnotification.exe",
    "wsappx.exe",
    # ── Graphics & Display ──
    "igfxcuiservice.exe", "igfxem.exe", "nvcontainer.exe",
    "nvdisplay.container.exe",
    # ── User Experience ──
    "useroobebroker.exe", "systemsettings.exe",
    "systemsettingsbroker.exe", "settingsynchost.exe",
    "cexecsvc.exe", "compactoverlay.exe",
    # ── Power & Hardware ──
    "upfc.exe", "devicecensus.exe", "compattelrunner.exe",
    # ── App Helpers (Crash Prevention) ──
    # Browsers
    "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe",
    # IDEs & Dev Tools
    "code.exe", "pycharm64.exe", "idea64.exe", "devenv.exe",
    "antigravity.exe", "cursor.exe", "windsurf.exe",
    # Common Electron apps
    "discord.exe", "slack.exe", "teams.exe", "spotify.exe",
}


class ListsManager:
    """Manages whitelisted (protected) and blacklisted (targeted) processes."""

    def __init__(self, config: Config = None):
        self._config = config or Config()
        self._protected_pids: Set[int] = set()
        self._refresh_lists()

    def _refresh_lists(self) -> None:
        """Rebuild the whitelist and blacklist sets from config."""
        cfg_whitelist = self._config.whitelist or []
        cfg_blacklist = self._config.blacklist or []

        self._whitelist: Set[str] = _SYSTEM_CRITICAL | {
            name.lower() for name in cfg_whitelist
        }
        self._blacklist: Set[str] = {
            name.lower() for name in cfg_blacklist
        }

        # Dynamically protect the optimizer itself and its entire parent tree
        # This prevents the optimizer from suspending itself or the Antigravity agent shell
        self._protect_own_process_tree()

    def _protect_own_process_tree(self) -> None:
        """Finds this process and all its parents, adding their PIDs to the protected set."""
        self._protected_pids.clear()
        try:
            current_pid = os.getpid()
            proc = psutil.Process(current_pid)
            
            # Add self and all parents up the chain
            while proc is not None:
                self._protected_pids.add(proc.pid)
                logger.debug(f"Protected parent process: {proc.name()} (PID {proc.pid})")
                proc = proc.parent()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    def reload(self) -> None:
        """Reload lists if config has changed."""
        if self._config.reload_if_changed():
            self._refresh_lists()
            logger.info("Lists reloaded from config")

    def is_protected(self, process: ProcessInfo) -> bool:
        """Check if a process is on the whitelist (should never be touched).

        Also protects the optimizer itself, its parent process tree, and the foreground process.
        """
        if process.pid in self._protected_pids:
            return True
        if process.is_foreground:
            return True
        return process.name_lower in self._whitelist

    def is_blacklisted(self, process: ProcessInfo) -> bool:
        """Check if a process is on the blacklist (should be terminated/suspended)."""
        return process.name_lower in self._blacklist

    def is_actionable(self, process: ProcessInfo) -> bool:
        """Check if a process can have actions performed on it.

        A process is actionable if it's NOT protected. Blacklisted processes
        are always actionable; other processes are actionable if they exceed thresholds.
        """
        return not self.is_protected(process)

    @property
    def whitelist(self) -> Set[str]:
        return self._whitelist.copy()

    @property
    def blacklist(self) -> Set[str]:
        return self._blacklist.copy()

    def add_to_whitelist(self, name: str) -> None:
        """Dynamically add a process name to the runtime whitelist."""
        self._whitelist.add(name.lower())
        logger.info(f"Added '{name}' to whitelist")

    def add_to_blacklist(self, name: str) -> None:
        """Dynamically add a process name to the runtime blacklist."""
        self._blacklist.add(name.lower())
        logger.info(f"Added '{name}' to blacklist")
