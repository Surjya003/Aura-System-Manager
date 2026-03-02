"""
GPU Preference Router
=====================
Manages per-application GPU preferences via the Windows Registry.
Forces graphic-intensive apps to dedicated GPU and light apps to integrated GPU.
"""

import winreg
from typing import Dict, List, Optional

from core.app_classifier import AppCategory, AppClassifier
from core.config import Config
from models.telemetry_models import ProcessInfo, OptimizationAction
from utils.logger import get_logger

logger = get_logger()

# Registry path for DirectX GPU preferences
_REG_PATH = r"Software\Microsoft\DirectX\UserGpuPreferences"

# GPU preference values
GPU_PREF_SYSTEM_DEFAULT = 0
GPU_PREF_POWER_SAVING = 1      # Integrated GPU
GPU_PREF_HIGH_PERFORMANCE = 2  # Dedicated GPU


class GpuRouter:
    """Manages GPU preferences for applications via Windows Registry."""

    def __init__(
        self,
        config: Config = None,
        classifier: AppClassifier = None,
    ):
        self._config = config or Config()
        self._classifier = classifier or AppClassifier(self._config)
        self._routed_apps: Dict[str, int] = {}  # exe_path -> pref value

    def _get_current_preference(self, exe_path: str) -> Optional[int]:
        """Read the current GPU preference for an executable from the registry."""
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _REG_PATH, 0, winreg.KEY_READ
            )
            value, _ = winreg.QueryValueEx(key, exe_path)
            winreg.CloseKey(key)
            # Value format: "GpuPreference=N;"
            if "GpuPreference=" in str(value):
                pref = int(str(value).split("GpuPreference=")[1].split(";")[0])
                return pref
            return None
        except (FileNotFoundError, OSError):
            return None

    def _set_preference(self, exe_path: str, preference: int) -> bool:
        """Write a GPU preference to the registry for an executable.

        Args:
            exe_path: Full path to the executable.
            preference: 0=System Default, 1=Power Saving, 2=High Performance.

        Returns:
            True if the registry was written successfully.
        """
        if not exe_path:
            return False

        try:
            key = winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER, _REG_PATH, 0, winreg.KEY_WRITE
            )
            value = f"GpuPreference={preference};"
            winreg.SetValueEx(key, exe_path, 0, winreg.REG_SZ, value)
            winreg.CloseKey(key)
            self._routed_apps[exe_path] = preference
            return True
        except (PermissionError, OSError) as e:
            logger.error(f"Failed to set GPU preference for '{exe_path}': {e}")
            return False

    def set_high_performance(self, exe_path: str) -> OptimizationAction:
        """Force an application to use the dedicated (high-performance) GPU."""
        action = OptimizationAction(
            pid=0,
            process_name=exe_path,
            action="set_gpu",
            reason="Set to High Performance GPU",
        )
        action.success = self._set_preference(exe_path, GPU_PREF_HIGH_PERFORMANCE)
        action.detail = "GpuPreference=2 (Dedicated GPU)"
        if action.success:
            logger.info(f"🎮 GPU → High Performance: {exe_path}")
        return action

    def set_power_saving(self, exe_path: str) -> OptimizationAction:
        """Force an application to use the integrated (power-saving) GPU."""
        action = OptimizationAction(
            pid=0,
            process_name=exe_path,
            action="set_gpu",
            reason="Set to Power Saving GPU",
        )
        action.success = self._set_preference(exe_path, GPU_PREF_POWER_SAVING)
        action.detail = "GpuPreference=1 (Integrated GPU)"
        if action.success:
            logger.info(f"🔋 GPU → Power Saving: {exe_path}")
        return action

    def set_system_default(self, exe_path: str) -> OptimizationAction:
        """Reset an application to system default GPU selection."""
        action = OptimizationAction(
            pid=0,
            process_name=exe_path,
            action="set_gpu",
            reason="Reset to System Default GPU",
        )
        action.success = self._set_preference(exe_path, GPU_PREF_SYSTEM_DEFAULT)
        action.detail = "GpuPreference=0 (System Default)"
        return action

    def optimize_gpu_routing(
        self, processes: List[ProcessInfo]
    ) -> List[OptimizationAction]:
        """Route processes to appropriate GPUs based on classification.

        - GRAPHIC_INTENSIVE → Dedicated GPU (High Performance)
        - LIGHT / BACKGROUND → Integrated GPU (Power Saving)

        Only acts on processes with valid exe_path, and avoids re-routing
        processes already at the correct setting.

        Returns:
            List of OptimizationAction records.
        """
        if not self._config.gpu_routing_enabled:
            return []

        actions: List[OptimizationAction] = []
        seen_paths: set = set()

        for proc in processes:
            if not proc.exe_path or proc.exe_path in seen_paths:
                continue
            seen_paths.add(proc.exe_path)

            category = self._classifier.classify(proc)

            # Determine desired preference
            if category == AppCategory.GRAPHIC_INTENSIVE:
                desired = GPU_PREF_HIGH_PERFORMANCE
            elif category in (AppCategory.LIGHT, AppCategory.BACKGROUND):
                desired = GPU_PREF_POWER_SAVING
            else:
                continue  # COMPUTE_HEAVY → leave at system default

            # Check if already set correctly
            current = self._get_current_preference(proc.exe_path)
            if current == desired:
                continue

            # Apply the preference
            if desired == GPU_PREF_HIGH_PERFORMANCE:
                result = self.set_high_performance(proc.exe_path)
            else:
                result = self.set_power_saving(proc.exe_path)

            result.pid = proc.pid
            result.process_name = proc.name
            actions.append(result)

        if actions:
            succeeded = sum(1 for a in actions if a.success)
            logger.info(f"GPU routing: {succeeded}/{len(actions)} preferences set")

        return actions

    @property
    def routed_apps(self) -> Dict[str, int]:
        """Return dict of exe_path → current GPU preference value."""
        return self._routed_apps.copy()
