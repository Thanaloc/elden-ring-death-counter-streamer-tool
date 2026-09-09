"""Screen capture and cropping of the analysed band."""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import mss
import numpy as np

# Where the death text appears, as fractions of the screen (x1, y1, x2, y2).
SEARCH_BAND = (0.15, 0.30, 0.85, 0.66)

# Working width: setup and detection must share the same scale.
WORK_WIDTH = 960


def imread_gray(path: Path):
    """Read an image, tolerating non-ASCII paths.

    cv2.imread goes through the Windows ANSI API and fails silently as soon
    as the path contains an accent.
    """
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)


def imwrite_png(path: Path, image: np.ndarray) -> bool:
    """Write a PNG, tolerating non-ASCII paths. Returns real success."""
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
    """Wait for F8 and return the captured band."""
    import keyboard

    print("Die once, then press F8 while the death text is on screen.")
    print("Esc to cancel.\n")

    with mss.mss() as sct:
        monitor = sct.monitors[monitor_index]
        while True:
            if keyboard.is_pressed("esc"):
                raise KeyboardInterrupt
            if keyboard.is_pressed("f8"):
                return crop_band(grab(sct, monitor))
            time.sleep(0.05)
