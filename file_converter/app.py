"""Point d'entrée de l'application."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from .core import missing_tools
from .ui import MainWindow

INSTALL_HELP = (
    "Installez ffmpeg (ffprobe est fourni avec), puis relancez l'application :\n\n"
    "• Windows : winget install Gyan.FFmpeg\n"
    "• macOS : brew install ffmpeg\n"
    "• Linux : sudo apt install ffmpeg (ou l'équivalent de votre distribution)\n\n"
    "Si ffmpeg est déjà installé, ajoutez son dossier « bin » à la variable d'environnement PATH. "
    "Pour vérifier, tapez « ffmpeg -version » dans un nouveau terminal."
)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("File Converter")

    missing = missing_tools()
    if missing:
        QMessageBox.critical(
            None,
            "ffmpeg introuvable",
            f"Programme(s) introuvable(s) dans le PATH : {', '.join(missing)}.\n\n{INSTALL_HELP}",
        )
        return 1

    window = MainWindow()
    window.show()
    return app.exec()
