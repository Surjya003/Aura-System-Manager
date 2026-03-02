"""
Application Classifier
======================
Classifies running applications by their nature — graphic-intensive, compute-heavy,
light, or background — using heuristic rules and configurable app databases.
"""

from enum import Enum
from typing import Dict, Optional

from core.config import Config
from models.telemetry_models import ProcessInfo
from utils.logger import get_logger

logger = get_logger()


class AppCategory(Enum):
    """Application category for hardware routing decisions."""
    GRAPHIC_INTENSIVE = "graphic_intensive"   # Games, renderers, video editors
    COMPUTE_HEAVY = "compute_heavy"           # Compilers, ML training, encoding
    LIGHT = "light"                           # Text editors, browsers (normal), chat
    BACKGROUND = "background"                 # Services, updaters, telemetry


# ── Known application patterns ──────────────────────────────────────────────

_GRAPHIC_PATTERNS = {
    "blender", "photoshop", "afterfx", "premiere", "davinci",
    "obs64", "obs32", "unity", "unrealengine", "ue4editor",
    "godot", "steam", "epicgameslauncher", "csgo", "valorant",
    "fortnite", "minecraft", "javaw",  # Minecraft uses javaw
    "gimp", "krita", "paintshoppro", "3dsmax", "maya",
    "cinema4d", "nuke", "houdini", "vlc", "mpv",
    "mpc-hc64", "potplayer", "handbrake",
}

_COMPUTE_PATTERNS = {
    "python", "python3", "pythonw", "node", "java",
    "gcc", "g++", "cl", "msbuild", "devenv",
    "docker", "wsl", "pwsh", "powershell",
    "ffmpeg", "7z", "winrar", "cmake",
    "cargo", "rustc", "go", "dotnet",
}

_LIGHT_PATTERNS = {
    "notepad", "notepad++", "code", "sublime_text",
    "wordpad", "winword", "excel", "powerpnt",
    "outlook", "thunderbird", "teams", "slack",
    "discord", "telegram", "whatsapp", "signal",
    "calc", "mspaint", "snippingtool",
}


class AppClassifier:
    """Classifies applications for CPU/GPU routing decisions."""

    def __init__(self, config: Config = None):
        self._config = config or Config()
        self._custom_cache: Dict[str, AppCategory] = {}
        self._build_custom_mappings()

    def _build_custom_mappings(self) -> None:
        """Build custom mappings from config GPU lists."""
        for app in self._config.high_performance_apps:
            base = app.lower().replace(".exe", "")
            self._custom_cache[base] = AppCategory.GRAPHIC_INTENSIVE

        for app in self._config.power_saving_apps:
            base = app.lower().replace(".exe", "")
            self._custom_cache[base] = AppCategory.LIGHT

    def classify(self, process: ProcessInfo) -> AppCategory:
        """Classify a process into an application category.

        Uses a priority system:
        1. Custom config mappings
        2. Known app pattern matching
        3. Heuristic analysis (CPU%, memory, thread count)
        4. Default to BACKGROUND
        """
        base_name = process.name_lower.replace(".exe", "")

        # 1. Custom mappings from config
        if base_name in self._custom_cache:
            return self._custom_cache[base_name]

        # 2. Known patterns
        if base_name in _GRAPHIC_PATTERNS:
            return AppCategory.GRAPHIC_INTENSIVE
        if base_name in _COMPUTE_PATTERNS:
            return AppCategory.COMPUTE_HEAVY
        if base_name in _LIGHT_PATTERNS:
            return AppCategory.LIGHT

        # 3. Heuristic based on resource usage
        return self._heuristic_classify(process)

    def _heuristic_classify(self, process: ProcessInfo) -> AppCategory:
        """Fallback heuristic classification based on resource usage."""
        # Foreground + high memory/CPU → likely important
        if process.is_foreground:
            if process.cpu_percent > 30 or process.memory_mb > 500:
                return AppCategory.GRAPHIC_INTENSIVE
            if process.cpu_percent > 10:
                return AppCategory.COMPUTE_HEAVY
            return AppCategory.LIGHT

        # Background process with high compute
        if process.cpu_percent > 50:
            return AppCategory.COMPUTE_HEAVY

        # Everything else is background
        return AppCategory.BACKGROUND

    def get_category_label(self, category: AppCategory) -> str:
        """Human-readable label for a category."""
        labels = {
            AppCategory.GRAPHIC_INTENSIVE: "🎮 Graphic Intensive",
            AppCategory.COMPUTE_HEAVY: "⚙️ Compute Heavy",
            AppCategory.LIGHT: "📝 Light",
            AppCategory.BACKGROUND: "💤 Background",
        }
        return labels.get(category, "❓ Unknown")
