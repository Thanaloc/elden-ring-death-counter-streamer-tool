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


def find_text_box(band: np.ndarray):
    """
    Isole le bloc de texte dans la bande capturee.

    Sur l'ecran de mort, le decor est recouvert d'un voile tres sombre et
    le texte ressort nettement. On seuille par rapport a la statistique de
    la bande, on recolle les lettres entre elles, et on garde le plus large
    bloc horizontal : c'est le texte.
    """
    blur = cv2.GaussianBlur(band, (3, 3), 0)
    threshold = blur.mean() + 2.0 * blur.std()
    mask = (blur > threshold).astype(np.uint8)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (31, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = [cv2.boundingRect(c) for c in contours]
    boxes = [b for b in boxes if b[2] > band.shape[1] * 0.12 and b[3] > 6]
    if not boxes:
        return None

    x, y, w, h = max(boxes, key=lambda b: b[2])
    pad_x, pad_y = int(w * 0.06), int(h * 0.35)
    x0 = max(0, x - pad_x)
    y0 = max(0, y - pad_y)
    x1 = min(band.shape[1], x + w + pad_x)
    y1 = min(band.shape[0], y + h + pad_y)
    return x0, y0, x1, y1


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

                box = find_text_box(band)
                if box is None:
                    raise ValueError(
                        "Aucun bloc de texte trouve dans la zone analysee.\n"
                        "Verifie que tu analyses bien l'ecran du jeu "
                        "(option --monitor) et que le texte etait affiche."
                    )
                x0, y0, x1, y1 = box
                template = band[y0:y1, x0:x1]

                # Apercu annote : c'est la seule facon de verifier de visu
                # que le setup a cadre le bon element.
                preview = cv2.cvtColor(band, cv2.COLOR_GRAY2BGR)
                cv2.rectangle(preview, (x0, y0), (x1, y1), (80, 220, 80), 2)
                preview_path = out_path.with_name("apercu-setup.png")
                imwrite_png(preview_path, preview)

                if not imwrite_png(out_path, template):
                    raise OSError(f"Impossible d'ecrire le template dans {out_path}")

                # On relit ce qu'on vient d'ecrire : un fichier illisible
                # ici vaut mieux qu'une erreur au milieu d'un stream.
                if imread_gray(out_path) is None:
                    raise OSError(f"Template ecrit mais illisible : {out_path}")

                print(f"Template enregistre : {out_path}")
                print(f"  {template.shape[1]}x{template.shape[0]} pixels, "
                      f"{out_path.stat().st_size} octets")
                print(f"\nOuvre {preview_path} pour verifier.")
                print("Le rectangle vert doit entourer le texte, et rien d'autre.")
                return out_path
            time.sleep(0.05)


@dataclass
class DetectorConfig:
    threshold: float = 0.72        # score NCC minimal
    confirm_frames: int = 3        # frames consecutives requises
    rearm_seconds: float = 8.0     # anti double-comptage
    luma_gate: float = 150.0       # pre-filtre perf, volontairement permissif


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
