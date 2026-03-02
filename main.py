"""
Intelligent System Resource Optimizer — Main Orchestrator
==========================================================
The central optimization loop that coordinates all subsystems:
telemetry, process scanning, memory optimization, CPU/GPU routing,
usage tracking, learning, and the live dashboard.

Usage:
    python main.py                # Run with GUI dashboard (default)
    python main.py --terminal     # Run with old Rich terminal dashboard
    python main.py --headless     # Run without any dashboard (background only)
    python main.py --dry-run      # Show what would be done, no actions taken
"""

import argparse
import signal
import sys
import threading
import time
from typing import List

from core.config import Config
from core.telemetry import get_system_snapshot
from core.process_scanner import scan_all_processes, get_foreground_pid
from core.memory_optimizer import MemoryOptimizer
from core.lists_manager import ListsManager
from core.cpu_affinity import CpuAffinityManager
from core.gpu_router import GpuRouter
from core.app_classifier import AppClassifier
from core.usage_tracker import UsageTracker
from core.priority_predictor import PriorityPredictor
from core.process_analyzer import ProcessAnalyzer
from core.process_controller import terminate_process, suspend_process, resume_process
from models.telemetry_models import OptimizationAction, SystemSnapshot
from utils.admin import ensure_admin
from utils.logger import setup_logger, get_logger


# ── Globals ──────────────────────────────────────────────────────────────────
_running = True


def _signal_handler(signum, frame):
    """Handle Ctrl+C for graceful shutdown."""
    global _running
    _running = False


def parse_args():
    parser = argparse.ArgumentParser(
        description="Intelligent System Resource Optimizer",
    )
    parser.add_argument(
        "--terminal", action="store_true",
        help="Use the old Rich terminal dashboard instead of GUI",
    )
    parser.add_argument(
        "--headless", action="store_true",
        help="Run without any dashboard",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show recommendations without executing actions",
    )
    parser.add_argument(
        "--no-admin", action="store_true",
        help="Skip admin elevation check (limited functionality)",
    )
    parser.add_argument(
        "--auto", action="store_true",
        help="Enable auto mode (skip user confirmation for actions)",
    )
    parser.add_argument(
        "--config", type=str, default="config.yaml",
        help="Path to config file (default: config.yaml)",
    )
    return parser.parse_args()


def _optimization_loop(
    config, mem_optimizer, cpu_manager, gpu_router,
    usage_tracker, predictor, dashboard, logger, args
):
    """Background optimization loop that feeds the dashboard."""
    global _running

    all_actions: List[OptimizationAction] = []
    tick_count = 0

    while _running:
        # Check if dashboard is still alive (for GUI mode)
        if dashboard and hasattr(dashboard, '_running') and not dashboard._running:
            _running = False
            break

        # Check if paused
        if dashboard and hasattr(dashboard, 'is_paused') and dashboard.is_paused():
            time.sleep(1)
            continue

        tick_count += 1

        try:
            # 1. Detect foreground window
            fg_pid = get_foreground_pid()

            # 2. Scan all processes
            processes = scan_all_processes(fg_pid)

            # 3. Collect system telemetry
            snapshot = get_system_snapshot(processes)
            snapshot.foreground_pid = fg_pid
            snapshot.total_processes = len(processes)

            # 4. Update usage tracking
            usage_tracker.update_active_processes(processes)

            # 5. Clear prediction cache for this cycle
            predictor.clear_cache()

            # 6. Memory optimization
            is_auto = args.auto or (
                dashboard and hasattr(dashboard, 'is_auto_mode')
                and dashboard.is_auto_mode()
            )

            # Get current RAM pressure for smart analysis
            ram_pct = snapshot.memory.percent if snapshot.memory else 0.0

            if is_auto and not args.dry_run:
                # Auto mode: execute actions automatically
                mem_actions = mem_optimizer.optimize(
                    processes, dry_run=args.dry_run, ram_percent=ram_pct
                )
                all_actions.extend(mem_actions)
                if dashboard and mem_actions:
                    dashboard.add_actions(mem_actions)
            else:
                # Manual mode: only recommend, don't execute
                recommendations = mem_optimizer.recommend_actions(
                    processes, ram_percent=ram_pct
                )
                if recommendations and dashboard and hasattr(dashboard, 'add_pending'):
                    dashboard.add_pending(recommendations)

            # 7. Flush working sets (every 3 ticks when RAM is high)
            if tick_count % 3 == 0:
                flush_count = mem_optimizer.flush_working_sets(ram_pct)
                if flush_count and dashboard:
                    from models.telemetry_models import OptimizationAction
                    flush_action = OptimizationAction(
                        pid=0, process_name="[System]",
                        action="flush", reason=f"RAM at {ram_pct:.0f}%",
                        success=True, detail=f"Flushed {flush_count} process working sets",
                    )
                    dashboard.add_actions([flush_action])

            # 8. CPU affinity routing
            cpu_actions = []
            if config.cpu_routing_enabled:
                cpu_actions = cpu_manager.optimize_affinities(processes)
                all_actions.extend(cpu_actions)

            # 9. GPU preference routing (every 10 ticks)
            if config.gpu_routing_enabled and tick_count % 10 == 1:
                gpu_actions = gpu_router.optimize_gpu_routing(processes)
                all_actions.extend(gpu_actions)

            # 10. Maybe retrain predictor
            if tick_count % 100 == 0:
                predictor.maybe_retrain()

            # 11. Update dashboard
            if dashboard:
                dashboard.update(snapshot)

            # 12. Hot-reload config
            if config.reload_if_changed():
                logger.info("Config reloaded")

            # Keep only last 200 actions in memory
            all_actions = all_actions[-200:]

        except Exception as e:
            logger.error(f"Optimization loop error: {e}")

        # Sleep until next scan
        time.sleep(config.scan_interval)


