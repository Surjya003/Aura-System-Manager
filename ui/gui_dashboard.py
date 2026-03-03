"""
GUI Dashboard — Premium CustomTkinter Interface
================================================
A modern dark-themed CustomTkinter GUI that gives users full control over the
system optimizer: real-time metrics, sortable process table, kill/suspend
controls, whitelist/blacklist management, and an action log.
"""

import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import customtkinter as ctk
from datetime import datetime
from typing import List, Optional, Callable

from core.config import Config
from core.lists_manager import ListsManager
from models.telemetry_models import SystemSnapshot, ProcessInfo, OptimizationAction

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# ── Color palette ────────────────────────────────────────────────────────────
_COLORS = {
    "bg":           "#0B0F19", # Deep Dark Blue/Black
    "bg_secondary": "#111827", # Gray 900
    "bg_card":      "#1F2937", # Gray 800
    "accent":       "#EF4444", # Red 500
    "accent_green": "#10B981", # Emerald 500
    "accent_yellow":"#F59E0B", # Amber 500
    "accent_blue":  "#3B82F6", # Blue 500
    "text":         "#F9FAFB", # Gray 50
    "text_dim":     "#9CA3AF", # Gray 400
    "text_dark":    "#4B5563", # Gray 600
    "bar_bg":       "#374151", # Gray 700
    "protected":    "#1E3A8A", # Blue 900
    "hog":          "#7F1D1D", # Red 900
    "foreground":   "#064E3B", # Emerald 900
    "border":       "#374151", # Gray 700
}

def _pct_color(pct: float) -> str:
    """Return a hex color for a utilization percentage."""
    if pct < 50:
        return _COLORS["accent_green"]
    elif pct < 80:
        return _COLORS["accent_yellow"]
    return _COLORS["accent"]


