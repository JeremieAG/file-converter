# file-converter

Application de bureau (Python + PySide6) qui convertit localement des fichiers vidéo ou audio en MP3, M4A, WAV ou FLAC avec ffmpeg. Rien n'est envoyé sur Internet.

Pour Windows 10/11 64 bits, un installateur embarque tout le nécessaire : l'utilisateur n'a besoin d'installer ni Python ni ffmpeg.

## Fonctionnalités

- Ajout de plusieurs fichiers par glisser-déposer, avec le bouton « Ajouter des fichiers… », ou en les passant en argument (« Ouvrir avec », dépôt sur le raccourci).
- Formats de sortie :
  - **MP3** : 320, 256, 192 ou 128 kbit/s en CBR, ou VBR V0 / V2.
  - **M4A** : si l'audio source est déjà en AAC, il est copié sans réencodage (`-c:a copy`, rapide et sans perte). Sinon, il est encodé en AAC 256 kbit/s.
  - **WAV** : PCM 16 bits.
  - **FLAC** : sans perte.
- Dossier de sortie au choix. Par défaut, c'est le dossier du fichier source.
- Aucun fichier existant n'est jamais écrasé : un suffixe est ajouté (`clip.mp3`, `clip (1).mp3`, …).
- Une barre de progression par fichier. La durée est lue sur la ligne `Duration:` de la sortie de ffmpeg (ffprobe n'est pas nécessaire), et l'avancement vient de `ffmpeg -progress pipe:1`.
- Les conversions tournent dans un `QThread` : l'interface ne gèle pas, et le bouton « Annuler » arrête ffmpeg puis supprime le fichier partiel.
- Les erreurs sont affichées sur la ligne du fichier concerné (fichier sans piste audio, format invalide ou corrompu, dossier inaccessible…), puis la file continue avec les fichiers suivants.
- Aucune fenêtre de console ne s'ouvre : tous les appels à ffmpeg utilisent `CREATE_NO_WINDOW`.

## Où l'application cherche ffmpeg

1. À côté de l'exécutable, quand l'application est empaquetée avec PyInstaller (`FileConverter.exe` et `ffmpeg.exe` dans le même dossier).
2. Dans le dossier interne de PyInstaller (`_internal`).
3. Dans le `PATH`.

Si ffmpeg reste introuvable, un message l'explique au démarrage : réinstaller, pour la version installée ; installer ffmpeg, pour un lancement depuis les sources.

## Lancer depuis les sources

Prérequis : Python 3.10 ou plus récent, et ffmpeg dans le `PATH` (Windows : `winget install Gyan.FFmpeg` puis ouvrir un nouveau terminal ; macOS : `brew install ffmpeg` ; Linux : `sudo apt install ffmpeg`).

**Windows (PowerShell)**, depuis le dossier du projet :

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m file_converter
```

Appeler directement `.venv\Scripts\python.exe` évite d'activer le venv, ce que PowerShell bloque souvent par défaut (« running scripts is disabled »).

**macOS / Linux**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m file_converter
```

## Construire la version Windows

Prérequis sur la machine de build : Python 3.10+ (lanceur `py`) et Inno Setup 6.3+ (`winget install JRSoftware.InnoSetup`).

```powershell
.\build.bat
```

Le script fait tout d'un coup :

1. Il crée `.venv` si besoin et installe `requirements.txt` et `requirements-build.txt` (PyInstaller).
2. Il télécharge le build statique de ffmpeg pour Windows (BtbN, variante LGPL), vérifie son SHA-256 et le garde en cache dans `build\`.
3. Il lance PyInstaller en mode onedir, ce qui produit `dist\FileConverter\` avec `FileConverter.exe`, `ffmpeg.exe` à côté et le dossier `licenses\`. Seuls QtCore, QtGui et QtWidgets sont embarqués, avec les plugins `qwindows`, les styles Windows et `qico`. Les autres modules Qt, les traductions et `opengl32sw.dll` sont exclus.
4. Il compile `packaging\installer.iss` avec Inno Setup, ce qui produit `dist\installer\FileConverter-Setup-<version>.exe`.

L'installateur :
- installe l'application dans `Program Files\File Converter` (droits administrateur requis) ;
- crée un raccourci dans le menu Démarrer, et un raccourci sur le bureau si l'option est cochée ;
- enregistre un désinstalleur dans « Paramètres > Applications » ;
- copie les licences de ffmpeg et de Qt/PySide6 dans `licenses\`.

La commande `FileConverter-Setup-<version>.exe /CURRENTUSER` installe l'application sans droits administrateur, dans `%LOCALAPPDATA%\Programs`.

La version affichée vient de `file_converter/__init__.py` (`__version__`) ; l'icône, de `file_converter/resources/app.ico` (régénérable avec `packaging/make_icon.py`).

### Mettre à jour ffmpeg

Les constantes `RELEASE`, `ARCHIVE` et `SHA256` de `packaging/fetch_ffmpeg.py` désignent le build utilisé. BtbN conserve durablement ses builds de fin de mois (`autobuild-AAAA-MM-JJ-…` sur https://github.com/BtbN/FFmpeg-Builds/releases), alors que les builds quotidiens disparaissent au bout de quelques semaines. Prenez l'archive `win64-lgpl` (pas `shared`) et son empreinte SHA-256.

### Signature du code

Les exécutables produits ne sont pas signés. Conséquences pour les utilisateurs :
- sous Windows 11, quand **Smart App Control** est activé, Windows peut bloquer l'installateur et l'application, sans option pour passer outre ;
- ailleurs, SmartScreen affiche « Windows a protégé votre ordinateur » pour un installateur téléchargé (« Informations complémentaires > Exécuter quand même »).

Pour distribuer largement, signez `FileConverter.exe`, `ffmpeg.exe` et l'installateur avec un certificat Authenticode : Azure Trusted Signing, ou un certificat OV/EV d'une autorité reconnue.

## Licences

ffmpeg est distribué sous LGPL v3 (build BtbN, sans composant GPL), et Qt/PySide6 sous LGPL v3. Leurs textes et l'origine des sources sont dans le dossier `licenses\` de l'application installée.

## Structure

```
file_converter/
  core.py         # Logique ffmpeg sans dépendance Qt : recherche de ffmpeg, analyse, commande, progression, annulation
  worker.py       # QThread qui enchaîne les conversions et émet des signaux vers l'interface
  ui.py           # Fenêtre principale (liste de fichiers, options, progression)
  app.py          # Point d'entrée : vérification de ffmpeg puis ouverture de la fenêtre
  resources/      # Icône de l'application
packaging/
  FileConverter.spec  # PyInstaller (onedir, exclusions Qt, icône, version, copie de ffmpeg et des licences)
  installer.iss       # Inno Setup
  fetch_ffmpeg.py     # Téléchargement épinglé de ffmpeg
  launcher.py         # Script d'entrée pour PyInstaller
  make_icon.py        # Génération de l'icône
build.bat         # Construction complète (PyInstaller + Inno Setup)
tests/
  media.py        # Génération des médias de test (testsrc + sine) et vérifications ffprobe
  test_core.py    # Conversions, analyse de la sortie ffmpeg, recherche de ffmpeg, erreurs, annulation
  test_ui.py      # Thread de conversion, fenêtre, message de démarrage
```

## Tests

Les tests génèrent leurs propres fichiers avec ffmpeg : une vidéo `testsrc` + `sine` de 10 s, une vidéo sans piste audio, un fichier corrompu et un long fichier audio pour tester l'annulation. Ils convertissent ensuite vers chaque format et vérifient les fichiers produits avec ffprobe : conteneur, codec, durée, décodage complet sans erreur, et paquets AAC identiques à la source quand le M4A est copié sans réencodage. L'application n'a pas besoin de ffprobe, mais les tests s'en servent pour ces vérifications.

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Les tests de l'interface tournent sans affichage (`QT_QPA_PLATFORM=offscreen`).
