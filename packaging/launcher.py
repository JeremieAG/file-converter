"""Script d'entrée pour PyInstaller (le paquet utilise des imports relatifs)."""

import sys

from file_converter.app import main

sys.exit(main())
