"""
Configuration Manager
=====================
Loads, validates, and provides access to config.yaml settings.
Supports hot-reload by watching file modification time.
"""

import os
import time
from typing import Any, Dict, List, Optional

import yaml


_DEFAULT_CONFIG = {
    "general": {
        "scan_interval_seconds": 5,
        "log_level": "INFO",
        "log_file": "logs/optimizer.log",
        "data_dir": "data",
    },
    "memory": {
        "threshold_mb": 200,
        "default_action": "suspend",
        "max_suspensions": 30,
        "auto_mode": True,
        "aggressive_cleanup": True,
        "working_set_flush": True,
    },
    "cpu": {
        "performance_cores": [0, 1, 2, 3],
        "efficiency_cores": [4, 5, 6, 7],
        "enabled": True,
    },
    "gpu": {
        "enabled": True,
        "high_performance_apps": [],
        "power_saving_apps": [],
    },
    "dashboard": {
        "refresh_rate_seconds": 1,
        "top_processes": 15,
    },
    "learning": {
        "min_samples": 50,
        "retrain_interval_hours": 24,
        "model_path": "data/priority_model.joblib",
    },
    "whitelist": [
        "svchost.exe", "csrss.exe", "lsass.exe", "smss.exe",
        "services.exe", "wininit.exe", "winlogon.exe", "explorer.exe",
        "dwm.exe", "system",
    ],
    "blacklist": [],
}


class Config:
    """Singleton configuration manager with hot-reload support."""

    _instance: Optional["Config"] = None

    def __new__(cls, config_path: str = "config.yaml") -> "Config":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config_path: str = "config.yaml") -> None:
        if self._initialized:
            return
        self._config_path = os.path.abspath(config_path)
        self._data: Dict[str, Any] = {}
        self._last_mtime: float = 0.0
        self._load()
        self._initialized = True

    def _load(self) -> None:
        """Load configuration from YAML file, merging with defaults."""
        self._data = dict(_DEFAULT_CONFIG)  # shallow copy of defaults

        if os.path.exists(self._config_path):
            with open(self._config_path, "r", encoding="utf-8") as f:
                user_cfg = yaml.safe_load(f) or {}
            self._deep_merge(self._data, user_cfg)
            self._last_mtime = os.path.getmtime(self._config_path)

        # Ensure data directory exists
        data_dir = self._data["general"]["data_dir"]
        os.makedirs(data_dir, exist_ok=True)

    def _deep_merge(self, base: dict, override: dict) -> None:
        """Recursively merge override dict into base dict."""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value

    def reload_if_changed(self) -> bool:
        """Reload config if the file has been modified since last load.

        Returns:
            True if the config was reloaded, False otherwise.
        """
        if not os.path.exists(self._config_path):
            return False
        current_mtime = os.path.getmtime(self._config_path)
        if current_mtime > self._last_mtime:
            self._data = dict(_DEFAULT_CONFIG)
            self._load()
            return True
        return False

    # ── Typed accessors ─────────────────────────────────────────────────

    def get(self, section: str, key: Optional[str] = None, default: Any = None) -> Any:
        """Get a config value by section and optional key."""
        section_data = self._data.get(section, {})
        if key is None:
            return section_data
        if isinstance(section_data, dict):
            return section_data.get(key, default)
        return default

    @property
    def scan_interval(self) -> int:
        return self.get("general", "scan_interval_seconds", 5)

    @property
    def log_level(self) -> str:
        return self.get("general", "log_level", "INFO")

    @property
    def log_file(self) -> str:
        return self.get("general", "log_file", "logs/optimizer.log")

    @property
    def memory_threshold_mb(self) -> int:
        return self.get("memory", "threshold_mb", 500)

    @property
    def memory_action(self) -> str:
        return self.get("memory", "default_action", "suspend")

    @property
    def max_suspensions(self) -> int:
        return self.get("memory", "max_suspensions", 10)

    @property
    def auto_mode(self) -> bool:
        return self.get("memory", "auto_mode", True)

    @property
    def aggressive_cleanup(self) -> bool:
        return self.get("memory", "aggressive_cleanup", True)

    @property
    def working_set_flush(self) -> bool:
        return self.get("memory", "working_set_flush", True)

    @property
    def performance_cores(self) -> List[int]:
        return self.get("cpu", "performance_cores", [0, 1, 2, 3])

    @property
    def efficiency_cores(self) -> List[int]:
        return self.get("cpu", "efficiency_cores", [4, 5, 6, 7])

    @property
    def cpu_routing_enabled(self) -> bool:
        return self.get("cpu", "enabled", True)

    @property
    def gpu_routing_enabled(self) -> bool:
        return self.get("gpu", "enabled", True)

    @property
    def whitelist(self) -> List[str]:
        return self.get("whitelist", default=[])

    @property
    def blacklist(self) -> List[str]:
        return self.get("blacklist", default=[])

    @property
    def dashboard_refresh(self) -> int:
        return self.get("dashboard", "refresh_rate_seconds", 1)

    @property
    def top_processes_count(self) -> int:
        return self.get("dashboard", "top_processes", 15)

    @property
    def data_dir(self) -> str:
        return self.get("general", "data_dir", "data")

    @property
    def model_path(self) -> str:
        return self.get("learning", "model_path", "data/priority_model.joblib")

    @property
    def min_learning_samples(self) -> int:
        return self.get("learning", "min_samples", 50)

    @property
    def retrain_interval_hours(self) -> int:
        return self.get("learning", "retrain_interval_hours", 24)

    @property
    def high_performance_apps(self) -> List[str]:
        return self.get("gpu", "high_performance_apps", [])

    @property
    def power_saving_apps(self) -> List[str]:
        return self.get("gpu", "power_saving_apps", [])

    def __repr__(self) -> str:
        return f"Config(path={self._config_path!r}, sections={list(self._data.keys())})"
