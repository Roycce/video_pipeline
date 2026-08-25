"""
Stream Auto Cutter — Main Entry Point.

Initialises the Qt Application, loads settings and profiles,
and shows the main window.
"""

import os
import sys
import traceback
from pathlib import Path

# Ensure UTF-8 encoding for Cyrillic paths on Windows
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    # Enable long path support (> 260 chars) on Windows 10+
    try:
        import ctypes
        ctypes.windll.kernel32.SetDllDirectoryW("")
    except Exception:
        pass

from PySide6.QtWidgets import QApplication, QMessageBox

from gui import MainWindow
from settings import Settings
from profiles import ProfileManager


def global_exception_handler(exctype, value, tb):
    """Catch unhandled exceptions and show them in a GUI dialog."""
    error_msg = "".join(traceback.format_exception(exctype, value, tb))
    print(error_msg, file=sys.stderr)
    
    # Try to show a message box if QApplication exists
    app = QApplication.instance()
    if app:
        msg_box = QMessageBox()
        msg_box.setIcon(QMessageBox.Icon.Critical)
        msg_box.setWindowTitle("Критическая ошибка")
        msg_box.setText("Произошла непредвиденная ошибка в приложении.")
        msg_box.setDetailedText(error_msg)
        msg_box.exec()
    
    sys.exit(1)


def main():
    # Install global exception handler
    sys.excepthook = global_exception_handler
    
    # Initialize application
    app = QApplication(sys.argv)
    
    # Load settings and profiles from the same directory as main.py or executable
    if getattr(sys, 'frozen', False):
        base_dir = Path(sys.executable).parent.absolute()
    else:
        base_dir = Path(__file__).parent.absolute()

    settings_path = base_dir / "settings.json"
    profiles_path = base_dir / "profiles.json"
    
    settings = Settings(settings_path)
    profiles = ProfileManager(profiles_path)
    
    # Create and show main window
    window = MainWindow(settings, profiles)
    window.show()
    
    # Start event loop
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
