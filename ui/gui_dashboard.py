"""
GUI Dashboard — Full Tkinter Interface
========================================
A modern dark-themed tkinter GUI that gives users full control over the
system optimizer: real-time metrics, sortable process table, kill/suspend
controls, whitelist/blacklist management, and an action log.

Replaces the terminal-only Rich dashboard with an interactive GUI.
"""

import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from datetime import datetime
from typing import List, Optional, Callable

from core.config import Config
from core.lists_manager import ListsManager
from models.telemetry_models import SystemSnapshot, ProcessInfo, OptimizationAction


# ── Color palette ────────────────────────────────────────────────────────────
_COLORS = {
    "bg":           "#1a1a2e",
    "bg_secondary": "#16213e",
    "bg_card":      "#0f3460",
    "accent":       "#e94560",
    "accent_green": "#00e676",
    "accent_yellow":"#ffd600",
    "accent_blue":  "#2979ff",
    "text":         "#eaeaea",
    "text_dim":     "#8892b0",
    "text_dark":    "#4a5568",
    "bar_bg":       "#2d2d44",
    "protected":    "#3a3a5c",
    "hog":          "#5c1a1a",
    "foreground":   "#1a3a1a",
    "border":       "#2a2a4a",
}


def _pct_color(pct: float) -> str:
    """Return a hex color for a utilization percentage."""
    if pct < 50:
        return _COLORS["accent_green"]
    elif pct < 80:
        return _COLORS["accent_yellow"]
    return _COLORS["accent"]


