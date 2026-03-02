"""
Real-Time Terminal Dashboard
=============================
Live system telemetry dashboard using Rich library with auto-refreshing panels
for RAM, CPU, GPU, top processes, and recent optimization actions.
"""

from datetime import datetime
from typing import List, Optional

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Table
from rich.text import Text

from core.config import Config
from models.telemetry_models import SystemSnapshot, OptimizationAction


console = Console()


def _color_for_percent(pct: float) -> str:
    """Return a color name based on a utilization percentage."""
    if pct < 50:
        return "green"
    elif pct < 80:
        return "yellow"
    return "red"


def _bar(pct: float, width: int = 20) -> str:
    """Create a simple text-based progress bar."""
    filled = int(pct / 100 * width)
    empty = width - filled
    color = _color_for_percent(pct)
    return f"[{color}]{'█' * filled}{'░' * empty}[/{color}] {pct:5.1f}%"


def build_header() -> Panel:
    """Build the dashboard header."""
    title = Text("⚡ Intelligent System Resource Optimizer", style="bold cyan")
    subtitle = Text(
        f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        style="dim white",
    )
    content = Text.assemble(title, subtitle)
    return Panel(content, style="bold blue", height=3)


def build_memory_panel(snapshot: SystemSnapshot) -> Panel:
    """Build the RAM usage panel."""
    mem = snapshot.memory
    bar = _bar(mem.percent)

    content = (
        f"  Total:     {mem.total_mb:,.0f} MB\n"
        f"  Used:      {mem.used_mb:,.0f} MB\n"
        f"  Available: {mem.available_mb:,.0f} MB\n"
        f"  Usage:     {bar}"
    )
    return Panel(content, title="🧠 RAM", border_style="cyan", height=7)


def build_cpu_panel(snapshot: SystemSnapshot) -> Panel:
    """Build the per-core CPU usage panel."""
    lines = []
    for core in snapshot.cpu_cores:
        bar = _bar(core.usage_percent, width=15)
        freq = f"{core.frequency_mhz:,.0f}MHz" if core.frequency_mhz else ""
        lines.append(f"  Core {core.core_id:2d}: {bar}  {freq}")

    overall_bar = _bar(snapshot.cpu_overall_percent, width=15)
    lines.append(f"\n  Overall:  {overall_bar}")
    
    # Add temperature and fan speed
    lines.append(f"  Temp:     {snapshot.cpu_temperature_c:.1f}°C")
    lines.append(f"  Fan:      {snapshot.fan_speed_percent:.1f}%")

    return Panel("\n".join(lines), title="⚙️ CPU Cores & Hardware", border_style="yellow")


def build_gpu_panel(snapshot: SystemSnapshot) -> Panel:
    """Build the GPU usage panel."""
    if not snapshot.has_gpu:
        return Panel("  No GPU detected or GPUtil unavailable", title="🎮 GPU", border_style="magenta", height=5)

    lines = []
    for gpu in snapshot.gpus:
        load_bar = _bar(gpu.load_percent, width=15)
        vram_pct = (gpu.memory_used_mb / gpu.memory_total_mb * 100) if gpu.memory_total_mb > 0 else 0
        vram_bar = _bar(vram_pct, width=15)
        temp = f"  🌡️ {gpu.temperature:.0f}°C" if gpu.temperature else ""

        lines.append(f"  {gpu.name}")
        lines.append(f"  Load:  {load_bar}{temp}")
        lines.append(f"  VRAM:  {vram_bar}  ({gpu.memory_used_mb:.0f}/{gpu.memory_total_mb:.0f} MB)")
        lines.append("")

    return Panel("\n".join(lines), title="🎮 GPU", border_style="magenta")


