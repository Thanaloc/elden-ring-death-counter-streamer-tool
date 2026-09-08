"""
Detection de l'ecran de mort par correlation masquee.

Le texte de mort est souvent moins lumineux que le decor visible derriere
le voile sombre : le correler tel quel revient a comparer des paysages, pas
des lettres. On extrait donc une signature a partir de plusieurs morts. Ce
qui ressort localement dans TOUTES les captures est forcement le texte,
puisque le decor, lui, change a chaque fois.

La correlation ne porte ensuite que sur ces pixels-la. C'est independant de
la langue du jeu, de la resolution et de l'endroit ou l'on meurt.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import mss
import numpy as np

# Bande de l'ecran ou apparait le texte, en fractions (x1, y1, x2, y2).
SEARCH_BAND = (0.15, 0.30, 0.85, 0.66)

# Largeur de travail : signature et analyse partagent la meme echelle.
WORK_WIDTH = 960

HIGHPASS_SIGMA = 6.0     # rayon du flou soustrait pour isoler les traits fins
STABLE_LEVEL = 3.0       # contraste local minimal pour qu'un pixel compte
MIN_CAPTURES = 3         # en dessous, le masque garde trop de decor


# --------------------------------------------------------------- fichiers

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


# --------------------------------------------------------------- capture

def grab(sct, monitor) -> np.ndarray:
    """Capture le moniteur, downscale, niveaux de gris."""
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


def highpass(image, sigma: float = HIGHPASS_SIGMA) -> np.ndarray:
    """Retire les variations lentes et garde les traits fins du texte."""
    f = np.asarray(image, np.float32)
    return np.ascontiguousarray(f - cv2.GaussianBlur(f, (0, 0), sigma))


def wait_for_frames(monitor_index: int, count: int = MIN_CAPTURES) -> list:
    """
    Attend `count` appuis sur F8, un par mort, et retourne les bandes.

    Les morts doivent se produire a des endroits differents : c'est la
    difference entre les decors qui permet d'isoler le texte.
    """
    import keyboard  # seulement necessaire au setup

    frames = []
    with mss.mss() as sct:
        monitor = sct.monitors[monitor_index]
        while len(frames) < count:
            print(f"Mort {len(frames) + 1} sur {count} : appuie sur F8 pendant "
                  "que le texte est affiche.")
            while True:
                if keyboard.is_pressed("esc"):
                    raise KeyboardInterrupt
                if keyboard.is_pressed("f8"):
                    frames.append(crop_band(grab(sct, monitor)))
                    print("  capture faite.\n")
                    break
                time.sleep(0.05)
            while keyboard.is_pressed("f8"):
                time.sleep(0.05)   # evite de compter un appui long deux fois
    return frames


# --------------------------------------------------------------- signature

class SignatureError(RuntimeError):
    pass


def extract_signature(frames: list):
    """
    Isole le texte a partir de plusieurs captures de l'ecran de mort.

    Retourne (template, mask, box) : template et mask sont recadres sur le
    texte, box donne sa position dans la bande pour l'apercu.
    """
    if len(frames) < MIN_CAPTURES:
        raise SignatureError(f"Il faut au moins {MIN_CAPTURES} captures.")
    if len({f.shape for f in frames}) != 1:
        raise SignatureError("Les captures n'ont pas toutes la meme taille.")

    highs = [highpass(f) for f in frames]

    stable = np.ones(highs[0].shape, bool)
    for h in highs:
        stable &= (h > STABLE_LEVEL)
    mask = stable.astype(np.uint8)

    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (15, 5)))

    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    if count < 2:
        raise SignatureError(
            "Aucun texte commun aux captures.\n"
            "Verifie que tu analyses le bon ecran (--monitor) et que le "
            "texte etait bien affiche a chaque appui sur F8."
        )

    main = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    main_y = centroids[main][1]
    main_h = stats[main, cv2.CC_STAT_HEIGHT]

    # Les lettres arrivent en blocs separes : on garde celles de la meme
    # ligne de texte, de hauteur comparable.
    keep = [i for i in range(1, count)
            if abs(centroids[i][1] - main_y) < main_h * 1.1
            and stats[i, cv2.CC_STAT_AREA] > 25
            and stats[i, cv2.CC_STAT_HEIGHT] < main_h * 2.2]

    text = np.isin(labels, keep).astype(np.float32)
    ys, xs = np.nonzero(text)
    if xs.size < 200:
        raise SignatureError("Le texte trouve est trop petit pour etre fiable.")

    pad = 6
    x0, y0 = max(0, int(xs.min()) - pad), max(0, int(ys.min()) - pad)
    x1 = min(text.shape[1], int(xs.max()) + pad + 1)
    y1 = min(text.shape[0], int(ys.max()) + pad + 1)

    template = np.ascontiguousarray(np.mean(highs, axis=0)[y0:y1, x0:x1])
    return template, np.ascontiguousarray(text[y0:y1, x0:x1]), (x0, y0, x1, y1)


def save_signature(path: Path, template: np.ndarray, mask: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as handle:
        np.savez_compressed(handle, template=template, mask=mask)


def signature_preview(frame: np.ndarray, mask: np.ndarray, box) -> np.ndarray:
    """Bande capturee avec les pixels retenus surlignes, pour verification."""
    x0, y0, x1, y1 = box
    preview = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    zone = preview[y0:y1, x0:x1]
    zone[mask > 0] = (90, 220, 255)
    cv2.rectangle(preview, (x0, y0), (x1 - 1, y1 - 1), (90, 220, 255), 1)
    return preview


# --------------------------------------------------------------- detection

@dataclass
class DetectorConfig:
    threshold: float = 0.60        # marge large : morts ~0.93, reste ~0.15
    confirm_frames: int = 2
    rearm_seconds: float = 8.0
    luma_gate: float = 150.0       # pre-filtre de performance, permissif


class DeathDetector:
    def __init__(self, signature_path: Path, config: DetectorConfig | None = None):
        if not signature_path.is_file():
            raise FileNotFoundError(
                f"Signature absente : {signature_path}\n"
                "Lance d'abord la commande de setup."
            )
        with open(signature_path, "rb") as handle:
            data = np.load(handle)
            self.template = np.ascontiguousarray(data["template"], np.float32)
            self.mask = np.ascontiguousarray(data["mask"], np.float32)

        self.cfg = config or DetectorConfig()
        self._streak = 0
        self._armed = True
        self._last_fire = 0.0
        self.last_score = 0.0

    def score(self, gray_frame: np.ndarray) -> float:
        if gray_frame.mean() > self.cfg.luma_gate:
            return 0.0

        band = highpass(crop_band(gray_frame))
        th, tw = self.template.shape[:2]
        if band.shape[0] < th or band.shape[1] < tw:
            return 0.0

        result = cv2.matchTemplate(band, self.template,
                                   cv2.TM_CCORR_NORMED, mask=self.mask)
        result = result[np.isfinite(result)]
        return float(result.max()) if result.size else 0.0

    def update(self, gray_frame: np.ndarray) -> bool:
        """A appeler a chaque frame. Retourne True une seule fois par mort."""
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
