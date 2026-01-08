import importlib.util

if importlib.util.find_spec("PyQt5") is None:
    raise SystemExit("PyQt5 is required. Install it with: python -m pip install PyQt5")

from ui_main_qt import main

if __name__ == "__main__":
    raise SystemExit(main())
