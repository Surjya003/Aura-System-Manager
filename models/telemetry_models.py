"""
Telemetry Data Models
=====================
Dataclasses representing system snapshots, process info, and hardware metrics.
"""

from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime


@dataclass
class MemoryInfo:
    """System memory information."""
    total_mb: float
    available_mb: float
    used_mb: float
    percent: float


@dataclass
class CpuCoreInfo:
    """Per-core CPU usage."""
    core_id: int
    usage_percent: float
    frequency_mhz: float = 0.0


@dataclass
class GpuInfo:
    """GPU information."""
    id: int
    name: str
    load_percent: float
    memory_total_mb: float
    memory_used_mb: float
    memory_free_mb: float
    temperature: float = 0.0


@dataclass
class ProcessInfo:
    """Information about a running process."""
    pid: int
    name: str
    exe_path: str = ""
    memory_mb: float = 0.0
    cpu_percent: float = 0.0
    status: str = "running"
    num_threads: int = 0
    is_foreground: bool = False
    create_time: float = 0.0

    @property
    def name_lower(self) -> str:
        return self.name.lower()


@dataclass
class OptimizationAction:
    """A recommended or executed optimization action."""
    pid: int
    process_name: str
    action: str  # "terminate", "suspend", "set_affinity", "set_gpu"
    reason: str
    timestamp: datetime = field(default_factory=datetime.now)
    success: bool = False
    detail: str = ""


@dataclass
class SystemSnapshot:
    """Complete system state at a point in time."""
    timestamp: datetime
    memory: MemoryInfo
    cpu_cores: List[CpuCoreInfo]
    cpu_overall_percent: float
    gpus: List[GpuInfo]
    processes: List[ProcessInfo]
    foreground_pid: Optional[int] = None
    total_processes: int = 0
    cpu_temperature_c: float = 0.0
    fan_speed_percent: float = 0.0

    @property
    def cpu_core_count(self) -> int:
        return len(self.cpu_cores)

    @property
    def has_gpu(self) -> bool:
        return len(self.gpus) > 0
