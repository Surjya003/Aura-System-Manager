"""
System Tray Integration
========================
Provides a system tray icon with menu options for the optimizer using pystray.
"""

import os
import threading
from typing import Callable, Optional

from utils.logger import get_logger

logger = get_logger()


# Tray icon image (simple colored square generated with Pillow)
def _create_icon_image(color: str = "green"):
    """Create a simple tray icon image using Pillow.

    Args:
        color: "green" = normal, "yellow" = moderate load, "red" = high load.
    """
    try:
        from PIL import Image, ImageDraw

        colors = {
            "green": "#00E676",
            "yellow": "#FFD600",
            "red": "#FF1744",
            "blue": "#2979FF",
        }
        fill = colors.get(color, colors["green"])

        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Draw a rounded rectangle as the icon
        draw.rounded_rectangle(
            [(4, 4), (60, 60)],
            radius=12,
            fill=fill,
        )

        # Draw "SO" text (System Optimizer)
        try:
            from PIL import ImageFont
            font = ImageFont.truetype("arial.ttf", 22)
        except Exception:
            font = ImageFont.load_default()

        draw.text((12, 16), "SO", fill="white", font=font)
        return img

    except ImportError:
        logger.warning("Pillow not installed — tray icon may not display correctly")
        # Return a minimal 1x1 image as fallback
        from PIL import Image
        return Image.new("RGBA", (64, 64), (0, 200, 100, 255))


class SystemTray:
    """System tray icon with optimizer controls."""

    def __init__(
        self,
        on_show_dashboard: Optional[Callable] = None,
        on_pause_resume: Optional[Callable] = None,
        on_exit: Optional[Callable] = None,
    ):
        self._on_show_dashboard = on_show_dashboard
        self._on_pause_resume = on_pause_resume
        self._on_exit = on_exit
        self._icon = None
        self._paused = False
        self._thread: Optional[threading.Thread] = None

    def _create_menu(self):
        """Create the tray icon menu."""
        try:
            import pystray
            from pystray import MenuItem as Item

            pause_label = "▶ Resume" if self._paused else "⏸ Pause"

            return pystray.Menu(
                Item("📊 Show Dashboard", self._handle_show_dashboard),
                Item(pause_label, self._handle_pause_resume),
                pystray.Menu.SEPARATOR,
                Item("ℹ️ About", self._handle_about),
                pystray.Menu.SEPARATOR,
                Item("❌ Exit", self._handle_exit),
            )
        except ImportError:
            logger.error("pystray not installed")
            return None

    def _handle_show_dashboard(self, icon, item):
        if self._on_show_dashboard:
            self._on_show_dashboard()

    def _handle_pause_resume(self, icon, item):
        self._paused = not self._paused
        if self._on_pause_resume:
            self._on_pause_resume(self._paused)
        # Update icon color
        color = "yellow" if self._paused else "green"
        icon.icon = _create_icon_image(color)
        icon.update_menu()
        status = "paused" if self._paused else "resumed"
        logger.info(f"Optimizer {status}")

    def _handle_about(self, icon, item):
        logger.info("Intelligent System Resource Optimizer v1.0")

    def _handle_exit(self, icon, item):
        logger.info("Exit requested from tray")
        icon.stop()
        if self._on_exit:
            self._on_exit()

    def start(self) -> None:
        """Start the system tray icon (blocking — run in a thread)."""
        try:
            import pystray

            self._icon = pystray.Icon(
                name="SystemOptimizer",
                icon=_create_icon_image("green"),
                title="System Resource Optimizer",
                menu=self._create_menu(),
            )
            self._icon.run()
        except ImportError:
            logger.error("pystray not available — tray icon disabled")
        except Exception as e:
            logger.error(f"Failed to start tray icon: {e}")

    def start_threaded(self) -> threading.Thread:
        """Start the tray icon in a background thread."""
        self._thread = threading.Thread(target=self.start, daemon=True)
        self._thread.start()
        logger.info("System tray icon started")
        return self._thread

    def update_status(self, load_level: str = "green") -> None:
        """Update the tray icon color based on system load.

        Args:
            load_level: "green", "yellow", or "red".
        """
        if self._icon:
            try:
                self._icon.icon = _create_icon_image(load_level)
            except Exception:
                pass

    def stop(self) -> None:
        """Stop the tray icon."""
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass

    @property
    def is_paused(self) -> bool:
        return self._paused
