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


def main():
    initialize()
    apply_high_dpi_policy()

    app = QApplication(sys.argv)
    app.setApplicationName("Socksicle")
    app.setDesktopFileName(desktop_file_name())

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