"""
Detection de l'ecran de mort par correlation croisee normalisee.

Contrairement a une heuristique colorimetrique, on cherche la *forme* du
texte. Le score est quasi binaire et insensible a la luminosite, donc les
zones rouges du jeu (Caelid, sang, feu) ne declenchent rien.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import mss
import numpy as np

# Bande de l'ecran ou apparait le texte, en fractions (x1, y1, x2, y2).
# Volontairement plus large que le texte pour tolerer les ratios exotiques.
SEARCH_BAND = (0.15, 0.30, 0.85, 0.66)

# Largeur de travail : on downscale avant analyse, le template est capture
# a la meme echelle donc les deux restent coherents.
WORK_WIDTH = 960


def imread_gray(path: Path):
    """
    Lecture tolerante aux chemins non-ASCII.

    cv2.imread passe par l'API ANSI de Windows et echoue silencieusement
    des qu'un accent apparait dans le chemin, ce qui arrive des que le nom
    d'utilisateur en contient un.
    """
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
    """Capture le moniteur et le ramene a WORK_WIDTH en niveaux de gris."""
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


def capture_template(monitor_index: int, out_path: Path) -> Path:
    """
    Mode setup : l'utilisateur meurt une fois et valide au clavier.
    Le template obtenu est specifique a sa resolution ET a la langue du jeu.
    """
    import keyboard  # import local : seulement necessaire au setup

    print("Meurs une fois dans le jeu, puis appuie sur F8 pendant que")
    print("le texte est affiche a l'ecran. Echap pour annuler.\n")

    with mss.mss() as sct:
        monitor = sct.monitors[monitor_index]
        while True:
            if keyboard.is_pressed("esc"):
                raise KeyboardInterrupt
            if keyboard.is_pressed("f8"):
                band = crop_band(grab(sct, monitor))
                out_path.parent.mkdir(parents=True, exist_ok=True)

                if not imwrite_png(out_path, band):
                    raise OSError(f"Impossible d'ecrire le template dans {out_path}")

                # On relit ce qu'on vient d'ecrire : un fichier illisible
                # ici vaut mieux qu'une erreur au milieu d'un stream.
                if imread_gray(out_path) is None:
                    raise OSError(f"Template ecrit mais illisible : {out_path}")

                print(f"Template enregistre : {out_path} "
                      f"({band.shape[1]}x{band.shape[0]} pixels, "
                      f"{out_path.stat().st_size} octets)")
                return out_path
            time.sleep(0.05)


@dataclass
class DetectorConfig:
    threshold: float = 0.72        # score NCC minimal
    confirm_frames: int = 3        # frames consecutives requises
    rearm_seconds: float = 8.0     # anti double-comptage
    luma_gate: float = 110.0       # pre-filtre perf, volontairement permissif


class DeathDetector:
    def __init__(self, template_path: Path, config: DetectorConfig | None = None):
        template = imread_gray(template_path)
        if template is None:
            raise FileNotFoundError(
                f"Template illisible ou absent : {template_path}\n"
                "Relance la commande de setup."
            )
        self.template = template
        self.cfg = config or DetectorConfig()
        self._streak = 0
        self._armed = True
        self._last_fire = 0.0
        self.last_score = 0.0

    def score(self, gray_frame: np.ndarray) -> float:
        """Score de correlation, ou 0.0 si le pre-filtre rejette la frame."""
        if gray_frame.mean() > self.cfg.luma_gate:
            return 0.0

        band = crop_band(gray_frame)
        th, tw = self.template.shape[:2]
        if band.shape[0] < th or band.shape[1] < tw:
            # resolution differente de celle du setup : on redimensionne
            scale = min(band.shape[0] / th, band.shape[1] / tw) * 0.98
            tpl = cv2.resize(self.template, None, fx=scale, fy=scale,
                             interpolation=cv2.INTER_AREA)
        else:
            tpl = self.template

        res = cv2.matchTemplate(band, tpl, cv2.TM_CCOEFF_NORMED)
        return float(res.max())


    def update(self, gray_frame: np.ndarray) -> bool:
        """
        A appeler a chaque frame. Retourne True une seule fois par mort.
        """
        now = time.time()
        self.last_score = self.score(gray_frame)
        hit = self.last_score >= self.cfg.threshold

        if hit:
            self._streak += 1
        else:
            self._streak = 0
            if not self._armed and (now - self._last_fire) > self.cfg.rearm_seconds:
                self._armed = True

        if self._armed and self._streak >= self.cfg.confirm_frames:
            self._armed = False
            self._last_fire = now
            self._streak = 0
            return True
        return False