class GuiDashboard:
    """Full-featured tkinter GUI for the System Optimizer."""

    def __init__(self, config: Config, lists_mgr: ListsManager):
        self._config = config
        self._lists = lists_mgr
        self._running = True
        self._paused = False
        self._auto_mode = config.auto_mode
        self._snapshot: Optional[SystemSnapshot] = None
        self._actions: List[OptimizationAction] = []
        self._pending_actions: List[tuple] = []  # (ProcessInfo, action_type)
        self._start_time = datetime.now()
        self._analyzer = None  # Set via set_analyzer()

        # Callbacks set by the orchestrator
        self.on_kill_process: Optional[Callable] = None
        self.on_suspend_process: Optional[Callable] = None
        self.on_resume_process: Optional[Callable] = None
        self.on_add_whitelist: Optional[Callable] = None
        self.on_add_blacklist: Optional[Callable] = None
        self.on_threshold_change: Optional[Callable] = None
        self.on_auto_mode_change: Optional[Callable] = None

        self._build_window()

    def set_analyzer(self, analyzer):
        """Set the ProcessAnalyzer for smart verdict display."""
        self._analyzer = analyzer

    # ── Window Construction ──────────────────────────────────────────────

    def _build_window(self):
        self.root = tk.Tk()
        self.root.title("⚡ Intelligent System Resource Optimizer")
        self.root.geometry("1400x850")
        self.root.minsize(1100, 650)
        self.root.configure(bg=_COLORS["bg"])
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Configure ttk styles
        self._setup_styles()

        # ── Header ───────────────────────────────────────────────────────
        header = tk.Frame(self.root, bg=_COLORS["bg_secondary"], height=50)
        header.pack(fill=tk.X, padx=0, pady=0)
        header.pack_propagate(False)

        tk.Label(
            header, text="⚡ Intelligent System Resource Optimizer",
            font=("Segoe UI", 16, "bold"), fg=_COLORS["accent_blue"],
            bg=_COLORS["bg_secondary"]
        ).pack(side=tk.LEFT, padx=15, pady=10)

        self._status_label = tk.Label(
            header, text="● RUNNING", font=("Segoe UI", 11, "bold"),
            fg=_COLORS["accent_green"], bg=_COLORS["bg_secondary"]
        )
        self._status_label.pack(side=tk.RIGHT, padx=15)

        self._info_label = tk.Label(
            header, text="Processes: 0 | Uptime: 0:00:00",
            font=("Segoe UI", 10), fg=_COLORS["text_dim"],
            bg=_COLORS["bg_secondary"]
        )
        self._info_label.pack(side=tk.RIGHT, padx=15)

        # ── Main content area ────────────────────────────────────────────
        main_frame = tk.Frame(self.root, bg=_COLORS["bg"])
        main_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        # Left panel: metrics
        left_panel = tk.Frame(main_frame, bg=_COLORS["bg"], width=280)
        left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 4))
        left_panel.pack_propagate(False)
        self._build_metrics_panel(left_panel)

        # Right panel: controls
        right_panel = tk.Frame(main_frame, bg=_COLORS["bg"], width=260)
        right_panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(4, 0))
        right_panel.pack_propagate(False)
        self._build_controls_panel(right_panel)

        # Center: process table
        center_panel = tk.Frame(main_frame, bg=_COLORS["bg"])
        center_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4)
        self._build_process_table(center_panel)

        # ── Bottom: action log ───────────────────────────────────────────
        bottom_frame = tk.Frame(self.root, bg=_COLORS["bg"], height=160)
        bottom_frame.pack(fill=tk.X, padx=8, pady=(0, 8))
        bottom_frame.pack_propagate(False)
        self._build_action_log(bottom_frame)

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("Dark.TFrame", background=_COLORS["bg"])
        style.configure("Card.TFrame", background=_COLORS["bg_card"])
        style.configure(
            "Dark.TLabel", background=_COLORS["bg"],
            foreground=_COLORS["text"], font=("Segoe UI", 10)
        )
        style.configure(
            "CardTitle.TLabel", background=_COLORS["bg_card"],
            foreground=_COLORS["accent_blue"], font=("Segoe UI", 11, "bold")
        )

        # Treeview style
        style.configure(
            "Process.Treeview",
            background=_COLORS["bg_secondary"],
            foreground=_COLORS["text"],
            fieldbackground=_COLORS["bg_secondary"],
            font=("Consolas", 9),
            rowheight=24,
        )
        style.configure(
            "Process.Treeview.Heading",
            background=_COLORS["bg_card"],
            foreground=_COLORS["accent_blue"],
            font=("Segoe UI", 9, "bold"),
        )
        style.map("Process.Treeview", background=[("selected", _COLORS["accent_blue"])])

        # Button styles
        style.configure(
            "Action.TButton",
            background=_COLORS["bg_card"],
            foreground=_COLORS["text"],
            font=("Segoe UI", 9, "bold"),
            padding=(10, 5),
        )
        style.map("Action.TButton", background=[("active", _COLORS["accent"])])

        style.configure(
            "Danger.TButton",
            background=_COLORS["accent"],
            foreground="white",
            font=("Segoe UI", 9, "bold"),
            padding=(10, 5),
        )

        style.configure(
            "Success.TButton",
            background=_COLORS["accent_green"],
            foreground="black",
            font=("Segoe UI", 9, "bold"),
            padding=(10, 5),
        )

    # ── Metrics Panel (Left) ─────────────────────────────────────────────

    def _build_metrics_panel(self, parent):
        # RAM section
        ram_frame = self._card(parent, "🧠 RAM")
        self._ram_bar = self._metric_bar(ram_frame, "Usage")
        self._ram_detail = tk.Label(
            ram_frame, text="0 / 0 MB", font=("Consolas", 9),
            fg=_COLORS["text_dim"], bg=_COLORS["bg_card"], anchor="w"
        )
        self._ram_detail.pack(fill=tk.X, padx=10, pady=(0, 8))

        # CPU section
        cpu_frame = self._card(parent, "⚙️ CPU")
        self._cpu_overall_bar = self._metric_bar(cpu_frame, "Overall")
        
        self._cpu_temp_bar = self._metric_bar(cpu_frame, "Temp (°C)")

        self._cpu_cores_frame = tk.Frame(cpu_frame, bg=_COLORS["bg_card"])
        self._cpu_cores_frame.pack(fill=tk.X, padx=10, pady=(0, 8))
        self._cpu_core_bars = []

        # GPU section
        gpu_frame = self._card(parent, "🎮 GPU")
        self._gpu_load_bar = self._metric_bar(gpu_frame, "Load")
        self._gpu_vram_bar = self._metric_bar(gpu_frame, "VRAM")
        self._gpu_detail = tk.Label(
            gpu_frame, text="No GPU detected", font=("Consolas", 9),
            fg=_COLORS["text_dim"], bg=_COLORS["bg_card"], anchor="w"
        )
        self._gpu_detail.pack(fill=tk.X, padx=10, pady=(0, 8))

    def _card(self, parent, title: str) -> tk.Frame:
        outer = tk.Frame(parent, bg=_COLORS["border"], bd=1)
        outer.pack(fill=tk.X, pady=4)
        frame = tk.Frame(outer, bg=_COLORS["bg_card"])
        frame.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        tk.Label(
            frame, text=title, font=("Segoe UI", 11, "bold"),
            fg=_COLORS["accent_blue"], bg=_COLORS["bg_card"], anchor="w"
        ).pack(fill=tk.X, padx=10, pady=(8, 4))
        return frame

    def _metric_bar(self, parent, label: str):
        row = tk.Frame(parent, bg=_COLORS["bg_card"])
        row.pack(fill=tk.X, padx=10, pady=2)
        lbl = tk.Label(
            row, text=label, font=("Consolas", 9), width=8,
            fg=_COLORS["text_dim"], bg=_COLORS["bg_card"], anchor="w"
        )
        lbl.pack(side=tk.LEFT)
        canvas = tk.Canvas(
            row, height=16, bg=_COLORS["bar_bg"],
            highlightthickness=0, bd=0
        )
        canvas.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 4))
        pct_label = tk.Label(
            row, text="0%", font=("Consolas", 9), width=6,
            fg=_COLORS["text"], bg=_COLORS["bg_card"], anchor="e"
        )
        pct_label.pack(side=tk.RIGHT)
        return {"canvas": canvas, "pct_label": pct_label}

    def _draw_bar(self, bar_info: dict, pct: float):
        canvas = bar_info["canvas"]
        canvas.delete("all")
        canvas.update_idletasks()
        w = canvas.winfo_width()
        h = canvas.winfo_height()
        if w <= 1:
            return
        fill_w = int(pct / 100 * w)
        color = _pct_color(pct)
        canvas.create_rectangle(0, 0, fill_w, h, fill=color, outline="")
        bar_info["pct_label"].config(text=f"{pct:.1f}%")

    # ── Process Table (Center) ───────────────────────────────────────────

    def _build_process_table(self, parent):
        title_frame = tk.Frame(parent, bg=_COLORS["bg"])
        title_frame.pack(fill=tk.X)
        tk.Label(
            title_frame, text="📊 Running Processes",
            font=("Segoe UI", 12, "bold"), fg=_COLORS["accent_blue"],
            bg=_COLORS["bg"]
        ).pack(side=tk.LEFT, pady=4)

        self._sort_var = tk.StringVar(value="memory")
        sort_menu = ttk.Combobox(
            title_frame, textvariable=self._sort_var, state="readonly",
            values=["memory", "cpu", "name", "pid", "threads"], width=10
        )
        sort_menu.pack(side=tk.RIGHT, padx=4, pady=4)
        tk.Label(
            title_frame, text="Sort by:", font=("Segoe UI", 9),
            fg=_COLORS["text_dim"], bg=_COLORS["bg"]
        ).pack(side=tk.RIGHT)

        # Treeview
        columns = ("pid", "name", "memory", "cpu", "threads", "status", "flag")
        tree_frame = tk.Frame(parent, bg=_COLORS["bg_secondary"])
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=4)

        self._tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings",
            style="Process.Treeview", selectmode="extended"
        )
        self._tree.heading("pid", text="PID")
        self._tree.heading("name", text="Process Name")
        self._tree.heading("memory", text="Memory (MB)")
        self._tree.heading("cpu", text="CPU %")
        self._tree.heading("threads", text="Threads")
        self._tree.heading("status", text="Status")
        self._tree.heading("flag", text="Flag")

        self._tree.column("pid", width=65, anchor="e")
        self._tree.column("name", width=200, anchor="w")
        self._tree.column("memory", width=90, anchor="e")
        self._tree.column("cpu", width=65, anchor="e")
        self._tree.column("threads", width=65, anchor="e")
        self._tree.column("status", width=80, anchor="center")
        self._tree.column("flag", width=80, anchor="center")

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.pack(fill=tk.BOTH, expand=True)

        # Tag colors for rows
        self._tree.tag_configure("protected", background=_COLORS["protected"])
        self._tree.tag_configure("hog", background=_COLORS["hog"])
        self._tree.tag_configure("foreground", background=_COLORS["foreground"])
        self._tree.tag_configure("normal", background=_COLORS["bg_secondary"])
        self._tree.tag_configure("bloat", background="#4a2800")
        self._tree.tag_configure("junk", background=_COLORS["hog"])
        self._tree.tag_configure("idle", background="#2a2a3e")
        self._tree.tag_configure("useful", background="#1a2e1a")

        # Right-click context menu
        self._context_menu = tk.Menu(self._tree, tearoff=0,
                                      bg=_COLORS["bg_card"], fg=_COLORS["text"],
                                      activebackground=_COLORS["accent"],
                                      activeforeground="white",
                                      font=("Segoe UI", 10))
        self._context_menu.add_command(label="🔪 Kill Process", command=self._ctx_kill)
        self._context_menu.add_command(label="⏸ Suspend Process", command=self._ctx_suspend)
        self._context_menu.add_command(label="▶ Resume Process", command=self._ctx_resume)
        self._context_menu.add_separator()
        self._context_menu.add_command(label="🛡️ Add to Whitelist", command=self._ctx_whitelist)
        self._context_menu.add_command(label="🚫 Add to Blacklist", command=self._ctx_blacklist)

        self._tree.bind("<Button-3>", self._show_context_menu)

    def _show_context_menu(self, event):
        item = self._tree.identify_row(event.y)
        if item:
            self._tree.selection_set(item)
            self._context_menu.post(event.x_root, event.y_root)

    def _get_selected_process(self) -> Optional[dict]:
        sel = self._tree.selection()
        if not sel:
            return None
        values = self._tree.item(sel[0], "values")
        if not values:
            return None
        return {"pid": int(values[0]), "name": values[1]}

    def _ctx_kill(self):
        proc = self._get_selected_process()
        if not proc:
            return
        # Check if protected
        if self._is_protected_name(proc["name"]):
            messagebox.showwarning(
                "Protected Process",
                f"'{proc['name']}' is a protected system process and cannot be killed."
            )
            return
        if messagebox.askyesno(
            "Confirm Kill",
            f"Are you sure you want to KILL '{proc['name']}' (PID {proc['pid']})?\n\n"
            "This action cannot be undone."
        ):
            if self.on_kill_process:
                self.on_kill_process(proc["pid"], proc["name"])

    def _ctx_suspend(self):
        proc = self._get_selected_process()
        if not proc:
            return
        if self._is_protected_name(proc["name"]):
            messagebox.showwarning(
                "Protected Process",
                f"'{proc['name']}' is a protected system process and cannot be suspended."
            )
            return
        if self.on_suspend_process:
            self.on_suspend_process(proc["pid"], proc["name"])

    def _ctx_resume(self):
        proc = self._get_selected_process()
        if not proc:
            return
        if self.on_resume_process:
            self.on_resume_process(proc["pid"], proc["name"])

    def _ctx_whitelist(self):
        proc = self._get_selected_process()
        if not proc:
            return
        if self.on_add_whitelist:
            self.on_add_whitelist(proc["name"])
            self._log_action(f"Added '{proc['name']}' to whitelist")

    def _ctx_blacklist(self):
        proc = self._get_selected_process()
        if not proc:
            return
        if self._is_protected_name(proc["name"]):
            messagebox.showwarning(
                "Protected Process",
                f"'{proc['name']}' is a system-critical process and cannot be blacklisted."
            )
            return
        if self.on_add_blacklist:
            self.on_add_blacklist(proc["name"])
            self._log_action(f"Added '{proc['name']}' to blacklist")

    def _is_protected_name(self, name: str) -> bool:
        """Check if a process name is in the critical/whitelist."""
        return self._lists.is_protected(
            ProcessInfo(pid=0, name=name, is_foreground=False)
        )

        # Hardware Fan Controls
        self._build_hw_control_panel(parent)

    # ── Controls Panel (Right) ───────────────────────────────────────────

    def _build_hw_control_panel(self, parent):
        hw_frame = self._card(parent, "🌡️ Hardware Control")
        
        # Fan Speed Subheader
        tk.Label(
            hw_frame, text="System Fan Speed", font=("Segoe UI", 9, "bold"),
            fg=_COLORS["text_dim"], bg=_COLORS["bg_card"], anchor="w"
        ).pack(fill=tk.X, padx=10, pady=(4, 0))

        self._fan_var = tk.IntVar(value=50) # default mock value
        
        # Row with -, scale, +
        ctrl_row = tk.Frame(hw_frame, bg=_COLORS["bg_card"])
        ctrl_row.pack(fill=tk.X, padx=10, pady=(4, 10))
        
        def decrease_fan():
            val = max(0, self._fan_var.get() - 10)
            self._fan_var.set(val)
            self._on_fan_change(val)
            
        def increase_fan():
            val = min(100, self._fan_var.get() + 10)
            self._fan_var.set(val)
            self._on_fan_change(val)

        tk.Button(
            ctrl_row, text="−", font=("Segoe UI", 12, "bold"), width=2,
            bg=_COLORS["bar_bg"], fg=_COLORS["text"], relief="flat",
            cursor="hand2", command=decrease_fan
        ).pack(side=tk.LEFT)

        fan_scale = tk.Scale(
            ctrl_row, from_=0, to=100, orient=tk.HORIZONTAL,
            variable=self._fan_var, bg=_COLORS["bg_card"],
            fg=_COLORS["text"], troughcolor=_COLORS["bar_bg"],
            highlightthickness=0, sliderrelief="flat",
            font=("Consolas", 8), showvalue=True,
            command=self._on_fan_change
        )
        fan_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        tk.Button(
            ctrl_row, text="+", font=("Segoe UI", 12, "bold"), width=2,
            bg=_COLORS["bar_bg"], fg=_COLORS["text"], relief="flat",
            cursor="hand2", command=increase_fan
        ).pack(side=tk.RIGHT)

    def _on_fan_change(self, val):
        speed = int(val)
        # Apply to mock backend
        from core.telemetry import set_mock_fan_speed
        set_mock_fan_speed(speed)
        # Prevent log spam, only log if not updating from scale drag frequently
        if not hasattr(self, '_last_fan_log') or time.time() - self._last_fan_log > 1.0:
            self._log_action(f"Requested fan speed set to {speed}%", "info")
            self._last_fan_log = time.time()

    def _build_controls_panel(self, parent):
        # Mode section
        mode_frame = self._card(parent, "🎛️ Optimizer Controls")

        # Pause / Resume
        self._pause_btn = tk.Button(
            mode_frame, text="⏸ PAUSE", font=("Segoe UI", 10, "bold"),
            bg=_COLORS["accent_yellow"], fg="black",
            activebackground=_COLORS["accent"], activeforeground="white",
            relief="flat", cursor="hand2", command=self._toggle_pause
        )
        self._pause_btn.pack(fill=tk.X, padx=10, pady=6)

        # Auto / Manual toggle
        auto_frame = tk.Frame(mode_frame, bg=_COLORS["bg_card"])
        auto_frame.pack(fill=tk.X, padx=10, pady=4)
        tk.Label(
            auto_frame, text="Mode:", font=("Segoe UI", 9, "bold"),
            fg=_COLORS["text_dim"], bg=_COLORS["bg_card"]
        ).pack(side=tk.LEFT)
        self._auto_var = tk.BooleanVar(value=self._auto_mode)
        self._mode_label = tk.Label(
            auto_frame,
            text="⚠️ AUTO" if self._auto_mode else "🛡️ MANUAL",
            font=("Segoe UI", 10, "bold"),
            fg=_COLORS["accent"] if self._auto_mode else _COLORS["accent_green"],
            bg=_COLORS["bg_card"]
        )
        self._mode_label.pack(side=tk.RIGHT)
        mode_toggle = tk.Checkbutton(
            auto_frame, variable=self._auto_var,
            bg=_COLORS["bg_card"], activebackground=_COLORS["bg_card"],
            command=self._toggle_auto_mode, selectcolor=_COLORS["bg_secondary"]
        )
        mode_toggle.pack(side=tk.RIGHT, padx=4)

        # Threshold section
        thresh_frame = self._card(parent, "📏 Memory Threshold")
        self._thresh_var = tk.IntVar(value=self._config.memory_threshold_mb)
        self._thresh_label = tk.Label(
            thresh_frame,
            text=f"{self._config.memory_threshold_mb} MB",
            font=("Consolas", 14, "bold"),
            fg=_COLORS["accent_blue"], bg=_COLORS["bg_card"]
        )
        self._thresh_label.pack(pady=4)

        thresh_scale = tk.Scale(
            thresh_frame, from_=200, to=3000, orient=tk.HORIZONTAL,
            variable=self._thresh_var, bg=_COLORS["bg_card"],
            fg=_COLORS["text"], troughcolor=_COLORS["bar_bg"],
            highlightthickness=0, sliderrelief="flat",
            font=("Consolas", 8), showvalue=False,
            command=self._on_threshold_change
        )
        thresh_scale.pack(fill=tk.X, padx=10, pady=(0, 8))

        # Quick actions section
        actions_frame = self._card(parent, "⚡ Quick Actions")
        tk.Button(
            actions_frame, text="🛡️ Add to Whitelist",
            font=("Segoe UI", 9), bg=_COLORS["accent_green"],
            fg="black", relief="flat", cursor="hand2",
            command=self._manual_whitelist
        ).pack(fill=tk.X, padx=10, pady=3)

        tk.Button(
            actions_frame, text="🚫 Add to Blacklist",
            font=("Segoe UI", 9), bg=_COLORS["accent"],
            fg="white", relief="flat", cursor="hand2",
            command=self._manual_blacklist
        ).pack(fill=tk.X, padx=10, pady=3)

        # Pending actions (for manual mode)
        pending_frame = self._card(parent, "⏳ Pending Actions")
        self._pending_list = tk.Listbox(
            pending_frame, bg=_COLORS["bg_secondary"],
            fg=_COLORS["text"], font=("Consolas", 9),
            selectbackground=_COLORS["accent_blue"],
            highlightthickness=0, height=5, bd=0
        )
        self._pending_list.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        btn_row = tk.Frame(pending_frame, bg=_COLORS["bg_card"])
        btn_row.pack(fill=tk.X, padx=10, pady=(0, 8))
        tk.Button(
            btn_row, text="✅ Approve All", font=("Segoe UI", 8, "bold"),
            bg=_COLORS["accent_green"], fg="black", relief="flat",
            cursor="hand2", command=self._approve_all_pending
        ).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 2))
        tk.Button(
            btn_row, text="❌ Dismiss All", font=("Segoe UI", 8, "bold"),
            bg=_COLORS["accent"], fg="white", relief="flat",
            cursor="hand2", command=self._dismiss_all_pending
        ).pack(side=tk.RIGHT, expand=True, fill=tk.X, padx=(2, 0))

    def _toggle_pause(self):
        self._paused = not self._paused
        if self._paused:
            self._pause_btn.config(text="▶ RESUME", bg=_COLORS["accent_green"], fg="black")
            self._status_label.config(text="● PAUSED", fg=_COLORS["accent_yellow"])
        else:
            self._pause_btn.config(text="⏸ PAUSE", bg=_COLORS["accent_yellow"], fg="black")
            self._status_label.config(text="● RUNNING", fg=_COLORS["accent_green"])

    def _toggle_auto_mode(self):
        self._auto_mode = self._auto_var.get()
        if self._auto_mode:
            self._mode_label.config(text="⚠️ AUTO", fg=_COLORS["accent"])
            self._log_action("Switched to AUTO mode — actions will execute automatically", "info")
        else:
            self._mode_label.config(text="🛡️ MANUAL", fg=_COLORS["accent_green"])
            self._log_action("Switched to MANUAL mode — actions require approval", "info")
        if self.on_auto_mode_change:
            self.on_auto_mode_change(self._auto_mode)

    def _on_threshold_change(self, val):
        v = int(val)
        self._thresh_label.config(text=f"{v} MB")
        if self.on_threshold_change:
            self.on_threshold_change(v)

    def _manual_whitelist(self):
        name = simpledialog.askstring(
            "Add to Whitelist", "Enter process name (e.g., chrome.exe):",
            parent=self.root
        )
        if name and self.on_add_whitelist:
            self.on_add_whitelist(name)
            self._log_action(f"Whitelisted '{name}'")

    def _manual_blacklist(self):
        name = simpledialog.askstring(
            "Add to Blacklist", "Enter process name (e.g., bloatware.exe):",
            parent=self.root
        )
        if name and self.on_add_blacklist:
            self.on_add_blacklist(name)
            self._log_action(f"Blacklisted '{name}'")

    def _approve_all_pending(self):
        """Execute all pending actions."""
        for proc_info, action_type in self._pending_actions:
            if action_type == "terminate" and self.on_kill_process:
                self.on_kill_process(proc_info.pid, proc_info.name)
            elif action_type == "suspend" and self.on_suspend_process:
                self.on_suspend_process(proc_info.pid, proc_info.name)
        self._pending_actions.clear()
        self._pending_list.delete(0, tk.END)

    def _dismiss_all_pending(self):
        """Dismiss all pending actions."""
        self._pending_actions.clear()
        self._pending_list.delete(0, tk.END)

    # ── Action Log (Bottom) ──────────────────────────────────────────────

    def _build_action_log(self, parent):
        tk.Label(
            parent, text="🛠️ Action Log",
            font=("Segoe UI", 11, "bold"), fg=_COLORS["accent_blue"],
            bg=_COLORS["bg"], anchor="w"
        ).pack(fill=tk.X, pady=(4, 2))

        log_frame = tk.Frame(parent, bg=_COLORS["border"])
        log_frame.pack(fill=tk.BOTH, expand=True)

        self._log_text = tk.Text(
            log_frame, bg=_COLORS["bg_secondary"], fg=_COLORS["text"],
            font=("Consolas", 9), wrap=tk.WORD, height=6,
            highlightthickness=0, bd=0, padx=8, pady=4,
            state=tk.DISABLED, cursor="arrow"
        )
        log_scrollbar = ttk.Scrollbar(log_frame, orient="vertical",
                                       command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=log_scrollbar.set)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._log_text.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        # Tag configs for log
        self._log_text.tag_configure("success", foreground=_COLORS["accent_green"])
        self._log_text.tag_configure("error", foreground=_COLORS["accent"])
        self._log_text.tag_configure("info", foreground=_COLORS["accent_blue"])
        self._log_text.tag_configure("time", foreground=_COLORS["text_dim"])

    def _log_action(self, message: str, tag: str = "info"):
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_text.config(state=tk.NORMAL)
        self._log_text.insert(tk.END, f"[{ts}] ", "time")
        self._log_text.insert(tk.END, f"{message}\n", tag)
        self._log_text.see(tk.END)
        self._log_text.config(state=tk.DISABLED)

    # ── Public API (called by orchestrator) ──────────────────────────────

    def update(self, snapshot: SystemSnapshot):
        """Update the dashboard with a new system snapshot. Thread-safe."""
        self._snapshot = snapshot
        try:
            self.root.after(0, self._refresh_ui)
        except tk.TclError:
            pass  # Window closed

    def add_actions(self, actions: List[OptimizationAction]):
        """Add executed actions to the log."""
        for action in actions:
            self._actions.append(action)
            icon = "✅" if action.success else "❌"
            tag = "success" if action.success else "error"
            try:
                self.root.after(0, lambda a=action, i=icon, t=tag: self._log_action(
                    f"{i} {a.action.upper():10s} {a.process_name[:25]:25s} — {a.detail}", t
                ))
            except tk.TclError:
                pass

    def add_pending(self, recommendations: list):
        """Add recommendations to the pending list (manual mode)."""
        for proc, action_type in recommendations:
            self._pending_actions.append((proc, action_type))
            try:
                self.root.after(0, lambda p=proc, a=action_type: self._pending_list.insert(
                    tk.END, f"{a.upper():10s} {p.name[:20]:20s} ({p.memory_mb:.0f}MB)"
                ))
            except tk.TclError:
                pass

    def is_paused(self) -> bool:
        return self._paused

    def is_auto_mode(self) -> bool:
        return self._auto_mode

    def start(self):
        """Start the GUI main loop (blocking). Call from main thread."""
        mode_str = "Auto" if self._auto_mode else "Manual"
        self._log_action(f"Optimizer started — {mode_str} mode active", "info")
        self._log_action(
            f"Memory threshold: {self._config.memory_threshold_mb}MB | "
            f"Protected processes: {len(self._lists.whitelist)}", "info"
        )
        self.root.mainloop()

    def stop(self):
        """Stop the GUI."""
        self._running = False
        try:
            self.root.quit()
            self.root.destroy()
        except tk.TclError:
            pass

    # ── Internal Refresh ─────────────────────────────────────────────────

    def _refresh_ui(self):
        """Refresh all UI elements from the current snapshot."""
        snapshot = self._snapshot
        if not snapshot:
            return

        # Update header info
        uptime = datetime.now() - self._start_time
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        self._info_label.config(
            text=f"Processes: {snapshot.total_processes} | "
                 f"Uptime: {hours}:{minutes:02d}:{seconds:02d}"
        )

        # RAM
        self._draw_bar(self._ram_bar, snapshot.memory.percent)
        self._ram_detail.config(
            text=f"{snapshot.memory.used_mb:,.0f} / {snapshot.memory.total_mb:,.0f} MB  "
                 f"(Free: {snapshot.memory.available_mb:,.0f} MB)"
        )

        # CPU overall and Temp
        self._draw_bar(self._cpu_overall_bar, snapshot.cpu_overall_percent)

        temp_pct = min(100.0, max(0.0, (snapshot.cpu_temperature_c - 30) / (100 - 30) * 100))
        self._draw_bar(self._cpu_temp_bar, temp_pct)
        # Override pct label for temperature
        self._cpu_temp_bar["pct_label"].config(text=f"{snapshot.cpu_temperature_c:.1f}°C")

        # Sync Fan slider state if backend changed it indirectly
        if not getattr(self, '_fan_sliding', False):
            if abs(self._fan_var.get() - snapshot.fan_speed_percent) > 1:
                self._fan_var.set(int(snapshot.fan_speed_percent))

        # CPU cores (rebuild if core count changed)
        if len(self._cpu_core_bars) != len(snapshot.cpu_cores):
            for w in self._cpu_cores_frame.winfo_children():
                w.destroy()
            self._cpu_core_bars = []
            for core in snapshot.cpu_cores:
                bar = self._metric_bar(self._cpu_cores_frame, f"C{core.core_id}")
                self._cpu_core_bars.append(bar)

        for i, core in enumerate(snapshot.cpu_cores):
            if i < len(self._cpu_core_bars):
                self._draw_bar(self._cpu_core_bars[i], core.usage_percent)

        # GPU
        if snapshot.has_gpu and snapshot.gpus:
            gpu = snapshot.gpus[0]
            self._draw_bar(self._gpu_load_bar, gpu.load_percent)
            vram_pct = (gpu.memory_used_mb / gpu.memory_total_mb * 100) if gpu.memory_total_mb > 0 else 0
            self._draw_bar(self._gpu_vram_bar, vram_pct)
            temp_str = f" | 🌡️ {gpu.temperature:.0f}°C" if gpu.temperature else ""
            self._gpu_detail.config(
                text=f"{gpu.name}{temp_str}\n"
                     f"VRAM: {gpu.memory_used_mb:.0f}/{gpu.memory_total_mb:.0f} MB"
            )
        else:
            self._gpu_detail.config(text="No GPU detected")

        # Process table
        self._refresh_process_table(snapshot)

    def _refresh_process_table(self, snapshot: SystemSnapshot):
        """Refresh the process treeview."""
        # Remember scroll position
        selected = self._tree.selection()
        selected_pids = set()
        for item in selected:
            vals = self._tree.item(item, "values")
            if vals:
                selected_pids.add(vals[0])

        # Clear table
        self._tree.delete(*self._tree.get_children())

        # Sort processes
        procs = list(snapshot.processes)
        sort_key = self._sort_var.get()
        if sort_key == "memory":
            procs.sort(key=lambda p: p.memory_mb, reverse=True)
        elif sort_key == "cpu":
            procs.sort(key=lambda p: p.cpu_percent, reverse=True)
        elif sort_key == "name":
            procs.sort(key=lambda p: p.name.lower())
        elif sort_key == "pid":
            procs.sort(key=lambda p: p.pid)
        elif sort_key == "threads":
            procs.sort(key=lambda p: p.num_threads, reverse=True)

        threshold = self._thresh_var.get()

        # If we have a smart analyzer, score all visible processes
        score_map = {}
        if self._analyzer:
            try:
                visible_procs = procs[:100]
                scores = self._analyzer.analyze_all(visible_procs)
                score_map = {s.pid: s for s in scores}
            except Exception:
                pass

        for proc in procs[:100]:  # Limit to top 100 for performance
            ps = score_map.get(proc.pid)

            if ps:
                # Smart verdict-based display
                verdict = ps.verdict.value
                verdict_map = {
                    "essential": ("protected", "ESSENTIAL"),
                    "active":    ("foreground", "ACTIVE"),
                    "useful":    ("useful", "USEFUL"),
                    "idle":      ("idle", "IDLE"),
                    "bloat":     ("bloat", "BLOAT"),
                    "junk":      ("junk", "JUNK"),
                }
                tag, flag_text = verdict_map.get(verdict, ("normal", ""))
                flag = f"{flag_text} {ps.score:.0f}"
            else:
                # Fallback
                if proc.is_foreground:
                    tag = "foreground"
                    flag = "ACTIVE"
                elif self._is_protected_name(proc.name):
                    tag = "protected"
                    flag = "ESSENTIAL"
                elif proc.memory_mb >= threshold:
                    tag = "hog"
                    flag = "HOG"
                else:
                    tag = "normal"
                    flag = ""

            item_id = self._tree.insert("", tk.END, values=(
                proc.pid,
                proc.name[:30],
                f"{proc.memory_mb:.0f}",
                f"{proc.cpu_percent:.1f}",
                proc.num_threads,
                proc.status,
                flag,
            ), tags=(tag,))

            # Re-select if was selected before
            if str(proc.pid) in selected_pids:
                self._tree.selection_add(item_id)

    def _on_close(self):
        """Handle window close."""
        if messagebox.askyesno("Exit Optimizer", "Stop the optimizer and exit?"):
            self._running = False
            self.root.quit()
            self.root.destroy()
