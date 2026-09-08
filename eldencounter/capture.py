"""Capture d'ecran et decoupe de la bande analysee."""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import mss
import numpy as np

# Bande de l'ecran ou apparait le texte, en fractions (x1, y1, x2, y2).
SEARCH_BAND = (0.15, 0.30, 0.85, 0.66)

# Largeur de travail : setup et detection partagent la meme echelle.
WORK_WIDTH = 960


def imread_gray(path: Path):
    """Lecture tolerante aux chemins non-ASCII (cv2.imread passe par l'API ANSI)."""
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)


def imwrite_png(path: Path, image: np.ndarray) -> bool:
    """Ecriture tolerante aux chemins non-ASCII. Retourne le succes reel."""
    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        return False
    try:
        buffer.tofile(str(path))
    except OSError:
        return False
    return path.is_file() and path.stat().st_size > 0


def grab(sct, monitor) -> np.ndarray:
    frame = np.asarray(sct.grab(monitor))[:, :, :3]
    scale = WORK_WIDTH / frame.shape[1]
    if scale < 1.0:
        frame = cv2.resize(frame, None, fx=scale, fy=scale,
                           interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def crop_band(gray: np.ndarray) -> np.ndarray:
    h, w = gray.shape[:2]
    x1, y1, x2, y2 = SEARCH_BAND
    return gray[int(h * y1):int(h * y2), int(w * x1):int(w * x2)]


def wait_for_death(monitor_index: int) -> np.ndarray:
    """Attend un appui sur F8 et retourne la bande capturee."""
    import keyboard

    print("Meurs une fois, puis appuie sur F8 pendant que le texte est")
    print("affiche a l'ecran. Echap pour annuler.\n")

    with mss.mss() as sct:
        monitor = sct.monitors[monitor_index]
        while True:
            if keyboard.is_pressed("esc"):
                raise KeyboardInterrupt
            if keyboard.is_pressed("f8"):
                return crop_band(grab(sct, monitor))
            time.sleep(0.05)
