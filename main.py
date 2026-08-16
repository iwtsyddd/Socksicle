#!/usr/bin/env python3
"""Application entry point for Socksicle (Windows and Linux).

The shared startup flow lives here; platform-specific behaviour is delegated
to :mod:`utils.platform_startup`, which no-ops on every platform where a
Windows-only feature does not apply.
"""
import sys

# Must be imported before PySide6 so the Windows Qt environment variables
# are applied before Qt initialises.
from utils.platform_startup import (  # noqa: E402
    apply_high_dpi_policy,
    desktop_file_name,
    initialize,
    install_native_handlers,
)
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from ui.main_window import RoundedWindow
from utils.platform_utils import get_app_dir
from utils.startup_utils import (DECLINED_REASON, provision_backend,
                                 show_provisioning_failure)


def _apply_platform_style(app):
    """Non-Windows: consistent Fusion style + M3 dark palette.

    Widgets not fully covered by per-widget QSS can otherwise fall back to
    whatever the desktop QPA theme provides (invisible text, transparent
    widgets), so pin a coherent dark look instead.  Windows keeps its native
    look and is skipped.  A palette failure must never prevent startup.
    """
    if sys.platform == "win32":
        return
    try:
        from PySide6.QtGui import QColor, QPalette

        from utils.theme import M3Theme

        theme = M3Theme()
        palette = QPalette()
        roles = {
            QPalette.ColorRole.Window: theme.surface,
            QPalette.ColorRole.WindowText: theme.on_surface,
            QPalette.ColorRole.Base: theme.surface_container_highest,
            QPalette.ColorRole.AlternateBase: theme.surface_container,
            QPalette.ColorRole.ToolTipBase: theme.surface_container_highest,
            QPalette.ColorRole.ToolTipText: theme.on_surface,
            QPalette.ColorRole.Text: theme.on_surface,
            QPalette.ColorRole.Button: theme.surface_container_high,
            QPalette.ColorRole.ButtonText: theme.on_surface,
            QPalette.ColorRole.BrightText: theme.error,
            QPalette.ColorRole.Highlight: theme.primary,
            QPalette.ColorRole.HighlightedText: theme.on_primary,
            QPalette.ColorRole.Link: theme.primary,
            QPalette.ColorRole.PlaceholderText: theme.on_surface_variant,
        }
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive,
                      QPalette.ColorGroup.Disabled):
            for role, color in roles.items():
                palette.setColor(group, role, QColor(color))
        app.setStyle("Fusion")
        app.setPalette(palette)
    except Exception:
        pass


def main():
    initialize()
    apply_high_dpi_policy()

    app = QApplication(sys.argv)
    app.setApplicationName("Socksicle")
    app.setDesktopFileName(desktop_file_name())
    _apply_platform_style(app)

    # Set icon
    icon_path = get_app_dir() / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # Ensure the proxy backend: reuse existing, otherwise download.
    result = provision_backend()
    if result is None or not result.ok:
        if result is not None and result.reason != DECLINED_REASON:
            show_provisioning_failure(result)
            sys.exit(1)
        # User declined or cancelled — start without backend.

    # Kill engine processes a previously crashed session left behind; they
    # would otherwise hold the local/API ports and break the next connect.
    from utils.engines.engine_manager import cleanup_stale_core_processes
    cleanup_stale_core_processes()

    window = RoundedWindow()
    install_native_handlers(app, window)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()