def main():
    global _running

    args = parse_args()

    # ── Admin check ──────────────────────────────────────────────────────
    if not args.no_admin:
        ensure_admin()

    # ── Initialize config & logger ───────────────────────────────────────
    config = Config(args.config)
    logger = setup_logger(
        log_level=config.log_level,
        log_file=config.log_file,
    )

    logger.info("=" * 60)
    logger.info("⚡ Intelligent System Resource Optimizer starting...")
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("🏳️ DRY RUN mode — no actions will be executed")

    # ── Initialize subsystems ────────────────────────────────────────────
    classifier = AppClassifier(config)
    lists_mgr = ListsManager(config)
    mem_optimizer = MemoryOptimizer(config, lists_mgr)
    cpu_manager = CpuAffinityManager(config, classifier)
    gpu_router = GpuRouter(config, classifier)
    usage_tracker = UsageTracker(config)
    predictor = PriorityPredictor(config, usage_tracker)

    # Load existing ML model if available
    predictor.load_model()

    # Smart process analyzer — the brain that decides what's useful
    analyzer = ProcessAnalyzer(config, lists_mgr, classifier, predictor)
    mem_optimizer.set_analyzer(analyzer)
    logger.info("Smart process analyzer enabled")

    # ── Signal handling ──────────────────────────────────────────────────
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # ── Choose dashboard mode ────────────────────────────────────────────
    dashboard = None

    if args.terminal:
        # Old Rich terminal dashboard
        try:
            from ui.dashboard import DashboardManager
            dashboard = DashboardManager(config)
            dashboard.start()
            logger.info("Terminal dashboard started")

            # Run optimization loop inline (terminal mode is synchronous)
            _optimization_loop(
                config, mem_optimizer, cpu_manager, gpu_router,
                usage_tracker, predictor, dashboard, logger, args
            )

        except Exception as e:
            logger.warning(f"Terminal dashboard unavailable: {e}")
        finally:
            if dashboard:
                dashboard.stop()
            usage_tracker.close()
            logger.info("✅ Optimizer stopped cleanly.")

    elif not args.headless:
        # GUI mode (default)
        try:
            from ui.gui_dashboard import GuiDashboard
            gui = GuiDashboard(config, lists_mgr)
            gui.set_analyzer(analyzer)
            dashboard = gui

            # Wire up callbacks
            def on_kill(pid, name):
                result = terminate_process(pid, name)
                gui.add_actions([result])

            def on_suspend(pid, name):
                result = suspend_process(pid, name)
                gui.add_actions([result])

            def on_resume(pid, name):
                result = resume_process(pid, name)
                gui.add_actions([result])

            def on_whitelist(name):
                lists_mgr.add_to_whitelist(name)

            def on_blacklist(name):
                lists_mgr.add_to_blacklist(name)

            def on_threshold(val):
                # Update config in memory (not persisted to file)
                config._data["memory"]["threshold_mb"] = val
                logger.info(f"Memory threshold changed to {val}MB")

            def on_auto_mode(enabled):
                config._data["memory"]["auto_mode"] = enabled
                logger.info(f"Auto mode {'enabled' if enabled else 'disabled'}")

            gui.on_kill_process = on_kill
            gui.on_suspend_process = on_suspend
            gui.on_resume_process = on_resume
            gui.on_add_whitelist = on_whitelist
            gui.on_add_blacklist = on_blacklist
            gui.on_threshold_change = on_threshold
            gui.on_auto_mode_change = on_auto_mode

            # Start optimization loop in background thread
            opt_thread = threading.Thread(
                target=_optimization_loop,
                args=(
                    config, mem_optimizer, cpu_manager, gpu_router,
                    usage_tracker, predictor, gui, logger, args
                ),
                daemon=True,
            )
            opt_thread.start()
            logger.info("GUI dashboard starting...")

            # Start GUI (blocking — runs on main thread)
            gui.start()

            # GUI closed — shut down
            _running = False
            opt_thread.join(timeout=5)

        except Exception as e:
            logger.error(f"GUI dashboard failed: {e}")
            import traceback
            traceback.print_exc()
        finally:
            usage_tracker.close()
            logger.info("✅ Optimizer stopped cleanly.")

    else:
        # Headless mode
        logger.info("Running in headless mode (no dashboard)")
        try:
            _optimization_loop(
                config, mem_optimizer, cpu_manager, gpu_router,
                usage_tracker, predictor, None, logger, args
            )
        except KeyboardInterrupt:
            pass
        finally:
            usage_tracker.close()
            logger.info("✅ Optimizer stopped cleanly.")


if __name__ == "__main__":
    main()
