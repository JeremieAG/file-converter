from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication

from file_converter.core import FLAC, MP3, ConversionOptions, missing_tools
from file_converter.ui import MainWindow, State
from file_converter.worker import ConversionWorker

from media import ffprobe, make_audio, make_video

app = QApplication.instance() or QApplication([])


def wait_until(predicate, timeout=60.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise TimeoutError("condition non atteinte")
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


@unittest.skipIf(missing_tools(), "ffmpeg/ffprobe introuvables dans le PATH")
class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        media = Path(cls._tmp.name)
        cls.video = make_video(media / "test.mp4", 10)
        cls.silent_video = make_video(media / "muet.mp4", 10, audio_codec=None)
        cls.long_audio = make_audio(media / "long.flac", 20 * 60)
        cls.garbage = media / "corrompu.mp4"
        cls.garbage.write_bytes(b"\x00\x01garbage" * 500)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self.out = Path(tempfile.mkdtemp(dir=self._tmp.name))

    def run_worker(self, worker, cancel_on_first_progress=False):
        events = []
        worker.file_started.connect(lambda i: events.append(("started", i)))
        worker.file_succeeded.connect(lambda i, path, copied: events.append(("ok", i, path, copied)))
        worker.file_failed.connect(lambda i, msg: events.append(("failed", i, msg)))
        worker.file_cancelled.connect(lambda i: events.append(("cancelled", i)))

        def on_progress(i, percent):
            events.append(("progress", i, percent))
            if cancel_on_first_progress and 0 < percent < 100:
                worker.cancel()

        worker.file_progress.connect(on_progress)
        worker.start()
        wait_until(worker.isFinished)
        return events

    def test_worker_keeps_going_after_errors(self):
        jobs = [(0, self.video), (1, self.silent_video), (2, self.garbage)]
        events = self.run_worker(ConversionWorker(jobs, ConversionOptions(MP3, output_dir=self.out)))
        outcomes = {e[1]: e for e in events if e[0] in ("ok", "failed", "cancelled")}
        self.assertEqual(outcomes[0][0], "ok")
        self.assertEqual(Path(outcomes[0][2]), self.out / "test.mp3")
        self.assertEqual(outcomes[1][:2], ("failed", 1))
        self.assertIn("aucune piste audio", outcomes[1][2])
        self.assertEqual(outcomes[2][:2], ("failed", 2))
        self.assertIn("Format invalide", outcomes[2][2])
        self.assertIn(("progress", 0, 100), events)

    def test_worker_cancel_stops_current_and_skips_remaining(self):
        jobs = [(0, self.long_audio), (1, self.video)]
        worker = ConversionWorker(jobs, ConversionOptions(MP3, output_dir=self.out))
        events = self.run_worker(worker, cancel_on_first_progress=True)
        self.assertIn(("cancelled", 0), events)
        self.assertIn(("cancelled", 1), events)
        self.assertNotIn(("started", 1), events)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_window_drop_and_convert(self):
        window = MainWindow()
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(p)) for p in (self.video, self.silent_video, self.video)])
        drop = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        window.dropEvent(drop)
        self.assertEqual(window.table.rowCount(), 2, "les doublons sont ignorés")

        window.format_combo.setCurrentIndex(window.format_combo.findData(FLAC))
        self.assertFalse(window.quality_combo.isEnabled())
        window.same_dir_check.setChecked(False)
        window.output_dir_edit.setText(str(self.out))

        window.convert_button.click()
        self.assertTrue(window.cancel_button.isEnabled())
        self.assertFalse(window.convert_button.isEnabled())
        wait_until(lambda: not window._is_running())

        self.assertEqual([e.state for e in window._entries], [State.DONE, State.FAILED])
        self.assertIn("test.flac", window.table.item(0, 1).text())
        self.assertIn("aucune piste audio", window.table.item(1, 1).text())
        self.assertEqual(window.table.cellWidget(0, 2).value(), 100)
        self.assertEqual(ffprobe(self.out / "test.flac")["streams"][0]["codec_name"], "flac")
        self.assertEqual(window.summary_label.text(), "1 terminé(s), 1 en erreur.")

        # Une deuxième conversion ne refait pas les fichiers déjà terminés.
        window.convert_button.click()
        wait_until(lambda: not window._is_running())
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ["test.flac"])
        window.close()

    def test_window_cancel(self):
        window = MainWindow()
        window.add_files([self.long_audio])
        window.same_dir_check.setChecked(False)
        window.output_dir_edit.setText(str(self.out))
        window.convert_button.click()
        wait_until(lambda: 0 < window.table.cellWidget(0, 2).value() < 100)
        window.cancel_button.click()
        wait_until(lambda: not window._is_running(), timeout=10)
        self.assertEqual(window._entries[0].state, State.CANCELLED)
        self.assertEqual(list(self.out.iterdir()), [])
        window.close()


if __name__ == "__main__":
    unittest.main()
