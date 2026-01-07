import sys

from PySide6 import QtWidgets

from ui_main import App


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = App()
    window.show()
    sys.exit(app.exec())
