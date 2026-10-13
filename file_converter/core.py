"""Logique de conversion ffmpeg, indépendante de l'interface graphique."""

from __future__ import annotations

import itertools
import re
import shutil
import subprocess
import sys
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

# Sous Windows, aucun appel à ffmpeg ne doit ouvrir de fenêtre de console : l'application
# empaquetée n'en a pas, et Windows en créerait une pour chaque processus console lancé.
_POPEN_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

FFMPEG_EXECUTABLE = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
PROBE_TIMEOUT_S = 60


class ConversionError(Exception):
    """Échec de conversion, avec un message destiné à l'utilisateur."""


class ConversionCancelled(Exception):
    """La conversion a été annulée par l'utilisateur."""


@dataclass(frozen=True)
class Mp3Quality:
    label: str
    args: tuple[str, ...]


MP3_QUALITIES = (
    Mp3Quality("320 kbit/s (CBR)", ("-b:a", "320k")),
    Mp3Quality("256 kbit/s (CBR)", ("-b:a", "256k")),
    Mp3Quality("192 kbit/s (CBR)", ("-b:a", "192k")),
    Mp3Quality("128 kbit/s (CBR)", ("-b:a", "128k")),
    Mp3Quality("VBR V0 (~245 kbit/s)", ("-q:a", "0")),
    Mp3Quality("VBR V2 (~190 kbit/s)", ("-q:a", "2")),
)


@dataclass(frozen=True)
class OutputFormat:
    key: str
    label: str
    extension: str


MP3 = OutputFormat("mp3", "MP3", "mp3")
M4A = OutputFormat("m4a", "M4A (AAC)", "m4a")
WAV = OutputFormat("wav", "WAV (PCM 16 bits)", "wav")
FLAC = OutputFormat("flac", "FLAC (sans perte)", "flac")
FORMATS = (MP3, M4A, WAV, FLAC)

# Débit utilisé pour le M4A quand l'audio source n'est pas déjà en AAC.
M4A_REENCODE_KBPS = 256


@dataclass(frozen=True)
class ConversionOptions:
    format: OutputFormat
    mp3_quality: Mp3Quality = MP3_QUALITIES[0]
    # None : même dossier que le fichier source.
    output_dir: Path | None = None


@dataclass(frozen=True)
class MediaInfo:
    duration: float | None
    has_audio: bool
    audio_codec: str | None


@dataclass(frozen=True)
class ConversionResult:
    output: Path
    # True quand l'audio a été copié tel quel (M4A depuis une source AAC).
    stream_copied: bool


def bundled_dirs() -> list[Path]:
    """Dossiers où chercher un ffmpeg livré avec l'application, par ordre de priorité.

    Une fois empaquetée avec PyInstaller (sys.frozen), ffmpeg est livré à côté de
    l'exécutable ; le dossier interne de PyInstaller (sys._MEIPASS, « _internal » en mode
    onedir) est aussi accepté. En développement, il n'y a pas de ffmpeg livré.
    """
    if not getattr(sys, "frozen", False):
        return []
    dirs = [Path(sys.executable).resolve().parent]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(Path(meipass))
    return dirs


def find_ffmpeg() -> str | None:
    """Chemin de ffmpeg : celui livré avec l'application en priorité, sinon celui du PATH."""
    for directory in bundled_dirs():
        candidate = directory / FFMPEG_EXECUTABLE
        if candidate.is_file():
            return str(candidate)
    return shutil.which("ffmpeg")


def _require_ffmpeg() -> str:
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise ConversionError("ffmpeg est introuvable (ni à côté de l'application, ni dans le PATH).")
    return ffmpeg


# Sans fichier de sortie, « ffmpeg -i fichier » décrit l'entrée sur stderr puis s'arrête.
# La ligne « Duration: » de l'entrée est indentée de deux espaces ; les métadonnées le sont
# de quatre, ce qui évite de confondre un tag dont la valeur contiendrait « Duration: ».
_INPUT_RE = re.compile(r"^Input #0, ", re.MULTILINE)
_DURATION_RE = re.compile(r"^  Duration: (\d+):(\d{2}):(\d{2}(?:\.\d+)?)", re.MULTILINE)
_AUDIO_STREAM_RE = re.compile(r"^\s*Stream #0:(\d+)\S*: Audio: ([^\s,]+)", re.MULTILINE)


