# file-converter

Application de bureau (Python + PySide6) qui convertit localement des fichiers vidéo ou audio en MP3, M4A, WAV ou FLAC avec ffmpeg. Rien n'est envoyé sur Internet.

## Fonctionnalités

- Ajout de plusieurs fichiers par glisser-déposer ou avec le bouton « Ajouter des fichiers… ».
- Formats de sortie :
  - **MP3** : 320, 256, 192 ou 128 kbit/s en CBR, ou VBR V0 / V2.
  - **M4A** : si l'audio source est déjà en AAC, il est copié sans réencodage (`-c:a copy`, rapide et sans perte). Sinon, il est encodé en AAC 256 kbit/s.
  - **WAV** : PCM 16 bits.
  - **FLAC** : sans perte.
- Dossier de sortie au choix. Par défaut, c'est le dossier du fichier source.
- Aucun fichier existant n'est jamais écrasé : un suffixe est ajouté (`clip.mp3`, `clip (1).mp3`, …).
- Une barre de progression par fichier : la durée vient de ffprobe, l'avancement de `ffmpeg -progress pipe:1`.
- Les conversions tournent dans un `QThread` : l'interface ne gèle pas, et le bouton « Annuler » arrête ffmpeg puis supprime le fichier partiel.
- Les erreurs sont affichées sur la ligne du fichier concerné (fichier sans piste audio, format invalide ou corrompu, dossier inaccessible…), puis la file continue avec les fichiers suivants.

## Prérequis

- Python 3.10 ou plus récent.
- **ffmpeg** et **ffprobe** dans le `PATH`. Au démarrage, l'application vérifie leur présence et explique comment les installer s'ils manquent :
  - Windows : `winget install Gyan.FFmpeg` (ouvrez ensuite un nouveau terminal pour que le `PATH` soit à jour) ;
  - macOS : `brew install ffmpeg` ;
  - Linux : `sudo apt install ffmpeg` (ou l'équivalent de votre distribution).

## Installation et lancement

Depuis le dossier du projet :

**Windows (PowerShell)**

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

## Structure

```
file_converter/
  core.py      # Logique ffmpeg/ffprobe, sans dépendance Qt : analyse, commande, progression, annulation
  worker.py    # QThread qui enchaîne les conversions et émet des signaux vers l'interface
  ui.py        # Fenêtre principale (liste de fichiers, options, progression)
  app.py       # Point d'entrée : vérification de ffmpeg/ffprobe puis ouverture de la fenêtre
  __main__.py  # Permet `python -m file_converter`
tests/
  media.py     # Génération des médias de test (testsrc + sine) et vérifications ffprobe
  test_core.py # Conversion dans chaque format, noms de fichiers, erreurs, annulation
  test_ui.py   # Thread de conversion et fenêtre (glisser-déposer, conversion, annulation)
```

## Tests

Les tests génèrent leurs propres fichiers avec ffmpeg : une vidéo `testsrc` + `sine` de 10 s, une vidéo sans piste audio, un fichier corrompu et un long fichier audio pour tester l'annulation. Ils convertissent ensuite vers chaque format et vérifient les fichiers produits avec ffprobe : conteneur, codec, durée, décodage complet sans erreur, et paquets AAC identiques à la source quand le M4A est copié sans réencodage.

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Les tests de l'interface tournent sans affichage (`QT_QPA_PLATFORM=offscreen`).
