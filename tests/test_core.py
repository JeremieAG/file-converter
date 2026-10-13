from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from file_converter import core
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
    find_ffmpeg,
    parse_media_info,
)

from media import TOOLS_MISSING, audio_packets_md5, decode_errors, ffprobe, make_audio, make_video

DURATION = 10.0


@unittest.skipIf(TOOLS_MISSING, "ffmpeg/ffprobe introuvables dans le PATH")
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

    # --- appels système

    @unittest.skipUnless(sys.platform == "win32", "CREATE_NO_WINDOW n'existe que sous Windows")
    def test_every_subprocess_call_uses_create_no_window(self):
        real_popen = subprocess.Popen
        flags = []

        def recording_popen(*args, **kwargs):
            flags.append(kwargs.get("creationflags", 0))
            return real_popen(*args, **kwargs)

        with mock.patch.object(core.subprocess, "Popen", recording_popen):
            self.convert(self.video, MP3)
        self.assertGreaterEqual(len(flags), 2, "analyse + conversion")
        self.assertTrue(all(f & subprocess.CREATE_NO_WINDOW for f in flags), flags)

    def test_probe_reads_duration_and_codec_without_ffprobe(self):
        info = core.probe(self.video)
        self.assertAlmostEqual(info.duration, DURATION, delta=0.05)
        self.assertEqual(info.audio_codec, "aac")
        self.assertFalse(core.probe(self.silent_video).has_audio)


# Sorties réelles de « ffmpeg -hide_banner -i … » (ffmpeg 9.0).
MP4_AAC = """\
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'test.mp4':
  Metadata:
    major_brand     : isom
    encoder         : Lavf63.1.102
  Duration: 00:00:10.00, start: 0.000000, bitrate: 123 kb/s
  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p(progressive), 640x360, 25 fps (default)
    Metadata:
      handler_name    : VideoHandler
  Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, mono, fltp, 69 kb/s (default)
    Metadata:
      handler_name    : SoundHandler
At least one output file must be specified
"""

MKV_MP3_WITH_TRAP_TAG = """\
Input #0, matroska,webm, from 'a.mkv':
  Metadata:
    title           : Duration: 99:00:00.00 piège
    ENCODER         : Lavf63.1.102
  Duration: 00:00:03.03, start: 0.000000, bitrate: 111 kb/s
  Stream #0:0: Video: h264 (High 4:4:4 Predictive), yuv444p(tv, progressive), 320x240, 25 fps
    Metadata:
      DURATION        : 00:00:03.000000000
  Stream #0:1: Audio: mp3 (mp3float), 44100 Hz, mono, fltp, 64 kb/s
    Metadata:
      DURATION        : 00:00:03.025000000
At least one output file must be specified
"""

TS_TWO_AUDIO_TRACKS = """\
Input #0, mpegts, from 'multi.ts':
  Duration: 00:00:03.02, start: 1.416778, bitrate: 915 kb/s
  Program 1
    Metadata:
      service_name    : Service01
  Stream #0:0[0x100]: Video: mpeg2video (Main) ([2][0][0][0] / 0x0002), yuv420p(tv, progressive), 320x240
  Stream #0:2[0x102]: Audio: aac (LC) ([15][0][0][0] / 0x000F), 44100 Hz, mono, fltp, 71 kb/s
  Stream #0:1[0x101]: Audio: mp2 (mp3float) ([3][0][0][0] / 0x0003), 44100 Hz, mono, fltp, 384 kb/s
At least one output file must be specified
"""

VIDEO_ONLY_UNKNOWN_DURATION = """\
Input #0, h264, from 'raw.h264':
  Duration: N/A, bitrate: N/A
  Stream #0:0: Video: h264 (High), yuv420p(progressive), 320x240, 25 fps, 25 tbr, 1200k tbn
At least one output file must be specified
"""


class ParseMediaInfoTests(unittest.TestCase):
    def test_mp4_with_aac(self):
        info = parse_media_info(MP4_AAC)
        self.assertEqual(info.duration, 10.0)
        self.assertTrue(info.has_audio)
        self.assertEqual(info.audio_codec, "aac")

    def test_metadata_containing_duration_is_ignored(self):
        info = parse_media_info(MKV_MP3_WITH_TRAP_TAG)
        self.assertAlmostEqual(info.duration, 3.03)
        self.assertEqual(info.audio_codec, "mp3")

    def test_first_audio_track_is_the_lowest_index(self):
        # -map 0:a:0 prend la piste #0:1 (mp2), même si #0:2 est listée avant.
        self.assertEqual(parse_media_info(TS_TWO_AUDIO_TRACKS).audio_codec, "mp2")

    def test_no_audio_and_unknown_duration(self):
        info = parse_media_info(VIDEO_ONLY_UNKNOWN_DURATION)
        self.assertIsNone(info.duration)
        self.assertFalse(info.has_audio)
        self.assertIsNone(info.audio_codec)

    def test_long_duration(self):
        info = parse_media_info("Input #0, wav, from 'x.wav':\n  Duration: 12:34:56.78, bitrate: 1411 kb/s\n")
        self.assertAlmostEqual(info.duration, 12 * 3600 + 34 * 60 + 56.78)


class FindFfmpegTests(unittest.TestCase):
    """Ordre de recherche : à côté de l'exécutable empaqueté, puis _internal, puis le PATH."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.app_dir = Path(tmp.name)
        self.internal = self.app_dir / "_internal"
        self.internal.mkdir()
        self.path_ffmpeg = str(self.app_dir / "ailleurs" / "ffmpeg.exe")

    def find(self, frozen=True):
        patches = [mock.patch.object(core.shutil, "which", return_value=self.path_ffmpeg)]
        if frozen:
            patches += [
                mock.patch.object(sys, "frozen", True, create=True),
                mock.patch.object(sys, "executable", str(self.app_dir / "FileConverter.exe")),
                mock.patch.object(sys, "_MEIPASS", str(self.internal), create=True),
            ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return find_ffmpeg()

    def touch(self, directory: Path) -> str:
        path = directory / core.FFMPEG_EXECUTABLE
        path.write_bytes(b"")
        return str(path)

    def test_next_to_executable_wins_over_path(self):
        expected = self.touch(self.app_dir)
        self.touch(self.internal)
        self.assertEqual(self.find(), expected)

    def test_internal_dir_when_not_next_to_executable(self):
        expected = self.touch(self.internal)
        self.assertEqual(self.find(), expected)

    def test_falls_back_to_path(self):
        self.assertEqual(self.find(), self.path_ffmpeg)

    def test_not_frozen_uses_path_only(self):
        self.touch(self.app_dir)
        self.assertEqual(self.find(frozen=False), self.path_ffmpeg)


if __name__ == "__main__":
    unittest.main()
