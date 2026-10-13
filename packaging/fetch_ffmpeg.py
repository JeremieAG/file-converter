"""Télécharge le build statique de ffmpeg embarqué dans l'application.

Le build est épinglé (URL + SHA-256) pour que chaque compilation embarque exactement le
même binaire. BtbN conserve durablement ses builds de fin de mois ; pour changer de
version, choisir une autre release « autobuild-AAAA-MM-JJ » sur
https://github.com/BtbN/FFmpeg-Builds/releases et mettre à jour les trois constantes.

Variante LGPL (v3) : contient les encodeurs utilisés (libmp3lame, aac, flac, pcm) sans
composant GPL.

Usage : python packaging/fetch_ffmpeg.py <dossier_destination>
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

RELEASE = "autobuild-2026-09-30-13-08"
ARCHIVE = "ffmpeg-n9.0.2-17-g2a571b6068-win64-lgpl-9.0.zip"
SHA256 = "6b264b9e6019103f601d98c292bd332fd87acf1c5e941ddff4fb71760fe63432"
URL = f"https://github.com/BtbN/FFmpeg-Builds/releases/download/{RELEASE}/{ARCHIVE}"

UPSTREAM_SOURCE = "https://github.com/FFmpeg/FFmpeg/tree/2a571b606854520cf89804d8030c8b328e621689"
BUILD_SCRIPTS = "https://github.com/BtbN/FFmpeg-Builds"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(cache: Path) -> Path:
    archive = cache / ARCHIVE
    if archive.is_file() and sha256_of(archive) == SHA256:
        print(f"ffmpeg : archive déjà téléchargée ({archive.name})")
        return archive
    cache.mkdir(parents=True, exist_ok=True)
    partial = archive.with_suffix(".part")
    print(f"ffmpeg : téléchargement de {URL}")
    with urllib.request.urlopen(URL, timeout=60) as response, open(partial, "wb") as out:
        shutil.copyfileobj(response, out, 1 << 20)
    actual = sha256_of(partial)
    if actual != SHA256:
        partial.unlink()
        raise SystemExit(f"ERREUR : SHA-256 inattendu pour {ARCHIVE}\n  attendu : {SHA256}\n  obtenu  : {actual}")
    partial.replace(archive)
    return archive


def extract(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        names = {Path(n).relative_to(Path(n).parts[0]).as_posix(): n for n in zf.namelist() if len(Path(n).parts) > 1}
        for inner, target in (("bin/ffmpeg.exe", "ffmpeg.exe"), ("LICENSE.txt", "LICENSE.txt")):
            if inner not in names:
                raise SystemExit(f"ERREUR : {inner} absent de {archive.name}")
            with zf.open(names[inner]) as src, open(dest / target, "wb") as out:
                shutil.copyfileobj(src, out)
    (dest / "README.txt").write_text(
        "ffmpeg embarqué dans File Converter\n"
        "===================================\n\n"
        f"Binaire : ffmpeg.exe, build statique Windows 64 bits, variante LGPL\n"
        f"Archive : {ARCHIVE}\n"
        f"Source du binaire : {URL}\n"
        f"SHA-256 de l'archive : {SHA256}\n\n"
        "ffmpeg est distribué sous la licence GNU LGPL version 3 (voir LICENSE.txt).\n"
        f"Code source de ffmpeg correspondant : {UPSTREAM_SOURCE}\n"
        f"Scripts de compilation du build : {BUILD_SCRIPTS}\n"
        "Site officiel : https://ffmpeg.org/\n",
        encoding="utf-8",
    )
    (dest / ".archive").write_text(ARCHIVE, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage : python packaging/fetch_ffmpeg.py <dossier_destination>")
    dest = Path(sys.argv[1]).resolve()
    marker = dest / ".archive"
    if (dest / "ffmpeg.exe").is_file() and marker.is_file() and marker.read_text(encoding="utf-8") == ARCHIVE:
        print(f"ffmpeg : déjà présent dans {dest}")
        return
    archive = download(dest.parent / "cache")
    extract(archive, dest)
    print(f"ffmpeg : extrait dans {dest}")


if __name__ == "__main__":
    main()