def build_processes_table(snapshot: SystemSnapshot, top_n: int = 15) -> Panel:
    """Build the top processes table sorted by memory."""
    table = Table(
        show_header=True,
        header_style="bold white",
        expand=True,
        padding=(0, 1),
    )
    table.add_column("PID", style="dim", width=8, justify="right")
    table.add_column("Name", style="cyan", min_width=20)
    table.add_column("Memory", justify="right", width=10)
    table.add_column("CPU %", justify="right", width=8)
    table.add_column("Threads", justify="right", width=8)
    table.add_column("Status", width=10)
    table.add_column("FG", width=4, justify="center")

    for proc in snapshot.processes[:top_n]:
        fg_marker = "🟢" if proc.is_foreground else ""
        mem_color = _color_for_percent(min(proc.memory_mb / 10, 100))  # scale for color

        table.add_row(
            str(proc.pid),
            proc.name[:25],
            f"[{mem_color}]{proc.memory_mb:.0f} MB[/{mem_color}]",
            f"{proc.cpu_percent:.1f}",
            str(proc.num_threads),
            proc.status,
            fg_marker,
        )

    return Panel(table, title=f"📊 Top {top_n} Processes (by Memory)", border_style="green")


def build_actions_panel(actions: List[OptimizationAction], max_show: int = 8) -> Panel:
    """Build the recent optimization actions panel."""
    if not actions:
        return Panel("  No actions taken yet", title="🛠️ Recent Actions", border_style="red", height=5)

    lines = []
    for action in actions[-max_show:]:
        icon = "✅" if action.success else "❌"
        ts = action.timestamp.strftime("%H:%M:%S")
        lines.append(
            f"  {icon} [{ts}] {action.action.upper():10s} "
            f"{action.process_name[:20]:20s} — {action.detail}"
        )

    return Panel("\n".join(lines), title="🛠️ Recent Actions", border_style="red")


def build_dashboard(
    snapshot: SystemSnapshot,
    actions: List[OptimizationAction] = None,
    top_n: int = 15,
) -> Layout:
    """Assemble the full dashboard layout from component panels.

    Returns a Rich Layout ready for rendering.
    """
    layout = Layout()

    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=12),
    )

    # Header
    layout["header"].update(build_header())

    # Body: left sidebar (RAM + GPU) | right (CPU + processes)
    layout["body"].split_row(
        Layout(name="left", ratio=1),
        Layout(name="right", ratio=2),
    )

    # Left column: RAM on top, GPU on bottom
    layout["left"].split_column(
        Layout(name="memory", size=7),
        Layout(name="gpu"),
    )
    layout["memory"].update(build_memory_panel(snapshot))
    layout["gpu"].update(build_gpu_panel(snapshot))

    # Right column: CPU on top, processes on bottom
    layout["right"].split_column(
        Layout(name="cpu"),
        Layout(name="processes"),
    )
    layout["cpu"].update(build_cpu_panel(snapshot))
    layout["processes"].update(build_processes_table(snapshot, top_n))

    # Footer: recent actions
    layout["footer"].update(build_actions_panel(actions or []))

    return layout


class DashboardManager:
    """Manages the live-updating terminal dashboard."""

    def __init__(self, config: Config = None):
        self._config = config or Config()
        self._live: Optional[Live] = None
        self._actions: List[OptimizationAction] = []

    def start(self) -> Live:
        """Start the live dashboard. Returns the Live context for updating."""
        self._live = Live(
            console=console,
            refresh_per_second=1,
            screen=True,
        )
        self._live.start()
        return self._live

    def update(self, snapshot: SystemSnapshot) -> None:
        """Update the dashboard with a new system snapshot."""
        if self._live is None:
            return
        layout = build_dashboard(
            snapshot,
            actions=self._actions,
            top_n=self._config.top_processes_count,
        )
        self._live.update(layout)

    def add_actions(self, actions: List[OptimizationAction]) -> None:
        """Add optimization actions to the recent actions panel."""
        self._actions.extend(actions)
        # Keep only the last 50
        self._actions = self._actions[-50:]

    def stop(self) -> None:
        """Stop the live dashboard."""
        if self._live:
            self._live.stop()
            self._live = None
