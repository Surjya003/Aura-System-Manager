"""
Usage Tracker
=============
Logs per-process usage events to a SQLite database for historical analysis
and heuristic learning.
"""

import os
import sqlite3
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from core.config import Config
from models.telemetry_models import ProcessInfo
from utils.logger import get_logger

logger = get_logger()

_DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    app_name TEXT NOT NULL,
    exe_path TEXT NOT NULL,
    timestamp REAL NOT NULL,
    cpu_avg REAL DEFAULT 0.0,
    mem_avg REAL DEFAULT 0.0,
    gpu_avg REAL DEFAULT 0.0,
    duration_seconds REAL DEFAULT 0.0,
    was_foreground INTEGER DEFAULT 0,
    category TEXT DEFAULT 'unknown'
);

CREATE INDEX IF NOT EXISTS idx_app_name ON usage_events(app_name);
CREATE INDEX IF NOT EXISTS idx_timestamp ON usage_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_exe_path ON usage_events(exe_path);
"""


class UsageTracker:
    """Tracks process usage history in a SQLite database."""

    def __init__(self, config: Config = None):
        self._config = config or Config()
        db_dir = self._config.data_dir
        os.makedirs(db_dir, exist_ok=True)
        self._db_path = os.path.join(db_dir, "usage_history.db")
        self._conn: Optional[sqlite3.Connection] = None
        self._active_sessions: Dict[int, dict] = {}  # pid -> session data
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the SQLite database and create tables."""
        try:
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.executescript(_DB_SCHEMA)
            self._conn.commit()
            logger.debug(f"Usage database initialized: {self._db_path}")
        except sqlite3.Error as e:
            logger.error(f"Failed to initialize usage database: {e}")

    def start_session(self, process: ProcessInfo, category: str = "unknown") -> None:
        """Mark the start of a process usage session."""
        self._active_sessions[process.pid] = {
            "app_name": process.name_lower,
            "exe_path": process.exe_path,
            "start_time": time.time(),
            "cpu_samples": [process.cpu_percent],
            "mem_samples": [process.memory_mb],
            "gpu_samples": [0.0],
            "was_foreground": process.is_foreground,
            "category": category,
        }

    def update_session(self, process: ProcessInfo) -> None:
        """Update an ongoing session with new resource samples."""
        session = self._active_sessions.get(process.pid)
        if session is None:
            self.start_session(process)
            return

        session["cpu_samples"].append(process.cpu_percent)
        session["mem_samples"].append(process.memory_mb)
        if process.is_foreground:
            session["was_foreground"] = True

    def end_session(self, pid: int) -> None:
        """End a session and persist it to the database."""
        session = self._active_sessions.pop(pid, None)
        if session is None:
            return

        duration = time.time() - session["start_time"]
        if duration < 5:  # Skip very short sessions
            return

        cpu_avg = sum(session["cpu_samples"]) / len(session["cpu_samples"])
        mem_avg = sum(session["mem_samples"]) / len(session["mem_samples"])
        gpu_avg = sum(session["gpu_samples"]) / len(session["gpu_samples"])

        self._insert_event(
            app_name=session["app_name"],
            exe_path=session["exe_path"],
            timestamp=session["start_time"],
            cpu_avg=cpu_avg,
            mem_avg=mem_avg,
            gpu_avg=gpu_avg,
            duration=duration,
            was_foreground=session["was_foreground"],
            category=session["category"],
        )

    def _insert_event(self, **kwargs) -> None:
        """Insert a usage event into the database."""
        if self._conn is None:
            return
        try:
            self._conn.execute(
                """INSERT INTO usage_events
                   (app_name, exe_path, timestamp, cpu_avg, mem_avg, gpu_avg,
                    duration_seconds, was_foreground, category)
                   VALUES (:app_name, :exe_path, :timestamp, :cpu_avg, :mem_avg,
                           :gpu_avg, :duration, :was_foreground, :category)""",
                kwargs,
            )
            self._conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to insert usage event: {e}")

    def update_active_processes(self, current_processes: List[ProcessInfo]) -> None:
        """Update tracking for all currently running processes.

        - New processes get sessions started
        - Existing processes get samples updated
        - Processes that have exited get sessions ended
        """
        current_pids = {p.pid for p in current_processes}

        # End sessions for processes that have exited
        ended_pids = [pid for pid in self._active_sessions if pid not in current_pids]
        for pid in ended_pids:
            self.end_session(pid)

        # Update or start sessions for current processes
        for proc in current_processes:
            if proc.pid in self._active_sessions:
                self.update_session(proc)
            else:
                self.start_session(proc)

    def get_app_history(
        self, app_name: str, limit: int = 100
    ) -> List[dict]:
        """Get usage history for a specific application."""
        if self._conn is None:
            return []
        try:
            cursor = self._conn.execute(
                """SELECT app_name, exe_path, timestamp, cpu_avg, mem_avg,
                          gpu_avg, duration_seconds, was_foreground, category
                   FROM usage_events
                   WHERE app_name = ?
                   ORDER BY timestamp DESC
                   LIMIT ?""",
                (app_name.lower(), limit),
            )
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        except sqlite3.Error:
            return []

    def get_all_app_stats(self) -> List[dict]:
        """Get aggregated statistics for all tracked applications."""
        if self._conn is None:
            return []
        try:
            cursor = self._conn.execute(
                """SELECT app_name,
                          COUNT(*) as session_count,
                          AVG(cpu_avg) as avg_cpu,
                          AVG(mem_avg) as avg_mem,
                          AVG(gpu_avg) as avg_gpu,
                          SUM(duration_seconds) as total_duration,
                          AVG(was_foreground) as foreground_ratio
                   FROM usage_events
                   GROUP BY app_name
                   ORDER BY session_count DESC"""
            )
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        except sqlite3.Error:
            return []

    def get_total_events(self) -> int:
        """Return total number of tracked events."""
        if self._conn is None:
            return 0
        try:
            cursor = self._conn.execute("SELECT COUNT(*) FROM usage_events")
            return cursor.fetchone()[0]
        except sqlite3.Error:
            return 0

    def close(self) -> None:
        """End all active sessions and close the database."""
        for pid in list(self._active_sessions.keys()):
            self.end_session(pid)
        if self._conn:
            self._conn.close()
            self._conn = None