def parse_media_info(ffmpeg_output: str) -> MediaInfo:
    """Extrait la durée et le codec de la première piste audio de la sortie de « ffmpeg -i »."""
    duration = None
    if match := _DURATION_RE.search(ffmpeg_output):
        hours, minutes, seconds = match.groups()
        duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    audio_streams = sorted((int(index), codec) for index, codec in _AUDIO_STREAM_RE.findall(ffmpeg_output))
    return MediaInfo(
        duration=duration if duration else None,
        has_audio=bool(audio_streams),
        # -map 0:a:0 sélectionne la piste audio de plus petit index.
        audio_codec=audio_streams[0][1] if audio_streams else None,
    )


def probe(path: Path, ffmpeg: str | None = None) -> MediaInfo:
    """Lit la durée et la première piste audio d'un fichier, sans ffprobe."""
    cmd = [ffmpeg or _require_ffmpeg(), "-hide_banner", "-nostdin", "-i", str(path)]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=PROBE_TIMEOUT_S,
            creationflags=_POPEN_FLAGS,
        )
    except FileNotFoundError:
        raise ConversionError("ffmpeg est introuvable.") from None
    except subprocess.TimeoutExpired:
        raise ConversionError("ffmpeg ne répond pas pendant l'analyse du fichier (délai dépassé).") from None

    # Le code de sortie est toujours non nul (aucune sortie demandée) : seule la présence
    # de la description de l'entrée indique que le fichier a pu être ouvert.
    if not _INPUT_RE.search(proc.stderr):
        raise ConversionError(_describe_ffmpeg_error(proc.stderr.splitlines(), probing=True))
    return parse_media_info(proc.stderr)


def reserve_output_path(directory: Path, stem: str, extension: str) -> Path:
    """Crée un fichier vide au premier nom libre (« nom.ext », « nom (1).ext », …).

    Créer le fichier en mode exclusif, plutôt que de seulement tester son existence,
    garantit qu'aucun fichier existant n'est écrasé, même si un autre programme écrit
    dans le dossier au même moment.
    """
    for n in itertools.count():
        name = f"{stem}.{extension}" if n == 0 else f"{stem} ({n}).{extension}"
        candidate = directory / name
        try:
            with open(candidate, "x"):
                pass
        except FileExistsError:
            continue
        return candidate
    raise AssertionError("unreachable")


def build_command(
    ffmpeg: str, source: Path, output: Path, options: ConversionOptions, info: MediaInfo
) -> tuple[list[str], bool]:
    """Construit la ligne de commande ffmpeg. Renvoie (commande, copie_sans_réencodage)."""
    cmd = [
        ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error",
        # Écrase uniquement le fichier vide réservé par reserve_output_path().
        "-y",
        "-i", str(source),
        "-map", "0:a:0",
    ]
    stream_copied = False
    fmt = options.format
    if fmt == MP3:
        cmd += ["-c:a", "libmp3lame", *options.mp3_quality.args]
    elif fmt == M4A:
        if info.audio_codec == "aac":
            cmd += ["-c:a", "copy"]
            stream_copied = True
        else:
            cmd += ["-c:a", "aac", "-b:a", f"{M4A_REENCODE_KBPS}k"]
    elif fmt == WAV:
        # rf64=auto : bascule en RF64 seulement si le fichier dépasse 4 Go.
        cmd += ["-c:a", "pcm_s16le", "-rf64", "auto"]
    elif fmt == FLAC:
        cmd += ["-c:a", "flac"]
    else:
        raise ValueError(f"Format de sortie inconnu : {fmt}")
    cmd += ["-progress", "pipe:1", "-nostats", str(output)]
    return cmd, stream_copied


ProgressCallback = Callable[[float | None], None]


