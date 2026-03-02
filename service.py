"""
Service Wrapper
================
Runs the optimizer in a background thread while the system tray icon
runs on the main thread. This is the recommended entry point for
day-to-day use.

Usage:
    python service.py               # Start with tray icon
    python service.py --no-admin    # Skip admin check
"""

import argparse
import sys
import threading
import time

from utils.admin import ensure_admin
from utils.logger import setup_logger, get_logger
from core.config import Config


def main():
    parser = argparse.ArgumentParser(description="System Optimizer Service")
    parser.add_argument("--no-admin", action="store_true", help="Skip admin elevation")
    parser.add_argument("--config", type=str, default="config.yaml", help="Config path")
    args = parser.parse_args()

    # Admin check
    if not args.no_admin:
        ensure_admin()

    # Initialize
    config = Config(args.config)
    logger = setup_logger(log_level=config.log_level, log_file=config.log_file)
    logger.info("⚡ System Optimizer Service starting...")

    # ── Background optimizer thread ──────────────────────────────────────
    optimizer_running = threading.Event()
    optimizer_running.set()
    optimizer_paused = threading.Event()

    def run_optimizer():
        """Run the optimizer loop in a background thread."""
        from core.telemetry import get_system_snapshot
        from core.process_scanner import scan_all_processes, get_foreground_pid
        from core.memory_optimizer import MemoryOptimizer
        from core.lists_manager import ListsManager
        from core.cpu_affinity import CpuAffinityManager
        from core.gpu_router import GpuRouter
        from core.app_classifier import AppClassifier
        from core.usage_tracker import UsageTracker
        from core.priority_predictor import PriorityPredictor

        classifier = AppClassifier(config)
        lists_mgr = ListsManager(config)
        mem_optimizer = MemoryOptimizer(config, lists_mgr)
        cpu_manager = CpuAffinityManager(config, classifier)
        gpu_router = GpuRouter(config, classifier)
        usage_tracker = UsageTracker(config)
        predictor = PriorityPredictor(config, usage_tracker)
        predictor.load_model()

        tick = 0
        while optimizer_running.is_set():
            if optimizer_paused.is_set():
                time.sleep(1)
                continue

            tick += 1
            try:
                fg_pid = get_foreground_pid()
                processes = scan_all_processes(fg_pid)
                usage_tracker.update_active_processes(processes)
                predictor.clear_cache()

                # Memory optimization
                mem_optimizer.optimize(processes)

                # CPU affinity
                if config.cpu_routing_enabled:
                    cpu_manager.optimize_affinities(processes)

                # GPU routing (every 10 ticks)
                if config.gpu_routing_enabled and tick % 10 == 1:
                    gpu_router.optimize_gpu_routing(processes)

                # Retrain ML model periodically
                if tick % 100 == 0:
                    predictor.maybe_retrain()

                config.reload_if_changed()
            except Exception as e:
                logger.error(f"Optimizer tick error: {e}")

            time.sleep(config.scan_interval)

        usage_tracker.close()
        logger.info("Optimizer thread stopped")

    optimizer_thread = threading.Thread(target=run_optimizer, daemon=True)
    optimizer_thread.start()
    logger.info("Optimizer thread started")

    # ── System tray (main thread) ────────────────────────────────────────
    def on_show_dashboard():
        logger.info("Dashboard requested (launch main.py for dashboard view)")

    def on_pause_resume(paused: bool):
        if paused:
            optimizer_paused.set()
        else:
            optimizer_paused.clear()

    def on_exit():
        logger.info("Exit requested")
        optimizer_running.clear()
        optimizer_thread.join(timeout=5)
        logger.info("✅ Service stopped cleanly")
        sys.exit(0)

    try:
        from ui.tray import SystemTray
        tray = SystemTray(
            on_show_dashboard=on_show_dashboard,
            on_pause_resume=on_pause_resume,
            on_exit=on_exit,
        )
        logger.info("Starting system tray icon (main thread)...")
        tray.start()  # Blocking — runs main tray event loop
    except ImportError:
        logger.warning("pystray not available — running headless")
        # Without tray, just keep running
        try:
            while optimizer_running.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            optimizer_running.clear()
            optimizer_thread.join(timeout=5)
            logger.info("✅ Service stopped cleanly")


if __name__ == "__main__":
    main()
