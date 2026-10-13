# -*- mode: python -*-
"""Spec PyInstaller : FileConverter en mode onedir, avec ffmpeg.exe à côté de l'exécutable.

Lancé par build.bat ; utilisable seul avec :
    python -m PyInstaller --noconfirm --clean packaging/FileConverter.spec
"""

import os
import shutil
import sys
from pathlib import Path, PurePosixPath

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))
from file_converter import __version__  # noqa: E402

APP_NAME = "FileConverter"
PUBLISHER = "JeremieAG"
ICON = ROOT / "file_converter" / "resources" / "app.ico"
FFMPEG_DIR = Path(os.environ.get("FFMPEG_DIR", ROOT / "build" / "ffmpeg"))

if not (FFMPEG_DIR / "ffmpeg.exe").is_file():
    raise SystemExit(f"ffmpeg.exe introuvable dans {FFMPEG_DIR} : lancez d'abord packaging/fetch_ffmpeg.py")

# ---------------------------------------------------------------- exclusions Qt

# Modules Qt que l'application n'importe pas (elle n'utilise que QtCore, QtGui, QtWidgets).
QT_MODULE_EXCLUDES = [
    f"PySide6.{name}"
    for name in (
        "QtConcurrent", "QtDBus", "QtNetwork", "QtOpenGL", "QtOpenGLWidgets", "QtPdf",
        "QtPrintSupport", "QtQml", "QtQuick", "QtQuickWidgets", "QtSql", "QtSvg",
        "QtSvgWidgets", "QtTest", "QtXml",
    )
]

# Plugins Qt conservés, par catégorie (None = tous). Les autres catégories (iconengines,
# generic, tls, networkinformation…) dépendent de modules exclus ou sont inutiles ici.
KEPT_QT_PLUGINS = {
    "platforms": {"qwindows.dll"},
    "styles": None,  # style Windows 11 / Windows natif
    "imageformats": {"qico.dll"},  # icône de la fenêtre
}

# Bibliothèques livrées avec PySide6 mais inutiles pour une application QtWidgets.
DROPPED_DLLS = {
    "opengl32sw.dll",  # OpenGL logiciel (~20 Mo)
    "d3dcompiler_47.dll",  # déjà présent dans Windows 10/11
}
DROPPED_DLL_PREFIXES = ("qt6network", "qt6pdf", "qt6qml", "qt6quick", "qt6svg", "qt6opengl", "qt6virtualkeyboard")


def is_needed(entry) -> bool:
    parts = PurePosixPath(entry[0].replace("\\", "/").lower()).parts
    if not parts or parts[0] != "pyside6":
        return True
    if parts[1:2] == ("translations",):
        return False  # textes de l'interface déjà en français dans le code
    if parts[1:2] == ("plugins",) and len(parts) >= 4:
        if parts[2] not in KEPT_QT_PLUGINS:
            return False
        kept = KEPT_QT_PLUGINS[parts[2]]
        return kept is None or parts[-1] in kept
    name = parts[-1]
    return name not in DROPPED_DLLS and not name.startswith(DROPPED_DLL_PREFIXES)


# ---------------------------------------------------------------- analyse et build

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    datas=[(str(ICON), "file_converter/resources")],
    excludes=["tkinter", "unittest", "pydoc", *QT_MODULE_EXCLUDES],
    noarchive=False,
)

removed = [e[0] for e in a.binaries + a.datas if not is_needed(e)]
a.binaries = [e for e in a.binaries if is_needed(e)]
a.datas = [e for e in a.datas if is_needed(e)]
print(f"[FileConverter] {len(removed)} fichiers Qt inutiles retirés")

pyz = PYZ(a.pure)

version_tuple = tuple(int(x) for x in __version__.split(".")) + (0,) * (4 - len(__version__.split(".")))
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=version_tuple, prodvers=version_tuple),
    kids=[
        StringFileInfo([
            StringTable("040C04B0", [
                StringStruct("CompanyName", PUBLISHER),
                StringStruct("FileDescription", "File Converter"),
                StringStruct("FileVersion", __version__),
                StringStruct("InternalName", APP_NAME),
                StringStruct("OriginalFilename", f"{APP_NAME}.exe"),
                StringStruct("ProductName", "File Converter"),
                StringStruct("ProductVersion", __version__),
            ])
        ]),
        VarFileInfo([VarStruct("Translation", [0x040C, 1200])]),
    ],
)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    icon=str(ICON),
    version=version_info,
    console=False,
    upx=False,  # UPX provoque des faux positifs d'antivirus
)

coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME, upx=False)

# ---------------------------------------------------------------- ffmpeg et licences

dist_dir = Path(DISTPATH) / APP_NAME
shutil.copy2(FFMPEG_DIR / "ffmpeg.exe", dist_dir / "ffmpeg.exe")

ffmpeg_licenses = dist_dir / "licenses" / "ffmpeg"
ffmpeg_licenses.mkdir(parents=True, exist_ok=True)
for name in ("LICENSE.txt", "README.txt"):
    shutil.copy2(FFMPEG_DIR / name, ffmpeg_licenses / name)

import PySide6  # noqa: E402
from PySide6 import QtCore  # noqa: E402

qt_licenses = dist_dir / "licenses" / "Qt-PySide6"
qt_licenses.mkdir(parents=True, exist_ok=True)
(qt_licenses / "README.txt").write_text(
    "Qt et PySide6 embarqués dans File Converter\n"
    "===========================================\n\n"
    f"PySide6 {PySide6.__version__} (Qt for Python) et les bibliothèques Qt {QtCore.qVersion()}\n"
    "sont utilisés sous la licence GNU LGPL version 3, dont le texte est identique à\n"
    "licenses/ffmpeg/LICENSE.txt.\n\n"
    "Code source : https://download.qt.io/official_releases/QtForPython/\n"
    "              https://code.qt.io/cgit/qt/qtbase.git/\n",
    encoding="utf-8",
)
print(f"[FileConverter] ffmpeg.exe et licences copiés dans {dist_dir}")