class GuiDashboard:
    """Premium CustomTkinter GUI for the System Optimizer."""

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
        self._analyzer = None

        self.on_kill_process: Optional[Callable] = None
        self.on_suspend_process: Optional[Callable] = None
        self.on_resume_process: Optional[Callable] = None
        self.on_add_whitelist: Optional[Callable] = None
        self.on_add_blacklist: Optional[Callable] = None
        self.on_threshold_change: Optional[Callable] = None
        self.on_auto_mode_change: Optional[Callable] = None

        self._build_window()

    def set_analyzer(self, analyzer):
        self._analyzer = analyzer

    def _build_window(self):
        self.root = ctk.CTk()
        self.root.title("Intelligent System Resource Optimizer")
        self.root.geometry("1450x900")
        self.root.minsize(1200, 700)

        self._setup_styles()

        # ── Header ───────────────────────────────────────────────────────
        header = ctk.CTkFrame(self.root, fg_color=_COLORS["bg_secondary"], corner_radius=0, height=60)
        header.pack(fill="x")
        header.pack_propagate(False)

        title_lbl = ctk.CTkLabel(
            header, text="⚡ Intelligent System Resource Optimizer",
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color=_COLORS["accent_blue"]
        )
        title_lbl.pack(side="left", padx=20, pady=15)

        self._status_label = ctk.CTkLabel(
            header, text="● RUNNING", 
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color=_COLORS["accent_green"]
        )
        self._status_label.pack(side="right", padx=20)

        self._info_label = ctk.CTkLabel(
            header, text="Processes: 0 | Uptime: 0:00:00",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=_COLORS["text_dim"]
        )
        self._info_label.pack(side="right", padx=20)

        # ── Main content area ────────────────────────────────────────────
        main_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=15, pady=10)

        # Left panel: metrics
        left_panel = ctk.CTkScrollableFrame(main_frame, fg_color="transparent", width=300)
        left_panel.pack(side="left", fill="y", padx=(0, 10))
        self._build_metrics_panel(left_panel)

        # Right panel: controls
        right_panel = ctk.CTkScrollableFrame(main_frame, fg_color="transparent", width=280)
        right_panel.pack(side="right", fill="y", padx=(10, 0))
        self._build_controls_panel(right_panel)

        # Center: process table
        center_panel = ctk.CTkFrame(main_frame, fg_color="transparent")
        center_panel.pack(side="left", fill="both", expand=True)
        self._build_process_table(center_panel)

        # ── Bottom: action log ───────────────────────────────────────────
        bottom_frame = ctk.CTkFrame(self.root, fg_color="transparent", height=180)
        bottom_frame.pack(fill="x", padx=15, pady=(0, 15))
        bottom_frame.pack_propagate(False)
        self._build_action_log(bottom_frame)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_styles(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")

        # Treeview style
        style.configure(
            "Process.Treeview",
            background=_COLORS["bg_secondary"],
            foreground=_COLORS["text"],
            fieldbackground=_COLORS["bg_secondary"],
            borderwidth=0,
            font=("Consolas", 10),
            rowheight=30,
        )
        style.configure(
            "Process.Treeview.Heading",
            background=_COLORS["bg_card"],
            foreground=_COLORS["text_dim"],
            borderwidth=0,
            font=("Segoe UI", 11, "bold"),
            padding=(5, 5)
        )
        style.map("Process.Treeview", background=[("selected", _COLORS["accent_blue"])])
        style.map("Process.Treeview.Heading", background=[("active", _COLORS["border"])])

    # ── Metrics Panel (Left) ─────────────────────────────────────────────

    def _build_metrics_panel(self, parent):
        # RAM section
        ram_frame = self._card(parent, "🧠 RAM")
        self._ram_bar = self._metric_bar(ram_frame, "Usage")
        self._ram_detail = ctk.CTkLabel(
            ram_frame, text="0 / 0 MB", font=("Consolas", 11),
            text_color=_COLORS["text_dim"], anchor="w"
        )
        self._ram_detail.pack(fill="x", padx=15, pady=(0, 10))

        # CPU section
        cpu_frame = self._card(parent, "⚙️ CPU")
        self._cpu_overall_bar = self._metric_bar(cpu_frame, "Overall")
        self._cpu_temp_bar = self._metric_bar(cpu_frame, "Temp (°C)")

        self._cpu_cores_scroll = ctk.CTkScrollableFrame(cpu_frame, fg_color="transparent", height=120)
        self._cpu_cores_scroll.pack(fill="x", padx=5, pady=(5, 5))
        self._cpu_core_bars = []

        # GPU section
        gpu_frame = self._card(parent, "🎮 GPU")
        self._gpu_load_bar = self._metric_bar(gpu_frame, "Load")
        self._gpu_vram_bar = self._metric_bar(gpu_frame, "VRAM")
        self._gpu_detail = ctk.CTkLabel(
            gpu_frame, text="No GPU detected", font=("Consolas", 11),
            text_color=_COLORS["text_dim"], anchor="w", justify="left"
        )
        self._gpu_detail.pack(fill="x", padx=15, pady=(5, 10))

    def _card(self, parent, title: str) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(parent, fg_color=_COLORS["bg_card"], corner_radius=10)
        frame.pack(fill="x", pady=(0, 10))
        lbl = ctk.CTkLabel(
            frame, text=title, font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=_COLORS["text"], anchor="w"
        )
        lbl.pack(fill="x", padx=15, pady=(12, 8))
        return frame

    def _metric_bar(self, parent, label: str):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=15, pady=4)
        lbl = ctk.CTkLabel(
            row, text=label, font=("Consolas", 11), width=75,
            text_color=_COLORS["text_dim"], anchor="w"
        )
        lbl.pack(side="left")
        
        progress = ctk.CTkProgressBar(
            row, height=8, fg_color=_COLORS["bar_bg"],
            progress_color=_COLORS["accent_blue"]
        )
        progress.set(0)
        progress.pack(side="left", fill="x", expand=True, padx=(8, 8))
        
        pct_label = ctk.CTkLabel(
            row, text="0%", font=("Consolas", 11), width=45,
            text_color=_COLORS["text"], anchor="e"
        )
        pct_label.pack(side="right")
        return {"progress": progress, "pct_label": pct_label, "label": label}

    def _draw_bar(self, bar_info: dict, pct: float):
        progress = bar_info["progress"]
        progress.set(pct / 100.0)
        color = _pct_color(pct)
        progress.configure(progress_color=color)
        if "Temp" in bar_info.get("label", "") or bar_info["pct_label"].cget("text").endswith("°C"):
            pass # Keep separate logic for temp if overriden
        else:
            bar_info["pct_label"].configure(text=f"{pct:.1f}%")

    # ── Process Table (Center) ───────────────────────────────────────────

    def _build_process_table(self, parent):
        title_frame = ctk.CTkFrame(parent, fg_color="transparent")
        title_frame.pack(fill="x")
        
        ctk.CTkLabel(
            title_frame, text="📊 Running Processes",
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"), 
            text_color=_COLORS["text"]
        ).pack(side="left", pady=5)

        self._sort_var = ctk.StringVar(value="memory")
        sort_menu = ctk.CTkOptionMenu(
            title_frame, variable=self._sort_var, 
            values=["memory", "cpu", "name", "pid", "threads"],
            width=120, fg_color=_COLORS["bg_card"],
            button_color=_COLORS["bg_card"], button_hover_color=_COLORS["border"]
        )
        sort_menu.pack(side="right", padx=5, pady=5)
        
        ctk.CTkLabel(
            title_frame, text="Sort by:", font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=_COLORS["text_dim"]
        ).pack(side="right")

        # Treeview
        columns = ("pid", "name", "memory", "cpu", "threads", "status", "flag")
        
        # We need a frame for the treeview + scrollbar
        tree_frame = ctk.CTkFrame(parent, fg_color=_COLORS["bg_secondary"], corner_radius=10)
        tree_frame.pack(fill="both", expand=True, pady=(5, 0))

        self._tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings",
            style="Process.Treeview", selectmode="extended"
        )
        self._tree.heading("pid", text="PID")
        self._tree.heading("name", text="Process Name")
        self._tree.heading("memory", text="Mem(MB)")
        self._tree.heading("cpu", text="CPU (%)")
        self._tree.heading("threads", text="Threads")
        self._tree.heading("status", text="Status")
        self._tree.heading("flag", text="Flag")

        self._tree.column("pid", width=70, anchor="e")
        self._tree.column("name", width=240, anchor="w")
        self._tree.column("memory", width=80, anchor="e")
        self._tree.column("cpu", width=70, anchor="e")
        self._tree.column("threads", width=70, anchor="e")
        self._tree.column("status", width=90, anchor="center")
        self._tree.column("flag", width=110, anchor="center")

        scrollbar = ctk.CTkScrollbar(tree_frame, orientation="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side="right", fill="y", padx=(0, 2), pady=2)
        self._tree.pack(fill="both", expand=True, padx=(2, 0), pady=2)

        # Tag colors for rows
        self._tree.tag_configure("protected", background=_COLORS["protected"], foreground="white")
        self._tree.tag_configure("hog", background=_COLORS["hog"], foreground="white")
        self._tree.tag_configure("foreground", background=_COLORS["foreground"], foreground="white")
        self._tree.tag_configure("normal", background=_COLORS["bg_secondary"], foreground=_COLORS["text"])
        self._tree.tag_configure("bloat", background="#4a2800", foreground="white")
        self._tree.tag_configure("junk", background=_COLORS["hog"], foreground="white")
        self._tree.tag_configure("idle", background="#2a2a3e", foreground="white")
        self._tree.tag_configure("useful", background="#1a2e1a", foreground="white")

        # Right-click context menu (Tkinter Menu still required for cross-platform native context menus)
        self._context_menu = tk.Menu(self._tree, tearoff=0,
                                      bg=_COLORS["bg_card"], fg=_COLORS["text"],
                                      activebackground=_COLORS["accent_blue"],
                                      activeforeground="white",
                                      font=("Segoe UI", 10),
                                      bd=0)
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
        if not proc: return
        if self._is_protected_name(proc["name"]):
            messagebox.showwarning("Protected Process", f"'{proc['name']}' is a protected system process.")
            return
        if messagebox.askyesno("Confirm Kill", f"Kill '{proc['name']}' (PID {proc['pid']})?"):
            if self.on_kill_process: self.on_kill_process(proc["pid"], proc["name"])

    def _ctx_suspend(self):
        proc = self._get_selected_process()
        if not proc: return
        if self._is_protected_name(proc["name"]):
            messagebox.showwarning("Protected Process", "Cannot suspend protected process.")
            return
        if self.on_suspend_process: self.on_suspend_process(proc["pid"], proc["name"])

    def _ctx_resume(self):
        proc = self._get_selected_process()
        if not proc: return
        if self.on_resume_process: self.on_resume_process(proc["pid"], proc["name"])

    def _ctx_whitelist(self):
        proc = self._get_selected_process()
        if not proc: return
        if self.on_add_whitelist:
            self.on_add_whitelist(proc["name"])
            self._log_action(f"Added '{proc['name']}' to whitelist")

    def _ctx_blacklist(self):
        proc = self._get_selected_process()
        if not proc: return
        if self._is_protected_name(proc["name"]):
            messagebox.showwarning("Protected Process", "Cannot blacklist critical process.")
            return
        if self.on_add_blacklist:
            self.on_add_blacklist(proc["name"])
            self._log_action(f"Added '{proc['name']}' to blacklist")

    def _is_protected_name(self, name: str) -> bool:
        return self._lists.is_protected(ProcessInfo(pid=0, name=name, is_foreground=False))

    # ── Controls Panel (Right) ───────────────────────────────────────────

    def _build_hw_control_panel(self, parent):
        hw_frame = self._card(parent, "🌡️ Hardware Control")
        
        ctk.CTkLabel(
            hw_frame, text="System Fan Speed", font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=_COLORS["text_dim"], anchor="w"
        ).pack(fill="x", padx=15, pady=(4, 0))

        self._fan_var = ctk.IntVar(value=50) # default mock value
        
        ctrl_row = ctk.CTkFrame(hw_frame, fg_color="transparent")
        ctrl_row.pack(fill="x", padx=15, pady=(4, 2))
        
        self._rpm_label = ctk.CTkLabel(
            hw_frame, text="Speed: 3000 RPM", font=("Consolas", 11),
            text_color=_COLORS["accent_blue"], anchor="w"
        )
        self._rpm_label.pack(fill="x", padx=15, pady=(0, 10))
        
        def decrease_fan():
            val = max(0, self._fan_var.get() - 10)
            self._fan_var.set(val)
            self._on_fan_change(val)
            
        def increase_fan():
            val = min(100, self._fan_var.get() + 10)
            self._fan_var.set(val)
            self._on_fan_change(val)

        ctk.CTkButton(
            ctrl_row, text="−", width=30, height=30,
            fg_color=_COLORS["bar_bg"], hover_color=_COLORS["border"],
            command=decrease_fan
        ).pack(side="left")

        fan_scale = ctk.CTkSlider(
            ctrl_row, from_=0, to=100, variable=self._fan_var,
            button_color=_COLORS["text"], button_hover_color=_COLORS["accent_blue"],
            progress_color=_COLORS["accent_blue"], command=self._on_fan_change
        )
        fan_scale.pack(side="left", fill="x", expand=True, padx=10)

        ctk.CTkButton(
            ctrl_row, text="+", width=30, height=30,
            fg_color=_COLORS["bar_bg"], hover_color=_COLORS["border"],
            command=increase_fan
        ).pack(side="right")

    def _on_fan_change(self, val):
        speed = int(float(val))
        rpm = int((speed / 100.0) * 6000)
        if hasattr(self, '_rpm_label'):
            self._rpm_label.configure(text=f"Speed: {rpm} RPM")

        # Apply to mock backend
        from core.telemetry import set_mock_fan_speed
        set_mock_fan_speed(speed)
        if not hasattr(self, '_last_fan_log') or time.time() - self._last_fan_log > 1.0:
            self._log_action(f"Requested fan speed set to {speed}%", "info")
            self._last_fan_log = time.time()

    def _build_controls_panel(self, parent):
        self._build_hw_control_panel(parent)

        # Mode section
        mode_frame = self._card(parent, "🎛️ Optimizer Controls")

        self._pause_btn = ctk.CTkButton(
            mode_frame, text="⏸ PAUSE", font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color=_COLORS["accent_yellow"], text_color="#1F2937",
            hover_color=_COLORS["accent"], command=self._toggle_pause,
            height=36
        )
        self._pause_btn.pack(fill="x", padx=15, pady=6)

        auto_frame = ctk.CTkFrame(mode_frame, fg_color="transparent")
        auto_frame.pack(fill="x", padx=15, pady=4)
        
        ctk.CTkLabel(
            auto_frame, text="Mode:", font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=_COLORS["text_dim"]
        ).pack(side="left")
        
        self._auto_var = ctk.BooleanVar(value=self._auto_mode)
        mode_str = "⚠️ AUTO" if self._auto_mode else "🛡️ MANUAL"
        mode_color = _COLORS["accent"] if self._auto_mode else _COLORS["accent_green"]
        
        self._mode_label = ctk.CTkLabel(
            auto_frame, text=mode_str, font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=mode_color
        )
        self._mode_label.pack(side="right")
        
        mode_toggle = ctk.CTkSwitch(
            auto_frame, text="", variable=self._auto_var,
            onvalue=True, offvalue=False, command=self._toggle_auto_mode,
            progress_color=_COLORS["accent"], button_color=_COLORS["text"],
            button_hover_color=_COLORS["text_dim"], width=40
        )
        mode_toggle.pack(side="right", padx=10)

        # Threshold section
        thresh_frame = self._card(parent, "📏 Memory Threshold")
        self._thresh_var = ctk.IntVar(value=self._config.memory_threshold_mb)
        self._thresh_label = ctk.CTkLabel(
            thresh_frame, text=f"{self._config.memory_threshold_mb} MB",
            font=ctk.CTkFont(family="Consolas", size=18, weight="bold"),
            text_color=_COLORS["accent_blue"]
        )
        self._thresh_label.pack(pady=(4, 8))

        thresh_scale = ctk.CTkSlider(
            thresh_frame, from_=200, to=3000, variable=self._thresh_var,
            progress_color=_COLORS["accent_blue"], button_color=_COLORS["text"],
            button_hover_color=_COLORS["accent_blue"], command=self._on_threshold_change
        )
        thresh_scale.pack(fill="x", padx=15, pady=(0, 15))

        # Quick actions section
        actions_frame = self._card(parent, "⚡ Quick Actions")
        ctk.CTkButton(
            actions_frame, text="🛡️ Add to Whitelist", font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=_COLORS["accent_green"], text_color="#1F2937",
            hover_color="#059669", command=self._manual_whitelist, height=32
        ).pack(fill="x", padx=15, pady=4)

        ctk.CTkButton(
            actions_frame, text="🚫 Add to Blacklist", font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=_COLORS["accent"], text_color="#FFFFFF",
            hover_color="#DC2626", command=self._manual_blacklist, height=32
        ).pack(fill="x", padx=15, pady=(4, 12))

        # Pending actions (for manual mode)
        pending_frame = self._card(parent, "⏳ Pending Actions")
        
        self._pending_list = tk.Listbox(
            pending_frame, bg=_COLORS["bg_secondary"],
            fg=_COLORS["text"], font=("Consolas", 10),
            selectbackground=_COLORS["accent_blue"],
            highlightthickness=0, height=4, bd=0
        )
        self._pending_list.pack(fill="both", expand=True, padx=15, pady=8)

        btn_row = ctk.CTkFrame(pending_frame, fg_color="transparent")
        btn_row.pack(fill="x", padx=15, pady=(0, 15))
        
        ctk.CTkButton(
            btn_row, text="✅ Approve All", font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color=_COLORS["accent_green"], text_color="#1F2937", hover_color="#059669",
            command=self._approve_all_pending, height=28
        ).pack(side="left", expand=True, fill="x", padx=(0, 5))
        
        ctk.CTkButton(
            btn_row, text="❌ Dismiss All", font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color=_COLORS["accent"], text_color="#FFFFFF", hover_color="#DC2626",
            command=self._dismiss_all_pending, height=28
        ).pack(side="right", expand=True, fill="x", padx=(5, 0))

    def _toggle_pause(self):
        self._paused = not self._paused
        if self._paused:
            self._pause_btn.configure(text="▶ RESUME", fg_color=_COLORS["accent_green"], text_color="#1F2937")
            self._status_label.configure(text="● PAUSED", text_color=_COLORS["accent_yellow"])
        else:
            self._pause_btn.configure(text="⏸ PAUSE", fg_color=_COLORS["accent_yellow"], text_color="#1F2937")
            self._status_label.configure(text="● RUNNING", text_color=_COLORS["accent_green"])

    def _toggle_auto_mode(self):
        self._auto_mode = self._auto_var.get()
        if self._auto_mode:
            self._mode_label.configure(text="⚠️ AUTO", text_color=_COLORS["accent"])
            self._log_action("Switched to AUTO mode — actions will execute automatically", "info")
        else:
            self._mode_label.configure(text="🛡️ MANUAL", text_color=_COLORS["accent_green"])
            self._log_action("Switched to MANUAL mode — actions require approval", "info")
        if self.on_auto_mode_change:
            self.on_auto_mode_change(self._auto_mode)

    def _on_threshold_change(self, val):
        v = int(val)
        self._thresh_label.configure(text=f"{v} MB")
        if self.on_threshold_change:
            self.on_threshold_change(v)

    def _manual_whitelist(self):
        name = simpledialog.askstring("Add to Whitelist", "Enter process name (e.g., chrome.exe):", parent=self.root)
        if name and self.on_add_whitelist:
            self.on_add_whitelist(name)
            self._log_action(f"Whitelisted '{name}'")

    def _manual_blacklist(self):
        name = simpledialog.askstring("Add to Blacklist", "Enter process name (e.g., bloatware.exe):", parent=self.root)
        if name and self.on_add_blacklist:
            self.on_add_blacklist(name)
            self._log_action(f"Blacklisted '{name}'")

    def _approve_all_pending(self):
        for proc_info, action_type in self._pending_actions:
            if action_type == "terminate" and self.on_kill_process:
                self.on_kill_process(proc_info.pid, proc_info.name)
            elif action_type == "suspend" and self.on_suspend_process:
                self.on_suspend_process(proc_info.pid, proc_info.name)
        self._pending_actions.clear()
        self._pending_list.delete(0, tk.END)

    def _dismiss_all_pending(self):
        self._pending_actions.clear()
        self._pending_list.delete(0, tk.END)

    # ── Action Log (Bottom) ──────────────────────────────────────────────

    def _build_action_log(self, parent):
        ctk.CTkLabel(
            parent, text="🛠️ Action Log",
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"), 
            text_color=_COLORS["text"]
        ).pack(anchor="w", pady=(0, 5))

        log_frame = ctk.CTkFrame(parent, fg_color=_COLORS["bg_secondary"], corner_radius=10)
        log_frame.pack(fill="both", expand=True)

        self._log_text = ctk.CTkTextbox(
            log_frame, fg_color="transparent", text_color=_COLORS["text"],
            font=ctk.CTkFont(family="Consolas", size=12), wrap="word",
            state="disabled"
        )
        self._log_text.pack(fill="both", expand=True, padx=10, pady=10)

        # Basic text tags (CTkTextbox supports minimal tagging)
        self._log_text.tag_config("success", foreground=_COLORS["accent_green"])
        self._log_text.tag_config("error", foreground=_COLORS["accent"])
        self._log_text.tag_config("info", foreground=_COLORS["accent_blue"])
        self._log_text.tag_config("time", foreground=_COLORS["text_dim"])

    def _log_action(self, message: str, tag: str = "info"):
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_text.configure(state="normal")
        self._log_text.insert("end", f"[{ts}] ", "time")
        self._log_text.insert("end", f"{message}\n", tag)
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    # ── Public API (called by orchestrator) ──────────────────────────────

    def update(self, snapshot: SystemSnapshot):
        self._snapshot = snapshot
        try:
            self.root.after(0, self._refresh_ui)
        except tk.TclError:
            pass

    def add_actions(self, actions: List[OptimizationAction]):
        for action in actions:
            self._actions.append(action)
            icon = "✅" if action.success else "❌"
            tag = "success" if action.success else "error"
            try:
                msg = f"{icon} {action.action.upper():10s} {action.process_name[:25]:25s} — {action.detail}"
                self.root.after(0, lambda m=msg, t=tag: self._log_action(m, t))
            except tk.TclError:
                pass

    def add_pending(self, recommendations: list):
        for proc, action_type in recommendations:
            self._pending_actions.append((proc, action_type))
            try:
                msg = f"{action_type.upper():10s} {proc.name[:20]:20s} ({proc.memory_mb:.0f}MB)"
                self.root.after(0, lambda m=msg: self._pending_list.insert(tk.END, m))
            except tk.TclError:
                pass

    def is_paused(self) -> bool:
        return self._paused

    def is_auto_mode(self) -> bool:
        return self._auto_mode

    def start(self):
        mode_str = "Auto" if self._auto_mode else "Manual"
        self._log_action(f"Optimizer started — {mode_str} mode active", "info")
        self._log_action(
            f"Memory threshold: {self._config.memory_threshold_mb}MB | "
            f"Protected processes: {len(self._lists.whitelist)}", "info"
        )
        self.root.mainloop()

    def stop(self):
        self._running = False
        try:
            self.root.quit()
            self.root.destroy()
        except tk.TclError:
            pass

    # ── Internal Refresh ─────────────────────────────────────────────────

    def _refresh_ui(self):
        snapshot = self._snapshot
        if not snapshot:
            return

        uptime = datetime.now() - self._start_time
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        self._info_label.configure(
            text=f"Processes: {snapshot.total_processes} | "
                 f"Uptime: {hours}:{minutes:02d}:{seconds:02d}"
        )

        self._draw_bar(self._ram_bar, snapshot.memory.percent)
        self._ram_detail.configure(
            text=f"{snapshot.memory.used_mb:,.0f} / {snapshot.memory.total_mb:,.0f} MB  "
                 f"(Free: {snapshot.memory.available_mb:,.0f} MB)"
        )

        self._draw_bar(self._cpu_overall_bar, snapshot.cpu_overall_percent)

        temp_pct = min(100.0, max(0.0, (snapshot.cpu_temperature_c - 30) / (100 - 30) * 100))
        self._draw_bar(self._cpu_temp_bar, temp_pct)
        self._cpu_temp_bar["pct_label"].configure(text=f"{snapshot.cpu_temperature_c:.1f}°C")

        if not getattr(self, '_fan_sliding', False):
            if abs(self._fan_var.get() - snapshot.fan_speed_percent) > 1:
                speed = int(snapshot.fan_speed_percent)
                self._fan_var.set(speed)
                rpm = int((speed / 100.0) * 6000)
                if hasattr(self, '_rpm_label'):
                    self._rpm_label.configure(text=f"Speed: {rpm} RPM")

        if len(self._cpu_core_bars) != len(snapshot.cpu_cores):
            for w in self._cpu_cores_scroll.winfo_children():
                w.destroy()
            self._cpu_core_bars = []
            for core in snapshot.cpu_cores:
                bar = self._metric_bar(self._cpu_cores_scroll, f"C{core.core_id}")
                self._cpu_core_bars.append(bar)

        for i, core in enumerate(snapshot.cpu_cores):
            if i < len(self._cpu_core_bars):
                self._draw_bar(self._cpu_core_bars[i], core.usage_percent)

        if snapshot.has_gpu and snapshot.gpus:
            gpu = snapshot.gpus[0]
            self._draw_bar(self._gpu_load_bar, gpu.load_percent)
            vram_pct = (gpu.memory_used_mb / gpu.memory_total_mb * 100) if gpu.memory_total_mb > 0 else 0
            self._draw_bar(self._gpu_vram_bar, vram_pct)
            temp_str = f" | 🌡️ {gpu.temperature:.0f}°C" if gpu.temperature else ""
            self._gpu_detail.configure(
                text=f"{gpu.name}{temp_str}\n"
                     f"VRAM: {gpu.memory_used_mb:.0f}/{gpu.memory_total_mb:.0f} MB"
            )
        else:
            self._gpu_detail.configure(text="No GPU detected\nVRAM: 0/0 MB")

        self._refresh_process_table(snapshot)

    def _refresh_process_table(self, snapshot: SystemSnapshot):
        selected = self._tree.selection()
        selected_pids = set()
        for item in selected:
            vals = self._tree.item(item, "values")
            if vals:
                selected_pids.add(vals[0])

        self._tree.delete(*self._tree.get_children())

        procs = list(snapshot.processes)
        sort_key = self._sort_var.get()
        if sort_key == "memory": procs.sort(key=lambda p: p.memory_mb, reverse=True)
        elif sort_key == "cpu": procs.sort(key=lambda p: p.cpu_percent, reverse=True)
        elif sort_key == "name": procs.sort(key=lambda p: p.name.lower())
        elif sort_key == "pid": procs.sort(key=lambda p: p.pid)
        elif sort_key == "threads": procs.sort(key=lambda p: p.num_threads, reverse=True)

        threshold = self._thresh_var.get()
        score_map = {}
        if self._analyzer:
            try:
                visible_procs = procs[:100]
                scores = self._analyzer.analyze_all(visible_procs)
                score_map = {s.pid: s for s in scores}
            except Exception:
                pass

        for proc in procs[:100]:
            ps = score_map.get(proc.pid)

            if ps:
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
                if proc.is_foreground: tag, flag = "foreground", "ACTIVE"
                elif self._is_protected_name(proc.name): tag, flag = "protected", "ESSENTIAL"
                elif proc.memory_mb >= threshold: tag, flag = "hog", "HOG"
                else: tag, flag = "normal", ""

            item_id = self._tree.insert("", tk.END, values=(
                proc.pid,
                proc.name[:30],
                f"{proc.memory_mb:.0f}",
                f"{proc.cpu_percent:.1f}",
                proc.num_threads,
                proc.status,
                flag,
            ), tags=(tag,))

            if str(proc.pid) in selected_pids:
                self._tree.selection_add(item_id)

    def _on_close(self):
        if messagebox.askyesno("Exit Optimizer", "Stop the optimizer and exit?"):
            self._running = False
            self.root.quit()
            self.root.destroy()
