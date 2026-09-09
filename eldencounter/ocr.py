"""
Detection de l'ecran de mort par lecture du texte.

L'approche precedente correlait la forme d'une empreinte apprise. Elle
marchait, mais elle ne comprenait pas ce qu'elle regardait : un bord de
voile ou la boite de dialogue de la carte lui ressemblaient assez pour la
declencher, et il fallait tout un echafaudage pour les ecarter.

Lire le texte est specifique au sens. Un assombrissement ne lit rien, la
carte lit autre chose. Mesure sur des captures reelles : 8 morts sur 12
lues, aucun faux positif sur 37 images dont menus et carte.

Les 4 morts non lues sont des images degradees (fondu, texte delave). En
fonctionnement on analyse plusieurs images par seconde pendant les
secondes d'affichage : il suffit qu'une seule passe.
"""

from __future__ import annotations

import difflib
import json
import os
import shutil
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

try:
    import pytesseract
except ImportError:                                   # pragma: no cover
    pytesseract = None

TESSERACT_CONFIG = "--psm 7"
UPSCALE = 3

# Emplacements ou chercher le moteur, dans l'ordre : celui embarque dans
# l'executable, puis les installations classiques. pytesseract ne regarde
# que le PATH par defaut, ou Tesseract n'est presque jamais.
BUNDLED_SUBDIR = "tesseract"
WINDOWS_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)
UNIX_PATHS = ("/usr/bin/tesseract", "/usr/local/bin/tesseract",
              "/opt/homebrew/bin/tesseract")


class OcrUnavailable(RuntimeError):
    pass


def _bundle_root() -> Path | None:
    """Dossier ou PyInstaller a decompresse les ressources, s'il y en a un."""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else None


def _candidate_binaries():
    """
    La copie embarquee passe avant celle du systeme.

    Une installation faite a la main contient souvent le seul anglais ; la
    copie livree avec l'executable, elle, embarque les langues courantes.
    Chercher le PATH en premier reviendrait a preferer la moins fournie.
    """
    root = _bundle_root()
    if root is not None:
        folder = root / BUNDLED_SUBDIR
        yield folder / "tesseract.exe"
        yield folder / "tesseract"

    found = shutil.which("tesseract")
    if found:
        yield Path(found)

    for path in (WINDOWS_PATHS if os.name == "nt" else UNIX_PATHS):
        yield Path(path)


def _locate_binary() -> Path | None:
    for candidate in _candidate_binaries():
        if candidate.is_file():
            return candidate
    return None


def user_tessdata() -> Path:
    """
    Dossier de langues persistant, dans le repertoire de l'outil.

    Celui embarque dans l'executable vit dans un dossier temporaire recree
    a chaque lancement : impossible d'y deposer quoi que ce soit. On recopie
    donc son contenu une fois dans un emplacement stable, ou l'utilisateur
    peut ajouter les langues qui lui manquent.
    """
    return Path.home() / ".elden-death-counter" / "tessdata"


def _prepare_tessdata(binary: Path) -> Path | None:
    bundled = binary.parent / "tessdata"
    if _bundle_root() is None:
        return bundled if bundled.is_dir() else None

    target = user_tessdata()
    target.mkdir(parents=True, exist_ok=True)
    if bundled.is_dir():
        for source in bundled.glob("*.traineddata"):
            destination = target / source.name
            if not destination.exists():
                try:
                    shutil.copy2(source, destination)
                except OSError:
                    pass
    return target


def tessdata_dir() -> Path | None:
    prefix = os.environ.get("TESSDATA_PREFIX")
    if prefix and Path(prefix).is_dir():
        return Path(prefix)
    binary = _locate_binary()
    if binary is not None and (binary.parent / "tessdata").is_dir():
        return binary.parent / "tessdata"
    return None


def missing_language_help(lang: str) -> str:
    """Explique comment ajouter une langue absente, avec le chemin exact."""
    folder = tessdata_dir()
    lines = [
        f"Telecharge {lang}.traineddata depuis :",
        f"  https://github.com/tesseract-ocr/tessdata_fast/raw/main/{lang}.traineddata",
    ]
    if folder is not None:
        lines.append(f"et depose-le dans :\n  {folder}")
        lines.append("\nCe dossier est conserve d'un lancement a l'autre : "
                     "le fichier n'est a deposer qu'une fois.")
    else:
        lines.append("et depose-le dans le dossier tessdata de ton installation.")
    return "\n".join(lines)


def require_tesseract() -> None:
    """
    S'assure que le moteur est utilisable, et le configure si besoin.

    L'executable embarque sa propre copie de Tesseract ; encore faut-il
    indiquer a pytesseract ou elle se trouve, et ou sont les donnees de
    langue, sans quoi il ne regarde que le PATH.
    """
    if pytesseract is None:
        raise OcrUnavailable(
            "Le module pytesseract n'est pas installe.\n"
            "pip install pytesseract, et installe le moteur Tesseract."
        )

    binary = _locate_binary()
    if binary is not None:
        pytesseract.pytesseract.tesseract_cmd = str(binary)
        tessdata = _prepare_tessdata(binary)
        if tessdata is not None:
            # setdefault ne suffit pas : une variable heritee du systeme
            # pointerait vers une autre installation que celle retenue.
            os.environ["TESSDATA_PREFIX"] = str(tessdata)

    try:
        pytesseract.get_tesseract_version()
    except Exception as exc:
        tried = "\n".join(f"  {c}" for c in _candidate_binaries())
        raise OcrUnavailable(
            "Tesseract est introuvable sur ce systeme.\n"
            "Windows : https://github.com/UB-Mannheim/tesseract/wiki\n"
            "  (coche bien ta langue de jeu pendant l'installation)\n"
            "Linux : apt install tesseract-ocr tesseract-ocr-fra\n"
            f"\nEmplacements essayes :\n{tried}\n"
            f"\n({exc})"
        ) from exc