class Conversion:
    """Conversion d'un fichier. run() est bloquant ; cancel() peut être appelé depuis un autre thread."""

    def __init__(self, source: Path, options: ConversionOptions):
        self.source = Path(source)
        self.options = options
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._cancelled = False

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            if self._process is not None and self._process.poll() is None:
                self._process.kill()

    def run(self, on_progress: ProgressCallback | None = None) -> ConversionResult:
        """Convertit le fichier.

        on_progress reçoit une fraction entre 0 et 1, ou None si la durée est inconnue.
        Lève ConversionError en cas d'échec et ConversionCancelled en cas d'annulation ;
        dans les deux cas, aucun fichier partiel n'est laissé sur le disque.
        """
        report = on_progress or (lambda _fraction: None)
        if not self.source.is_file():
            raise ConversionError("Fichier introuvable.")

        ffmpeg = _require_ffmpeg()
        info = probe(self.source, ffmpeg)
        if not info.has_audio:
            raise ConversionError("Ce fichier ne contient aucune piste audio.")
        self._raise_if_cancelled()

        output_dir = self.options.output_dir or self.source.parent
        try:
            output = reserve_output_path(output_dir, self.source.stem, self.options.format.extension)
        except OSError as exc:
            raise ConversionError(
                f"Impossible de créer le fichier de sortie dans « {output_dir} » : {exc.strerror or exc}"
            ) from None

        cmd, stream_copied = build_command(ffmpeg, self.source, output, self.options, info)
        try:
            self._run_ffmpeg(cmd, info.duration, report)
        except BaseException:
            _remove_quietly(output)
            raise
        return ConversionResult(output=output, stream_copied=stream_copied)

    def _raise_if_cancelled(self) -> None:
        if self._cancelled:
            raise ConversionCancelled()

    def _run_ffmpeg(self, cmd: list[str], duration: float | None, report: ProgressCallback) -> None:
        with self._lock:
            self._raise_if_cancelled()
            try:
                process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=_POPEN_FLAGS,
                )
            except FileNotFoundError:
                raise ConversionError("ffmpeg est introuvable.") from None
            self._process = process

        # stderr est lu dans un thread à part pour qu'un flot d'erreurs ne bloque pas ffmpeg
        # pendant qu'on lit la progression sur stdout.
        stderr_tail: deque[str] = deque(maxlen=20)
        stderr_reader = threading.Thread(target=stderr_tail.extend, args=(process.stderr,), daemon=True)
        stderr_reader.start()

        report(0.0 if duration else None)
        try:
            for line in process.stdout:
                key, _, value = line.strip().partition("=")
                if key == "out_time_us" and duration:
                    try:
                        seconds = int(value) / 1_000_000
                    except ValueError:  # « N/A » en début de traitement
                        continue
                    report(min(max(seconds / duration, 0.0), 1.0))
                elif key == "progress" and value == "end":
                    report(1.0)
            process.wait()
        finally:
            if process.poll() is None:  # exception levée par le callback de progression
                process.kill()
                process.wait()
            stderr_reader.join()
            process.stdout.close()
            process.stderr.close()
            with self._lock:
                self._process = None

        self._raise_if_cancelled()
        if process.returncode != 0:
            raise ConversionError(_describe_ffmpeg_error(stderr_tail))


_KNOWN_ERRORS = (
    ("Invalid data found when processing input", "Format invalide ou fichier corrompu."),
    ("No space left on device", "Espace disque insuffisant."),
    ("Permission denied", "Accès refusé."),
    ("matches no streams", "Ce fichier ne contient aucune piste audio."),
)


def _describe_ffmpeg_error(stderr_lines: Iterable[str], probing: bool = False) -> str:
    lines = [line.strip() for line in stderr_lines if line.strip()]
    text = "\n".join(lines)
    for needle, message in _KNOWN_ERRORS:
        if needle in text:
            return message
    if probing:
        detail = f" ({lines[-1]})" if lines else ""
        return f"Format invalide ou fichier illisible{detail}."
    return f"ffmpeg a échoué : {lines[-1]}" if lines else "ffmpeg a échoué (erreur inconnue)."


def _remove_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
