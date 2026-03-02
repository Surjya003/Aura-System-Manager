"""
Process Usefulness Analyzer
=============================
Scores every running process on a 0-100 "usefulness" scale by combining
multiple signals:

  - Is it the foreground app? (user is actively using it)
  - Is it a system-critical process? (needed for Windows to function)
  - Is it a known user application vs. background bloat?
  - How much CPU is it actually using? (idle = less useful)
  - How long has it been running with zero activity?
  - Has the user interacted with it recently? (usage tracker data)
  - Is it a known bloatware / telemetry / updater process?

Processes scoring below the "junk threshold" are candidates for cleanup.
"""

import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple

from core.app_classifier import AppClassifier, AppCategory
from core.config import Config
from core.lists_manager import ListsManager
from core.priority_predictor import PriorityPredictor, PriorityLevel
from models.telemetry_models import ProcessInfo
from utils.logger import get_logger

logger = get_logger()


class Verdict(Enum):
    """Final verdict on a process."""
    ESSENTIAL = "essential"         # System-critical, never touch
    ACTIVE = "active"               # User is actively using it
    USEFUL = "useful"               # Doing real work in the background
    IDLE = "idle"                   # Not doing much but might be needed
    BLOAT = "bloat"                 # Waste of resources — cleanup candidate
    JUNK = "junk"                   # Confirmed useless — should be killed


@dataclass
class ProcessScore:
    """Detailed usefulness score for a process."""
    pid: int
    name: str
    score: float              # 0–100 (higher = more useful)
    verdict: Verdict
    reasons: List[str]        # Human-readable explanations
    memory_mb: float
    cpu_percent: float
    reclaimable_mb: float     # Estimated memory freed if killed

    @property
    def is_cleanup_candidate(self) -> bool:
        return self.verdict in (Verdict.BLOAT, Verdict.JUNK)


# ── Known bloatware / telemetry / updater patterns ───────────────────────────
# These are confirmed useless background processes that waste resources.
_KNOWN_BLOAT: Set[str] = {
    # Microsoft bloat
    "gamebar.exe", "gamebarpresencewriter.exe", "gamebarftserver.exe",
    "yourphone.exe", "phoneexperiencehost.exe",
    "cortana.exe", "searchapp.exe",
    "microsoftedgeupdate.exe", "msedgewebview2.exe",
    "officeclicktorun.exe", "officec2rclient.exe",
    "skypeapp.exe", "skypebackgroundhost.exe",
    "peopleapp.exe", "windowscommunicationsapps.exe",
    "gamingservices.exe", "gamingservicesnet.exe",
    # Update services (not critical)
    "googleupdate.exe", "googledrivesync.exe",
    "adobearm.exe", "adobeipcbroker.exe",
    "ccxprocess.exe", "cfenotify.exe",
    "crashpad_handler.exe",
    "software_reporter_tool.exe",
    "jusched.exe", "jucheck.exe",
    # Telemetry
    "compattelrunner.exe", "devicecensus.exe",
    "diagtrack.exe", "dismhost.exe",
    "microsoftedgeelevationservice.exe",
    "windowsinternal.composableshell.exe",
    # OEM bloat (common)
    "hpcommrecovery.exe", "hpsupportassistant.exe",
    "lenovo.modern.imcontroller.exe",
    "mcafee.exe", "mcshield.exe",
    "aswidsagent.exe",  # Avast
}

# Processes that look like services/system but are actually user apps
_USER_APP_PATTERNS: Set[str] = {
    "chrome.exe", "firefox.exe", "msedge.exe", "opera.exe", "brave.exe",
    "code.exe", "devenv.exe", "idea64.exe", "pycharm64.exe",
    "slack.exe", "discord.exe", "teams.exe", "telegram.exe",
    "spotify.exe", "steam.exe", "epicgameslauncher.exe",
    "obs64.exe", "obs.exe",
    "blender.exe", "photoshop.exe", "gimp.exe",
    "notepad++.exe", "sublime_text.exe",
    "winword.exe", "excel.exe", "powerpnt.exe",
    "vlc.exe", "mpv.exe", "potplayer.exe",
}

# Idle watchers — processes that are typically idle and waste memory
_IDLE_WASTERS: Set[str] = {
    "onedrive.exe",
    "dropbox.exe",
    "googledrivefs.exe",
    "icloud.exe",
    "crashpad_handler.exe",
    "backgroundtransferhost.exe",
    "microsoft.photos.exe",
    "paintstudio.view.exe",
    "video.ui.exe",
    "calculator.exe",
    "windowsterminal.exe",
}