def available_languages() -> list:
    try:
        return sorted(pytesseract.get_languages(config=""))
    except Exception:
        return []


def normalise(text: str) -> str:
    """Majuscules sans accents ni ponctuation, pour comparer sans bruit."""
    text = unicodedata.normalize("NFD", text.upper())
    return "".join(c for c in text if c.isalpha() and ord(c) < 128)


def variants(crop: np.ndarray) -> list:
    """
    Trois preparations de l'image, essayees en parallele.

    Aucune ne suffit seule : le texte est tantot plus clair que le fond,
    tantot plus sombre, et son contraste varie enormement d'une zone du
    jeu a l'autre. Cette combinaison a lu 8 captures sur 12 la ou la
    meilleure preparation seule en lisait 7.
    """
    stretched = cv2.normalize(crop, None, 0, 255, cv2.NORM_MINMAX)
    big = cv2.resize(stretched, None, fx=UPSCALE, fy=UPSCALE,
                     interpolation=cv2.INTER_CUBIC)

    local = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(crop)
    local = cv2.resize(local, None, fx=UPSCALE, fy=UPSCALE,
                       interpolation=cv2.INTER_CUBIC)

    _, binary = cv2.threshold(big, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return [255 - big, local, binary]


def read_text(crop: np.ndarray, lang: str) -> list:
    """Textes lus, un par preparation."""
    config = f"{TESSERACT_CONFIG} -l {lang}"
    out = []
    for image in variants(crop):
        try:
            out.append(normalise(pytesseract.image_to_string(image, config=config)))
        except Exception:
            out.append("")
    return out


def locate_text(band: np.ndarray, lang: str):
    """
    Propose la zone du texte en demandant a Tesseract ou il voit des mots.

    Retourne (x0, y0, x1, y1) dans le repere de la bande, ou None.
    """
    stretched = cv2.normalize(band, None, 0, 255, cv2.NORM_MINMAX)
    big = cv2.resize(stretched, None, fx=UPSCALE, fy=UPSCALE,
                     interpolation=cv2.INTER_CUBIC)

    best = None
    for image in (255 - big, big):
        try:
            data = pytesseract.image_to_data(
                image, config=f"--psm 6 -l {lang}",
                output_type=pytesseract.Output.DICT)
        except Exception:
            continue

        words = [i for i in range(len(data["text"]))
                 if data["text"][i].strip() and int(data["conf"][i]) > 45]
        if not words:
            continue

        # La ligne la plus fournie : le texte de mort tient sur une ligne.
        lines = {}
        for i in words:
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines.setdefault(key, []).append(i)
        line = max(lines.values(), key=len)

        x0 = min(data["left"][i] for i in line)
        y0 = min(data["top"][i] for i in line)
        x1 = max(data["left"][i] + data["width"][i] for i in line)
        y1 = max(data["top"][i] + data["height"][i] for i in line)
        score = sum(int(data["conf"][i]) for i in line)

        if best is None or score > best[0]:
            pad_x, pad_y = 6, 3
            best = (score,
                    (max(0, x0 // UPSCALE - pad_x), max(0, y0 // UPSCALE - pad_y),
                     min(band.shape[1], x1 // UPSCALE + pad_x),
                     min(band.shape[0], y1 // UPSCALE + pad_y)))

    return best[1] if best else None


# ------------------------------------------------------------------ reglage

@dataclass
class Detection:
    """Ce qu'il faut retenir du setup : ou regarder, et quoi y lire."""
    zone: tuple
    reference: str
    lang: str = "fra"

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "zone": list(self.zone),
            "reference": self.reference,
            "lang": self.lang,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path):
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(tuple(data["zone"]), data["reference"],
                       data.get("lang", "fra"))
        except (json.JSONDecodeError, KeyError, OSError):
            return None


@dataclass
class DetectorConfig:
    similarity: float = 0.60   # mesure : vraies morts >= 0.85, reste <= 0.40
    confirm_frames: int = 1
    rearm_seconds: float = 8.0


class TextDetector:
    def __init__(self, detection: Detection, config: DetectorConfig | None = None):
        require_tesseract()
        self.detection = detection
        self.cfg = config or DetectorConfig()
        self._armed = True
        self._streak = 0
        self._last_fire = 0.0
        self.last_score = 0.0
        self.last_text = ""

    def score(self, band: np.ndarray) -> float:
        """Similitude entre ce qui est lu dans la zone et le texte de reference."""
        x0, y0, x1, y1 = self.detection.zone
        crop = band[y0:y1, x0:x1]
        if crop.size == 0:
            return 0.0

        best, best_text = 0.0, ""
        for text in read_text(crop, self.detection.lang):
            ratio = difflib.SequenceMatcher(
                None, self.detection.reference, text).ratio()
            if ratio > best:
                best, best_text = ratio, text

        self.last_score, self.last_text = best, best_text
        return best

    def update(self, band: np.ndarray, now: float) -> bool:
        """A appeler regulierement. Retourne True une seule fois par mort."""
        hit = self.score(band) >= self.cfg.similarity

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
