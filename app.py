import sys

from PySide6 import QtWidgets

from ui_main import App
from ui_constants import DARK_STYLESHEET


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_STYLESHEET)
    window = App()
    window.show()
    sys.exit(app.exec())
