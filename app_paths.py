from pathlib import Path
import sys
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent

# Read-only assets live in PyInstaller's extracted bundle, not beside the EXE.
RESOURCE_DIR = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
