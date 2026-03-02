"""
CPU Affinity Manager
====================
Routes processes to Performance or Efficiency CPU cores based on classification.
"""

from typing import Dict, List, Optional, Set

import psutil

from core.app_classifier import AppCategory, AppClassifier
from core.config import Config
from models.telemetry_models import ProcessInfo, OptimizationAction
from utils.logger import get_logger

logger = get_logger()


class CpuAffinityManager:
    """Manages CPU core affinity for processes based on their classification."""

    def __init__(
        self,
        config: Config = None,
        classifier: AppClassifier = None,
    ):
        self._config = config or Config()
        self._classifier = classifier or AppClassifier(self._config)
        self._routed_pids: Dict[int, List[int]] = {}  # pid -> assigned cores

    @property
    def performance_cores(self) -> List[int]:
        """Get configured P-Core IDs, clamped to actual CPU count."""
        max_cores = psutil.cpu_count(logical=True)
        return [c for c in self._config.performance_cores if c < max_cores]

    @property
    def efficiency_cores(self) -> List[int]:
        """Get configured E-Core IDs, clamped to actual CPU count."""
        max_cores = psutil.cpu_count(logical=True)
        return [c for c in self._config.efficiency_cores if c < max_cores]

    @property
    def all_cores(self) -> List[int]:
        return list(range(psutil.cpu_count(logical=True)))

    def set_affinity(self, pid: int, cores: List[int]) -> bool:
        """Set CPU affinity for a specific process.

        Args:
            pid: Process ID.
            cores: List of core IDs to assign.

        Returns:
            True if affinity was set successfully.
        """
        try:
            proc = psutil.Process(pid)
            proc.cpu_affinity(cores)
            self._routed_pids[pid] = cores
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError) as e:
            logger.debug(f"Cannot set affinity for PID {pid}: {e}")
            return False

    def route_to_performance(self, pid: int, name: str = "") -> OptimizationAction:
        """Route a process to Performance cores."""
        action = OptimizationAction(
            pid=pid,
            process_name=name,
            action="set_affinity",
            reason="Routed to Performance cores",
        )
        cores = self.performance_cores
        if not cores:
            cores = self.all_cores  # fallback to all if not configured

        action.success = self.set_affinity(pid, cores)
        action.detail = f"Cores: {cores}"
        if action.success:
            logger.debug(f"🏎️ '{name}' (PID {pid}) → P-Cores {cores}")
        return action

    def route_to_efficiency(self, pid: int, name: str = "") -> OptimizationAction:
        """Route a process to Efficiency cores."""
        action = OptimizationAction(
            pid=pid,
            process_name=name,
            action="set_affinity",
            reason="Routed to Efficiency cores",
        )
        cores = self.efficiency_cores
        if not cores:
            cores = self.all_cores

        action.success = self.set_affinity(pid, cores)
        action.detail = f"Cores: {cores}"
        if action.success:
            logger.debug(f"🐢 '{name}' (PID {pid}) → E-Cores {cores}")
        return action

    def optimize_affinities(
        self, processes: List[ProcessInfo]
    ) -> List[OptimizationAction]:
        """Route all processes based on their classification.

        - GRAPHIC_INTENSIVE & COMPUTE_HEAVY + foreground → P-Cores
        - BACKGROUND & LIGHT (non-foreground) → E-Cores
        - Foreground process always gets P-Cores

        Returns:
            List of OptimizationAction records.
        """
        if not self._config.cpu_routing_enabled:
            return []

        actions: List[OptimizationAction] = []
        processed: Set[int] = set()

        for proc in processes:
            if proc.pid in processed:
                continue
            processed.add(proc.pid)

            category = self._classifier.classify(proc)

            # Foreground always gets P-Cores
            if proc.is_foreground:
                result = self.route_to_performance(proc.pid, proc.name)
                actions.append(result)
                continue

            # High-priority categories → P-Cores
            if category in (AppCategory.GRAPHIC_INTENSIVE, AppCategory.COMPUTE_HEAVY):
                result = self.route_to_performance(proc.pid, proc.name)
                actions.append(result)
            # Low-priority → E-Cores
            elif category == AppCategory.BACKGROUND:
                result = self.route_to_efficiency(proc.pid, proc.name)
                actions.append(result)
            # LIGHT apps → leave on default (all cores)

        succeeded = sum(1 for a in actions if a.success)
        if actions:
            logger.info(f"CPU affinity: {succeeded}/{len(actions)} routes applied")

        return actions
