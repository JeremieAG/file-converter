"""Point d'entrée de l'application."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from .core import find_ffmpeg
from .ui import MainWindow

ICON_PATH = Path(__file__).resolve().parent / "resources" / "app.ico"

MISSING_FFMPEG_INSTALLED = (
    "ffmpeg.exe est introuvable.\n\n"
    "Il est normalement installé avec l'application, dans le même dossier que FileConverter.exe. "
    "Il a peut-être été supprimé ou mis en quarantaine par un antivirus : "
    "réinstallez l'application pour le restaurer."
)

MISSING_FFMPEG_FROM_SOURCE = (
    "ffmpeg est introuvable dans le PATH.\n\n"
    "Installez-le, puis relancez l'application :\n\n"
    "• Windows : winget install Gyan.FFmpeg\n"
    "• macOS : brew install ffmpeg\n"
    "• Linux : sudo apt install ffmpeg (ou l'équivalent de votre distribution)\n\n"
    "Si ffmpeg est déjà installé, ajoutez son dossier « bin » à la variable d'environnement PATH. "
    "Pour vérifier, tapez « ffmpeg -version » dans un nouveau terminal."
)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("File Converter")
    app.setWindowIcon(QIcon(str(ICON_PATH)))

    if find_ffmpeg() is None:
        frozen = getattr(sys, "frozen", False)
        QMessageBox.critical(
            None,
            "ffmpeg introuvable",
            MISSING_FFMPEG_INSTALLED if frozen else MISSING_FFMPEG_FROM_SOURCE,
        )
        return 1

    window = MainWindow()
    # Fichiers passés en argument (« Ouvrir avec », dépôt sur le raccourci ou l'exécutable).
    window.add_files(Path(arg) for arg in app.arguments()[1:] if Path(arg).is_file())
    window.show()
    return app.exec()