class ProcessAnalyzer:
    """Scores every process on usefulness (0–100).

    Integrates signals from:
    - ListsManager (whitelist/blacklist/critical)
    - AppClassifier (graphic/compute/light/background)
    - PriorityPredictor (ML priority: high/medium/low)
    - Live resource metrics (CPU, memory, threads)
    - Known bloat/telemetry databases
    """

    def __init__(
        self,
        config: Config,
        lists_mgr: ListsManager,
        classifier: AppClassifier,
        predictor: PriorityPredictor,
    ):
        self._config = config
        self._lists = lists_mgr
        self._classifier = classifier
        self._predictor = predictor
        self._idle_tracker: Dict[int, float] = {}  # pid -> first_seen_idle_time

    def analyze_all(
        self, processes: List[ProcessInfo]
    ) -> List[ProcessScore]:
        """Score all processes and return sorted by usefulness (ascending).

        The least useful processes come first — those are cleanup candidates.
        """
        scores = []
        for proc in processes:
            score = self._score_process(proc)
            scores.append(score)

        # Sort: junk/bloat first (lowest score), essential last
        scores.sort(key=lambda s: s.score)
        return scores

    def get_cleanup_candidates(
        self, processes: List[ProcessInfo], ram_pressure: float = 0.0
    ) -> List[Tuple[ProcessScore, str]]:
        """Get processes that should be cleaned up, with recommended action.

        Args:
            processes: All running processes.
            ram_pressure: Current RAM usage percent (0–100).
                If above 70%, more aggressive cleanup.

        Returns:
            List of (ProcessScore, action) tuples where action is
            "terminate" or "suspend".
        """
        all_scores = self.analyze_all(processes)
        candidates = []

        aggressive = self._config.aggressive_cleanup

        # Determine aggressiveness based on RAM pressure
        if ram_pressure >= 85:
            junk_threshold = 50  # Very aggressive — clean anything below 50
        elif ram_pressure >= 75:
            junk_threshold = 40  # Aggressive — clean below 40
        elif ram_pressure >= 65:
            junk_threshold = 30  # Moderate — clean below 30
        else:
            junk_threshold = 15  # Minimal — only obvious bloat

        for score in all_scores:
            # Always skip essential/active processes
            if score.verdict in (Verdict.ESSENTIAL, Verdict.ACTIVE):
                continue

            # Standard cleanup: BLOAT and JUNK
            if score.is_cleanup_candidate and score.score <= junk_threshold:
                # ONLY terminate if it's confirmed bloat/blacklisted (score <= 10)
                # Otherwise, always suspend to prevent app crashes
                if score.verdict == Verdict.JUNK and score.score <= 10:
                    action = "terminate"
                else:
                    action = "suspend"
                candidates.append((score, action))
                continue

            # Aggressive mode: also suspend IDLE processes using significant RAM
            if aggressive and ram_pressure >= 70:
                if score.verdict == Verdict.IDLE and score.memory_mb >= 150:
                    candidates.append((score, "suspend"))
                    continue

            # Under extreme pressure, suspend even USEFUL non-foreground background processes
            if aggressive and ram_pressure >= 90:
                if score.verdict == Verdict.USEFUL and score.memory_mb >= 200:
                    if score.score < 65:  # Not strongly useful
                        candidates.append((score, "suspend"))

        # Cap at max_suspensions from config
        max_actions = self._config.max_suspensions
        return candidates[:max_actions]

    def _score_process(self, proc: ProcessInfo) -> ProcessScore:
        """Score a single process on usefulness (0–100)."""
        score = 50.0  # Start neutral
        reasons = []
        name_lower = proc.name_lower

        # ── Signal 1: System-critical? (Instant ESSENTIAL) ───────────────
        if self._lists.is_protected(proc):
            return ProcessScore(
                pid=proc.pid, name=proc.name, score=100.0,
                verdict=Verdict.ESSENTIAL,
                reasons=["System-critical / whitelisted process"],
                memory_mb=proc.memory_mb, cpu_percent=proc.cpu_percent,
                reclaimable_mb=0.0,
            )

        # ── Signal 2: Foreground app? (User is actively using it) ────────
        if proc.is_foreground:
            score = 95.0
            reasons.append("Foreground app (user is actively using it)")
            return ProcessScore(
                pid=proc.pid, name=proc.name, score=score,
                verdict=Verdict.ACTIVE, reasons=reasons,
                memory_mb=proc.memory_mb, cpu_percent=proc.cpu_percent,
                reclaimable_mb=0.0,
            )

        # ── Signal 3: Known bloatware? ───────────────────────────────────
        if name_lower in _KNOWN_BLOAT or self._lists.is_blacklisted(proc):
            score = 5.0
            reasons.append("Known bloatware / blacklisted process")
            return ProcessScore(
                pid=proc.pid, name=proc.name, score=score,
                verdict=Verdict.JUNK, reasons=reasons,
                memory_mb=proc.memory_mb, cpu_percent=proc.cpu_percent,
                reclaimable_mb=proc.memory_mb,
            )

        # ── Signal 4: App category ───────────────────────────────────────
        category = self._classifier.classify(proc)
        if category == AppCategory.GRAPHIC_INTENSIVE:
            score += 20
            reasons.append("Graphic-intensive app (game/renderer/editor)")
        elif category == AppCategory.COMPUTE_HEAVY:
            score += 15
            reasons.append("Compute-heavy app (compiler/encoder)")
        elif category == AppCategory.LIGHT:
            score += 10
            reasons.append("Light user app (editor/chat/browser)")
        elif category == AppCategory.BACKGROUND:
            score -= 15
            reasons.append("Background process (service/updater)")

        # ── Signal 5: Is it a known user application? ────────────────────
        if name_lower in _USER_APP_PATTERNS:
            score += 15
            reasons.append("Known user application")

        # ── Signal 6: CPU activity (is it actually doing anything?) ──────
        if proc.cpu_percent > 5.0:
            score += 15
            reasons.append(f"Actively using CPU ({proc.cpu_percent:.1f}%)")
        elif proc.cpu_percent > 1.0:
            score += 5
            reasons.append(f"Light CPU activity ({proc.cpu_percent:.1f}%)")
        else:
            score -= 10
            reasons.append("Zero CPU activity (completely idle)")
            # Track how long it's been idle
            if proc.pid not in self._idle_tracker:
                self._idle_tracker[proc.pid] = time.time()
            idle_seconds = time.time() - self._idle_tracker[proc.pid]
            if idle_seconds > 300:  # Idle for 5+ minutes
                score -= 10
                reasons.append(f"Idle for {idle_seconds/60:.0f} minutes")
            if idle_seconds > 900:  # Idle for 15+ minutes
                score -= 10
                reasons.append("Long idle period — likely unused")
        # Reset idle tracker if CPU active
        if proc.cpu_percent > 1.0 and proc.pid in self._idle_tracker:
            del self._idle_tracker[proc.pid]

        # ── Signal 7: Memory usage (bloated?) ────────────────────────────────────
        threshold = self._config.memory_threshold_mb
        if proc.memory_mb > threshold * 3:
            score -= 25
            reasons.append(f"Extreme memory ({proc.memory_mb:.0f}MB > {threshold*3}MB)")
        elif proc.memory_mb > threshold * 2:
            score -= 18
            reasons.append(f"Very high memory ({proc.memory_mb:.0f}MB > {threshold*2}MB)")
        elif proc.memory_mb > threshold:
            score -= 12
            reasons.append(f"High memory ({proc.memory_mb:.0f}MB > {threshold}MB)")
        elif proc.memory_mb < 10:
            score += 5  # Tiny footprint, not worth killing
            reasons.append("Tiny memory footprint")

        # ── Signal 8: ML priority prediction ─────────────────────────────
        try:
            priority = self._predictor.predict(proc.name_lower)
            if priority == PriorityLevel.HIGH:
                score += 15
                reasons.append("ML model: HIGH priority (frequently used)")
            elif priority == PriorityLevel.LOW:
                score -= 10
                reasons.append("ML model: LOW priority (rarely used)")
        except Exception:
            pass  # No model available yet

        # ── Signal 9: Known idle waster? ─────────────────────────────────
        if name_lower in _IDLE_WASTERS and proc.cpu_percent < 1.0:
            score -= 10
            reasons.append("Known idle background app (minimal activity)")

        # ── Signal 10: Thread count (proxy for complexity) ───────────────
        if proc.num_threads > 50:
            score += 5
            reasons.append(f"Complex process ({proc.num_threads} threads)")
        elif proc.num_threads <= 2:
            score -= 3
            reasons.append("Simple process (few threads)")

        # ── Clamp and determine verdict ────────────────────────────────────
        score = max(0.0, min(100.0, score))

        if score >= 70:
            verdict = Verdict.USEFUL
        elif score >= 35:
            verdict = Verdict.IDLE
        elif score >= 15:
            verdict = Verdict.BLOAT
        else:
            verdict = Verdict.JUNK

        # Reclaimable for anything that's not USEFUL or ESSENTIAL
        reclaimable = proc.memory_mb if verdict in (Verdict.BLOAT, Verdict.JUNK, Verdict.IDLE) else 0.0

        return ProcessScore(
            pid=proc.pid, name=proc.name, score=score,
            verdict=verdict, reasons=reasons,
            memory_mb=proc.memory_mb, cpu_percent=proc.cpu_percent,
            reclaimable_mb=reclaimable,
        )

    def get_total_reclaimable(self, processes: List[ProcessInfo]) -> float:
        """Estimate total MB that could be freed by cleaning junk."""
        scores = self.analyze_all(processes)
        return sum(s.reclaimable_mb for s in scores if s.is_cleanup_candidate)

    def cleanup_idle_tracker(self, current_pids: set):
        """Remove dead PIDs from the idle tracker."""
        dead = [pid for pid in self._idle_tracker if pid not in current_pids]
        for pid in dead:
            del self._idle_tracker[pid]
