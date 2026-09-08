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

# Ces valeurs ont ete reglees sur de vraies captures d'Elden Ring, pas
# estimees : voir la marge mesuree dans le README.
HIGHPASS_SIGMA = 6.0     # rayon du flou soustrait pour isoler les traits fins
STABLE_LEVEL = 4.0       # contraste local minimal pour qu'un pixel compte
STABLE_RATIO = 0.55      # variation toleree d'une capture a l'autre
GAMEPLAY_LIMIT = 0.5     # au-dela, le pixel est aussi present hors mort
MIN_CAPTURES = 4         # une capture ratee peut etre ecartee, il en reste 3
MIN_KEPT = 3
OUTLIER_MARGIN = 0.15    # ecart au score median qui fait ecarter une capture


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


def wait_for_frames(monitor_index: int, count: int = MIN_CAPTURES,
                    ambient_target: int = 12, ambient_interval: float = 3.0):
    """
    Attend `count` appuis sur F8, un par mort, et retourne (morts, jeu).

    Les frames de jeu sont prelevees toutes seules pendant l'attente : elles
    servent a eliminer l'interface, qui est elle aussi identique d'une mort
    a l'autre mais reste affichee en jeu normal.
    """
    import keyboard  # seulement necessaire au setup

    deaths, ambient = [], []
    last_sample = 0.0

    with mss.mss() as sct:
        monitor = sct.monitors[monitor_index]
        print(f"Mort 1 sur {count} : appuie sur F8 quand le texte est affiche.")
        while len(deaths) < count:
            now = time.time()

            if keyboard.is_pressed("esc"):
                raise KeyboardInterrupt

            if keyboard.is_pressed("f8"):
                deaths.append(crop_band(grab(sct, monitor)))
                print(f"  capture {len(deaths)}/{count} faite.")
                while keyboard.is_pressed("f8"):
                    time.sleep(0.05)
                if len(deaths) < count:
                    print(f"Mort {len(deaths) + 1} sur {count} : "
                          "va mourir ailleurs, puis F8.")
                last_sample = time.time() + 6.0   # laisse l'ecran de mort passer
                continue

            if (now - last_sample > ambient_interval
                    and len(ambient) < ambient_target):
                ambient.append(crop_band(grab(sct, monitor)))
                last_sample = now

            time.sleep(0.1)

    return deaths, ambient


# --------------------------------------------------------------- signature

class SignatureError(RuntimeError):
    pass


def _candidate_mask(deaths: list, gameplay: list):
    """Pixels marques, constants d'une mort a l'autre, et absents en jeu."""
    stack = np.stack([highpass(f) for f in deaths])
    mean, spread = stack.mean(axis=0), stack.std(axis=0)

    keep = (np.abs(mean) > STABLE_LEVEL) & (spread < np.abs(mean) * STABLE_RATIO)

    if gameplay:
        games = np.stack([highpass(f) for f in gameplay])
        also_in_game = ((np.abs(games) > STABLE_LEVEL)
                        & (np.sign(games) == np.sign(mean))).mean(axis=0)
        keep &= (also_in_game < GAMEPLAY_LIMIT)

    mask = cv2.morphologyEx(keep.astype(np.uint8), cv2.MORPH_OPEN,
                            np.ones((2, 2), np.uint8))
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (15, 5)))
    return mask, mean


def _extract_once(deaths: list, gameplay: list):
    mask, mean = _candidate_mask(deaths, gameplay)
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    height, width = mask.shape

    # L'interface du jeu touche les bords ou traverse toute la largeur.
    blocks = [i for i in range(1, count)
              if stats[i, cv2.CC_STAT_AREA] > 30
              and stats[i, cv2.CC_STAT_WIDTH] < width * 0.8
              and stats[i, cv2.CC_STAT_HEIGHT] < height * 0.4]
    if not blocks:
        return None

    main = max(blocks, key=lambda i: stats[i, cv2.CC_STAT_AREA])
    main_y = centroids[main][1]
    main_h = stats[main, cv2.CC_STAT_HEIGHT]
    kept = [i for i in blocks
            if abs(centroids[i][1] - main_y) < main_h * 1.2
            and stats[i, cv2.CC_STAT_HEIGHT] < main_h * 2.2]

    text = np.isin(labels, kept).astype(np.float32)
    ys, xs = np.nonzero(text)
    if xs.size < 150:
        return None

    pad = 6
    x0, y0 = max(0, int(xs.min()) - pad), max(0, int(ys.min()) - pad)
    x1 = min(width, int(xs.max()) + pad + 1)
    y1 = min(height, int(ys.max()) + pad + 1)

    return (np.ascontiguousarray(mean[y0:y1, x0:x1]),
            np.ascontiguousarray(text[y0:y1, x0:x1]), (x0, y0, x1, y1))


def raw_score(frame: np.ndarray, template: np.ndarray, mask: np.ndarray) -> float:
    band = highpass(frame)
    if band.shape[0] < template.shape[0] or band.shape[1] < template.shape[1]:
        return 0.0
    result = cv2.matchTemplate(band, template, cv2.TM_CCORR_NORMED, mask=mask)
    result = result[np.isfinite(result)]
    return float(result.max()) if result.size else 0.0


def extract_signature(deaths: list, gameplay: list | None = None):
    """
    Isole le texte a partir de plusieurs morts.

    Une capture prise pendant le fondu ou masquee par un effet degrade la
    signature entiere : on ecarte celles qui collent mal a ce que les autres
    decrivent, tant qu'il en reste assez.

    Retourne (template, mask, box, scores, ecartees).
    """
    if len(deaths) < MIN_KEPT:
        raise SignatureError(f"Il faut au moins {MIN_KEPT} captures.")
    if len({f.shape for f in deaths}) != 1:
        raise SignatureError("Les captures n'ont pas toutes la meme taille.")

    frames = list(deaths)
    dropped = 0

    while True:
        found = _extract_once(frames, gameplay or [])
        if found is None:
            raise SignatureError(
                "Aucun texte commun aux captures.\n"
                "Verifie que tu analyses le bon ecran (--monitor) et que le "
                "texte etait bien affiche a chaque appui sur F8."
            )
        template, mask, box = found
        scores = [raw_score(f, template, mask) for f in frames]
        median = float(np.median(scores))
        worst = int(np.argmin(scores))

        if len(frames) > MIN_KEPT and scores[worst] < median - OUTLIER_MARGIN:
            frames.pop(worst)
            dropped += 1
            continue

        return template, mask, box, scores, dropped


def save_signature(path: Path, template: np.ndarray, mask: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as handle:
        np.savez_compressed(handle, template=template, mask=mask)


def signature_preview(frame: np.ndarray, mask: np.ndarray, box) -> np.ndarray:
    """Bande capturee avec les pixels retenus surlignes, pour verification."""
    x0, y0, x1, y1 = box
    # L'ecran de mort est tres sombre : on l'eclaircit, sinon l'apercu est
    # illisible et ne sert a rien.
    preview = cv2.cvtColor(cv2.convertScaleAbs(frame, alpha=2.2, beta=25),
                           cv2.COLOR_GRAY2BGR)
    zone = preview[y0:y1, x0:x1]
    zone[mask > 0] = (90, 220, 255)
    cv2.rectangle(preview, (x0, y0), (x1 - 1, y1 - 1), (90, 220, 255), 1)
    return preview


# --------------------------------------------------------------- detection

@dataclass
class DetectorConfig:
    threshold: float = 0.45        # mesure : morts >= 0.71, jeu <= 0.23
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
        return raw_score(crop_band(gray_frame), self.template, self.mask)

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
