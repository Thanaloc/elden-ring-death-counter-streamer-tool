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

import itertools
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
MAX_BLOCK_RATIO = 4.5    # au-dela, c'est un ruban (bord de voile), pas une lettre
MIN_BLOCK_HEIGHT = 5     # une lettre a une epaisseur verticale
MIN_BLOCKS = 8           # un texte fait plusieurs blocs, un ruban un seul
MIN_CAPTURES = 4         # une capture ratee peut etre ecartee, il en reste 3
MIN_KEPT = 3
MIN_MARGIN = 0.15        # ecart minimal exige entre morts et jeu normal


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

    # Pas de fermeture ici : le tri par forme se fait sur les blocs separes.
    mask = cv2.morphologyEx(keep.astype(np.uint8), cv2.MORPH_OPEN,
                            np.ones((2, 2), np.uint8))
    return mask, mean


def _letter_blocks(mask: np.ndarray):
    """
    Garde les blocs qui ont une forme de lettre.

    A ce stade les lettres sont encore separees : c'est le seul moment ou
    l'on peut distinguer du texte d'un bord de voile, qui est un ruban long
    et plat. Une fois la fermeture appliquee, les deux se ressemblent.
    """
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    height, width = mask.shape

    blocks = []
    for i in range(1, count):
        w = stats[i, cv2.CC_STAT_WIDTH]
        h = stats[i, cv2.CC_STAT_HEIGHT]
        if stats[i, cv2.CC_STAT_AREA] < 15:
            continue
        if h < MIN_BLOCK_HEIGHT or w / max(h, 1) > MAX_BLOCK_RATIO:
            continue
        if w > width * 0.5 or h > height * 0.5:
            continue
        blocks.append(i)

    return blocks, labels, stats, centroids


def _extract_once(deaths: list, gameplay: list, zone=None):
    mask, mean = _candidate_mask(deaths, gameplay)

    if zone is not None:
        x0, y0, x1, y1 = zone
        limited = np.zeros_like(mask)
        limited[y0:y1, x0:x1] = mask[y0:y1, x0:x1]
        mask = limited
    blocks, labels, stats, centroids = _letter_blocks(mask)
    if len(blocks) < MIN_BLOCKS:
        return None

    # Le texte tient sur une ligne : on garde les blocs qui la partagent.
    heights = [stats[i, cv2.CC_STAT_HEIGHT] for i in blocks]
    line_y = float(np.median([centroids[i][1] for i in blocks]))
    line_h = float(np.median(heights))
    kept = [i for i in blocks
            if abs(centroids[i][1] - line_y) < max(line_h * 1.5, 12)]
    if len(kept) < MIN_BLOCKS:
        return None

    text = np.isin(labels, kept).astype(np.uint8)
    # Les lettres ne sont recollees qu'apres le tri, pour la correlation.
    text = cv2.morphologyEx(
        text, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (15, 5))).astype(np.float32)

    ys, xs = np.nonzero(text)
    if xs.size < 150:
        return None

    pad = 6
    x0, y0 = max(0, int(xs.min()) - pad), max(0, int(ys.min()) - pad)
    x1 = min(mask.shape[1], int(xs.max()) + pad + 1)
    y1 = min(mask.shape[0], int(ys.max()) + pad + 1)

    return (np.ascontiguousarray(mean[y0:y1, x0:x1]),
            np.ascontiguousarray(text[y0:y1, x0:x1]), (x0, y0, x1, y1))


def signature_in_zone(deaths: list, gameplay: list, zone):
    """
    Reconstruit la signature en bornant la recherche a la zone confirmee.

    Tout le travail automatique est conserve : constance entre les morts,
    exclusion de l'interface, tri par forme, et selection des captures par
    la marge. La zone ne fait que borner l'endroit ou l'on cherche.
    """
    template, mask, box, _, _ = extract_signature(deaths, gameplay, zone=zone)
    return template, mask, box


def raw_score(frame: np.ndarray, template: np.ndarray, mask: np.ndarray) -> float:
    band = highpass(frame)
    if band.shape[0] < template.shape[0] or band.shape[1] < template.shape[1]:
        return 0.0
    result = cv2.matchTemplate(band, template, cv2.TM_CCORR_NORMED, mask=mask)
    result = result[np.isfinite(result)]
    return float(result.max()) if result.size else 0.0


def _evaluate(template, mask, kept: list, gameplay: list):
    """
    Note une signature par la marge qu'elle laisse entre morts et jeu normal.

    C'est la seule mesure qui compte vraiment : une signature accrochee au
    bord du voile obtient d'excellents scores sur les morts, mais se
    declenche aussi sur des moments de jeu. La marge le revele tout de suite.
    """
    on_deaths = [raw_score(f, template, mask) for f in kept]
    on_gameplay = [raw_score(f, template, mask) for f in gameplay] or [0.0]
    return min(on_deaths) - max(on_gameplay), on_deaths, on_gameplay


def extract_signature(deaths: list, gameplay: list | None = None,
                      zone=None):
    """
    Isole le texte a partir de plusieurs morts.

    Si `zone` est fournie, la recherche est bornee a ce rectangle : c'est
    le cas du cadrage manuel. Le tri des captures reste indispensable la
    aussi, une mauvaise capture deviant la signature meme dans la bonne zone.

    Une capture prise pendant un fondu, ou dans une scene ou le voile
    domine, oriente l'extraction vers un bord d'assombrissement plutot que
    vers le texte. Plutot que de deviner laquelle poser de cote, on essaie
    les differentes combinaisons et on garde celle qui separe le mieux les
    morts du jeu normal.

    Retourne (template, mask, box, scores, ecartees).
    """
    if len(deaths) < MIN_KEPT:
        raise SignatureError(f"Il faut au moins {MIN_KEPT} captures.")
    if len({f.shape for f in deaths}) != 1:
        raise SignatureError("Les captures n'ont pas toutes la meme taille.")

    gameplay = gameplay or []
    best = None

    # D'abord toutes les captures, puis les combinaisons ou l'on en retire
    # une, deux... tant qu'il en reste assez.
    for size in range(len(deaths), MIN_KEPT - 1, -1):
        for combo in itertools.combinations(range(len(deaths)), size):
            subset = [deaths[i] for i in combo]
            found = _extract_once(subset, gameplay, zone)
            if found is None:
                continue
            template, mask, box = found
            margin, on_deaths, _ = _evaluate(template, mask, subset, gameplay)
            if best is None or margin > best[0]:
                best = (margin, template, mask, box, on_deaths,
                        len(deaths) - size)
        # Une combinaison complete qui separe bien vaut mieux qu'une
        # combinaison plus courte : inutile de continuer a en retirer.
        if best is not None and best[0] >= MIN_MARGIN:
            break

    if best is None:
        raise SignatureError(
            "Aucune forme de texte commune aux captures.\n"
            "Verifie que tu analyses le bon ecran (--monitor), que le "
            "texte etait affiche a chaque appui sur F8, et que tu es "
            "bien mort a des endroits differents."
        )

    margin, template, mask, box, scores, dropped = best
    if margin < MIN_MARGIN:
        raise SignatureError(
            f"La meilleure signature ne laisse qu'une marge de {margin:.2f} "
            f"entre les morts et le jeu normal (il en faut {MIN_MARGIN}).\n"
            "Elle s'accroche sans doute a un assombrissement de l'ecran "
            "plutot qu'au texte. Refais le setup en mourant dans des "
            "decors plus varies."
        )

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
    threshold: float = 0.55        # mesure : morts >= 0.78, jeu <= 0.35
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
