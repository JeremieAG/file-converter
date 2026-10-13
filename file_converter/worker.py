"""Thread Qt qui enchaîne les conversions sans bloquer l'interface."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .core import Conversion, ConversionCancelled, ConversionError, ConversionOptions


class ConversionWorker(QThread):
    """Convertit une liste de fichiers l'un après l'autre.

    Chaque fichier est identifié par un entier choisi par l'appelant (la ligne du tableau).
    """

    file_started = Signal(int)
    # Pourcentage de 0 à 100, ou -1 si la durée est inconnue.
    file_progress = Signal(int, int)
    # Identifiant, chemin du fichier produit, audio copié sans réencodage.
    file_succeeded = Signal(int, str, bool)
    file_failed = Signal(int, str)
    file_cancelled = Signal(int)

    def __init__(self, jobs: list[tuple[int, Path]], options: ConversionOptions, parent=None):
        super().__init__(parent)
        self._jobs = list(jobs)
        self._options = options
        self._lock = threading.Lock()
        self._current: Conversion | None = None
        self._cancel_requested = False

    def cancel(self) -> None:
        """Arrête la conversion en cours et ignore les fichiers restants."""
        with self._lock:
            self._cancel_requested = True
            if self._current is not None:
                self._current.cancel()

    def run(self) -> None:
        for job_id, source in self._jobs:
            with self._lock:
                if self._cancel_requested:
                    self.file_cancelled.emit(job_id)
                    continue
                conversion = Conversion(source, self._options)
                self._current = conversion

            self.file_started.emit(job_id)
            try:
                result = conversion.run(self._progress_reporter(job_id))
            except ConversionCancelled:
                self.file_cancelled.emit(job_id)
            except ConversionError as exc:
                self.file_failed.emit(job_id, str(exc))
            except Exception as exc:  # un bug ne doit ni tuer le thread ni bloquer la file
                self.file_failed.emit(job_id, f"Erreur inattendue : {exc}")
            else:
                self.file_succeeded.emit(job_id, str(result.output), result.stream_copied)
            finally:
                with self._lock:
                    self._current = None

    def _progress_reporter(self, job_id: int):
        last_percent: int | None = None

        def report(fraction: float | None) -> None:
            nonlocal last_percent
            percent = -1 if fraction is None else round(fraction * 100)
            if percent != last_percent:  # évite d'inonder la boucle d'événements de l'UI
                last_percent = percent
                self.file_progress.emit(job_id, percent)

        return report
