from __future__ import annotations

import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

from file_converter.core import (
    FLAC,
    M4A,
    MP3,
    MP3_QUALITIES,
    WAV,
    Conversion,
    ConversionCancelled,
    ConversionError,
    ConversionOptions,
    missing_tools,
)

from media import audio_packets_md5, decode_errors, ffprobe, make_audio, make_video

DURATION = 10.0


@unittest.skipIf(missing_tools(), "ffmpeg/ffprobe introuvables dans le PATH")
class ConversionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        media = Path(cls._tmp.name)
        cls.video = make_video(media / "test.mp4", DURATION, audio_codec="aac")
        cls.video_mp3_audio = make_video(media / "test_mp3.mkv", DURATION, audio_codec="libmp3lame")
        cls.silent_video = make_video(media / "muet.mp4", DURATION, audio_codec=None)
        cls.long_audio = make_audio(media / "long.flac", 20 * 60)
        cls.garbage = media / "corrompu.mp4"
        cls.garbage.write_bytes(b"ceci n'est pas une video " * 1000)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self.out = Path(tempfile.mkdtemp(dir=self._tmp.name))

    def convert(self, source, fmt, **options):
        progress = []
        options.setdefault("output_dir", self.out)
        result = Conversion(source, ConversionOptions(fmt, **options)).run(progress.append)
        return result, progress

    def assert_valid_audio(self, path: Path, codec: str, container: str) -> dict:
        info = ffprobe(path)
        self.assertEqual([s["codec_type"] for s in info["streams"]], ["audio"], "une seule piste, audio")
        self.assertEqual(info["streams"][0]["codec_name"], codec)
        self.assertIn(container, info["format"]["format_name"].split(","))
        self.assertAlmostEqual(float(info["format"]["duration"]), DURATION, delta=0.15)
        self.assertEqual(decode_errors(path), "", "le fichier doit se décoder sans erreur")
        return info

    # --- formats de sortie

    def test_mp3_every_quality(self):
        for quality in MP3_QUALITIES:
            with self.subTest(quality=quality.label):
                out = Path(tempfile.mkdtemp(dir=self.out))
                result, _ = self.convert(self.video, MP3, mp3_quality=quality, output_dir=out)
                self.assertEqual(result.output, out / "test.mp3")
                self.assertFalse(result.stream_copied)
                info = self.assert_valid_audio(result.output, "mp3", "mp3")
                if quality.args[0] == "-b:a":
                    expected = int(quality.args[1].removesuffix("k")) * 1000
                    self.assertEqual(int(info["streams"][0]["bit_rate"]), expected)

    def test_m4a_copies_aac_without_reencoding(self):
        result, _ = self.convert(self.video, M4A)
        self.assertEqual(result.output.suffix, ".m4a")
        self.assertTrue(result.stream_copied)
        self.assert_valid_audio(result.output, "aac", "m4a")
        self.assertEqual(audio_packets_md5(result.output), audio_packets_md5(self.video))

    def test_m4a_reencodes_non_aac_audio(self):
        result, _ = self.convert(self.video_mp3_audio, M4A)
        self.assertFalse(result.stream_copied)
        self.assert_valid_audio(result.output, "aac", "m4a")

    def test_wav(self):
        result, _ = self.convert(self.video, WAV)
        self.assertEqual(result.output.suffix, ".wav")
        self.assert_valid_audio(result.output, "pcm_s16le", "wav")

    def test_flac(self):
        result, _ = self.convert(self.video, FLAC)
        self.assertEqual(result.output.suffix, ".flac")
        self.assert_valid_audio(result.output, "flac", "flac")

    # --- progression

    def test_progress_is_monotonic_and_reaches_100(self):
        _, progress = self.convert(self.video, FLAC)
        self.assertGreaterEqual(len(progress), 2)
        self.assertTrue(all(0.0 <= p <= 1.0 for p in progress), progress)
        self.assertEqual(progress, sorted(progress))
        self.assertEqual(progress[-1], 1.0)

    def test_progress_reports_intermediate_values_on_long_file(self):
        progress = []
        Conversion(self.long_audio, ConversionOptions(WAV, output_dir=self.out)).run(progress.append)
        self.assertTrue(any(0.0 < p < 1.0 for p in progress), progress)
        self.assertEqual(progress[-1], 1.0)

    # --- dossier de sortie et noms de fichiers

    def test_default_output_dir_is_source_dir(self):
        source_dir = Path(tempfile.mkdtemp(dir=self._tmp.name))
        source = Path(shutil.copy(self.video, source_dir / "clip.mp4"))
        result = Conversion(source, ConversionOptions(MP3)).run()
        self.assertEqual(result.output, source_dir / "clip.mp3")

    def test_never_overwrites_existing_files(self):
        existing = self.out / "test.mp3"
        existing.write_bytes(b"ne pas toucher")
        first, _ = self.convert(self.video, MP3)
        second, _ = self.convert(self.video, MP3)
        self.assertEqual(first.output, self.out / "test (1).mp3")
        self.assertEqual(second.output, self.out / "test (2).mp3")
        self.assertEqual(existing.read_bytes(), b"ne pas toucher")

    def test_same_format_as_source_does_not_overwrite_source(self):
        source_dir = Path(tempfile.mkdtemp(dir=self._tmp.name))
        source = Path(shutil.copy(self.long_audio, source_dir / "son.flac"))
        before = source.read_bytes()
        result = Conversion(source, ConversionOptions(FLAC)).run()
        self.assertEqual(result.output, source_dir / "son (1).flac")
        self.assertEqual(source.read_bytes(), before)

    # --- erreurs

    def assert_fails_cleanly(self, source, expected_message):
        with self.assertRaises(ConversionError) as ctx:
            self.convert(source, MP3)
        self.assertIn(expected_message, str(ctx.exception))
        self.assertEqual(list(self.out.iterdir()), [], "aucun fichier partiel ne doit rester")

    def test_file_without_audio(self):
        self.assert_fails_cleanly(self.silent_video, "aucune piste audio")

    def test_invalid_file(self):
        self.assert_fails_cleanly(self.garbage, "Format invalide")

    def test_missing_file(self):
        self.assert_fails_cleanly(self.out / "absent.mp4", "introuvable")

    def test_missing_output_dir(self):
        missing_dir = self.out / "absent"
        with self.assertRaises(ConversionError) as ctx:
            self.convert(self.video, MP3, output_dir=missing_dir)
        self.assertIn("Impossible de créer le fichier de sortie", str(ctx.exception))

    # --- annulation

    def test_cancel_during_conversion_kills_ffmpeg_and_removes_output(self):
        conversion = Conversion(self.long_audio, ConversionOptions(MP3, output_dir=self.out))
        seen = []

        def on_progress(fraction):
            seen.append(fraction)
            if 0.0 < fraction < 1.0:
                # Annule depuis un autre thread, comme le bouton de l'interface.
                threading.Thread(target=conversion.cancel).start()

        start = time.monotonic()
        with self.assertRaises(ConversionCancelled):
            conversion.run(on_progress)
        self.assertLess(time.monotonic() - start, 10)
        self.assertLess(max(seen), 1.0, "la conversion ne doit pas être allée au bout")
        self.assertEqual(list(self.out.iterdir()), [])

    def test_cancel_before_start(self):
        conversion = Conversion(self.video, ConversionOptions(MP3, output_dir=self.out))
        conversion.cancel()
        with self.assertRaises(ConversionCancelled):
            conversion.run()
        self.assertEqual(list(self.out.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
