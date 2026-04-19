import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from cove_converter.binaries import resource_path
from cove_converter.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Cove Universal Converter")
    app.setStyle("Fusion")

    icon_file = resource_path("cove_icon.png")
    if icon_file.is_file():
        app.setWindowIcon(QIcon(str(icon_file)))

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
