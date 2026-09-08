"""Cible PyInstaller : un seul fichier a geler."""
from eldencounter.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
