"""Génération de fichiers de test et vérification avec ffprobe."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

# L'application n'a besoin que de ffmpeg ; les tests utilisent aussi ffprobe pour vérifier
# les fichiers produits.
TOOLS_MISSING = shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def make_video(path: Path, seconds: float = 10, audio_codec: str | None = "aac") -> Path:
    """Vidéo testsrc avec, si audio_codec n'est pas None, une sinusoïde à 1 kHz."""
    args = ["-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=320x240:rate=25"]
    if audio_codec:
        args += ["-f", "lavfi", "-i", f"sine=frequency=1000:duration={seconds}", "-c:a", audio_codec]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", str(path)]
    ffmpeg(*args)
    return path


def make_audio(path: Path, seconds: float) -> Path:
    ffmpeg("-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=44100:duration={seconds}", "-ac", "2", str(path))
    return path


def ffprobe(path: Path) -> dict:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(proc.stdout)


def decode_errors(path: Path) -> str:
    """Décode entièrement le fichier et renvoie les erreurs rencontrées (vide si aucune)."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-v", "error", "-i", str(path), "-f", "null", "-"],
        capture_output=True, text=True,
    )
    return proc.stderr.strip() or ("" if proc.returncode == 0 else f"code de sortie {proc.returncode}")


def audio_packets_md5(path: Path) -> str:
    """Empreinte des paquets audio bruts, pour vérifier une copie sans réencodage."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-v", "error", "-i", str(path), "-map", "0:a:0", "-c", "copy", "-f", "md5", "-"],
        capture_output=True, text=True, check=True,
    )
    return proc.stdout.strip()
