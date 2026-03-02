"""
Memory Optimizer
================
Analyzes memory usage using the smart ProcessAnalyzer to identify truly
useless processes and execute optimization actions. Only kills/suspends
processes that score as BLOAT or JUNK — never touches useful ones.
"""

import ctypes
from typing import List, Tuple

from core.config import Config
from core.lists_manager import ListsManager
from core.process_controller import terminate_process, suspend_process
from core.process_scanner import scan_all_processes
from models.telemetry_models import ProcessInfo, OptimizationAction
from utils.logger import get_logger

logger = get_logger()


class MemoryOptimizer:
    """Analyzes and optimizes system memory using smart process analysis."""

    def __init__(self, config: Config = None, lists_mgr: ListsManager = None):
        self._config = config or Config()
        self._lists = lists_mgr or ListsManager(self._config)
        self._suspended_pids: dict = {}  # pid -> process_name
        self._analyzer = None  # Set externally via set_analyzer()

    def set_analyzer(self, analyzer):
        """Set the ProcessAnalyzer for smart analysis."""
        self._analyzer = analyzer

    def analyze_memory_hogs(
        self, processes: List[ProcessInfo]
    ) -> List[ProcessInfo]:
        """Identify processes exceeding the memory threshold.

        Returns:
            List of non-whitelisted processes above the threshold,
            sorted by memory usage descending.
        """
        threshold = self._config.memory_threshold_mb
        hogs = [
            p for p in processes
            if p.memory_mb >= threshold and self._lists.is_actionable(p)
        ]
        hogs.sort(key=lambda p: p.memory_mb, reverse=True)
        return hogs

    def get_blacklisted_running(
        self, processes: List[ProcessInfo]
    ) -> List[ProcessInfo]:
        """Find any blacklisted processes currently running."""
        return [
            p for p in processes
            if self._lists.is_blacklisted(p)
            and not self._lists.is_protected(p)
        ]

    def recommend_actions(
        self, processes: List[ProcessInfo], ram_percent: float = 0.0
    ) -> List[Tuple[ProcessInfo, str]]:
        """Build a list of recommended (process, action) tuples.

        Uses the smart ProcessAnalyzer if available, otherwise falls
        back to the simple threshold check.
        """
        recommendations: List[Tuple[ProcessInfo, str]] = []

        # ── Smart analysis path ──────────────────────────────────────────
        if self._analyzer:
            candidates = self._analyzer.get_cleanup_candidates(
                processes, ram_pressure=ram_percent
            )
            for score, action in candidates:
                # Find the matching ProcessInfo
                proc = next(
                    (p for p in processes if p.pid == score.pid), None
                )
                if proc:
                    recommendations.append((proc, action))

            if recommendations:
                total_reclaim = sum(
                    s.reclaimable_mb for s, _ in candidates
                )
                logger.info(
                    f"Smart analysis: {len(recommendations)} cleanup candidates "
                    f"(~{total_reclaim:.0f}MB reclaimable)"
                )
            return recommendations

        # ── Fallback: simple threshold path ──────────────────────────────
        # Blacklisted -> terminate
        for proc in self.get_blacklisted_running(processes):
            recommendations.append((proc, "terminate"))

        # Memory hogs -> configured action (suspend or terminate)
        default_action = self._config.memory_action
        max_actions = self._config.max_suspensions
        count = 0

        for proc in self.analyze_memory_hogs(processes):
            if count >= max_actions:
                break
            rec_pids = {r[0].pid for r in recommendations}
            if proc.pid not in rec_pids:
                recommendations.append((proc, default_action))
                count += 1

        return recommendations

    def optimize(
        self, processes: List[ProcessInfo], dry_run: bool = False,
        ram_percent: float = 0.0
    ) -> List[OptimizationAction]:
        """Run the full memory optimization pass.

        Args:
            processes: Current list of running processes.
            dry_run: If True, only return recommendations without executing.
            ram_percent: Current RAM usage (0-100) for pressure-based decisions.

        Returns:
            List of OptimizationAction records (executed or recommended).
        """
        self._lists.reload()
        recommendations = self.recommend_actions(processes, ram_percent)

        if not recommendations:
            return []

        actions: List[OptimizationAction] = []

        for proc, action_type in recommendations:
            # Build the reason string
            if self._analyzer:
                scores = self._analyzer.analyze_all([proc])
                reason_detail = ""
                if scores:
                    s = scores[0]
                    reason_detail = (
                        f"Score: {s.score:.0f}/100 ({s.verdict.value}) | "
                        f"Memory: {proc.memory_mb:.0f}MB | "
                        + "; ".join(s.reasons[:3])
                    )
                else:
                    reason_detail = f"Memory: {proc.memory_mb:.0f}MB"
            else:
                reason_detail = (
                    f"Memory: {proc.memory_mb:.0f}MB "
                    f"(threshold: {self._config.memory_threshold_mb}MB)"
                )

            if dry_run:
                actions.append(OptimizationAction(
                    pid=proc.pid,
                    process_name=proc.name,
                    action=action_type,
                    reason=reason_detail,
                    success=False,
                    detail="DRY RUN -- not executed",
                ))
                continue

            if action_type == "terminate":
                result = terminate_process(proc.pid, proc.name)
                if result.success and proc.pid in self._suspended_pids:
                    del self._suspended_pids[proc.pid]
            elif action_type == "suspend":
                result = suspend_process(proc.pid, proc.name)
                if result.success:
                    self._suspended_pids[proc.pid] = proc.name
            else:
                continue

            result.reason = reason_detail
            actions.append(result)

        if actions:
            succeeded = sum(1 for a in actions if a.success)
            logger.info(
                f"Memory optimization: {succeeded}/{len(actions)} actions succeeded"
            )

        return actions

    @property
    def suspended_processes(self) -> dict:
        """Return dict of currently suspended PIDs -> names."""
        return self._suspended_pids.copy()

    def flush_working_sets(self, ram_percent: float = 0.0) -> int:
        """Flush working sets of non-protected processes using EmptyWorkingSet.

        This reclaims cached RAM pages without killing processes.
        Safe operation that gives immediate RAM reduction.

        Args:
            ram_percent: Current RAM usage (0-100). Only flushes if > 60%.

        Returns:
            Number of processes whose working sets were flushed.
        """
        if not self._config.working_set_flush:
            return 0
        if ram_percent < 60:
            return 0

        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
        except OSError:
            logger.warning("Could not load kernel32/psapi for working set flush")
            return 0
            
        # Refresh lists and process tree mapping to catch newly spawned children
        self._lists.reload()

        PROCESS_QUERY_INFORMATION = 0x0400
        PROCESS_SET_QUOTA = 0x0100

        flushed = 0
        import psutil

        for proc in psutil.process_iter(["pid", "name"]):
            try:
                pid = proc.info["pid"]
                name = (proc.info["name"] or "").lower()

                # Skip protected processes
                dummy = ProcessInfo(pid=pid, name=name, is_foreground=False)
                if self._lists.is_protected(dummy):
                    continue

                # Skip PID 0 and 4 (System)
                if pid in (0, 4):
                    continue

                # Open process with required access
                handle = kernel32.OpenProcess(
                    PROCESS_QUERY_INFORMATION | PROCESS_SET_QUOTA, False, pid
                )
                if not handle:
                    continue

                # EmptyWorkingSet forces pages out of RAM to page file
                result = psapi.EmptyWorkingSet(handle)
                kernel32.CloseHandle(handle)

                if result:
                    flushed += 1

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            except Exception:
                continue

        if flushed > 0:
            logger.info(f"💨 Flushed working sets of {flushed} processes")

        return flushed
