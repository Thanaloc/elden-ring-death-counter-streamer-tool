"""
Death screen detection by reading the text.

The earlier approach matched the shape of a learned fingerprint. It worked,
but it had no idea what it was looking at: the edge of the dark veil, or the
map dialog, resembled it enough to trigger a count.

Reading the text is specific to meaning. A darkened band reads as nothing,
the map reads as something else. Measured on real captures: 8 deaths out of
12 read, no false positive across 37 images including menus and map.

The 4 unread deaths are degraded frames (mid-fade, washed out). At runtime
the screen is checked several times per second while the text is up, so one
successful read is enough.
"""

from __future__ import annotations

import difflib
import json
import os
import shutil
import sys
import tempfile
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

# Where to look for the engine: the copy bundled in the executable first,
# then the usual installs. pytesseract only checks PATH, where Tesseract
# almost never is.
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
    """Where PyInstaller unpacked resources, if it did."""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else None


def _candidate_binaries():
    """The bundled copy wins over the system one.

    A hand-made install often ships English only, while the copy shipped with
    the executable carries the common languages. Checking PATH first would
    prefer the poorer one.
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


def _is_ascii(path: Path) -> bool:
    return str(path).isascii()


def _short_path(path: Path) -> Path:
    """Windows 8.3 short form of a path, when one exists.

    C:\\Users\\Jean Francois becomes C:\\Users\\JEANFR~1, which has the good
    taste of being pure ASCII.
    """
    if os.name != "nt":
        return path
    try:
        import ctypes
        from ctypes import wintypes

        get_short = ctypes.windll.kernel32.GetShortPathNameW
        get_short.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        get_short.restype = wintypes.DWORD

        buffer = ctypes.create_unicode_buffer(1024)
        length = get_short(str(path), buffer, 1024)
        if length and length < 1024 and buffer.value:
            return Path(buffer.value)
    except Exception:
        pass
    return path


def user_tessdata() -> Path:
    """Persistent language folder, guaranteed free of accented characters.

    The one bundled in the executable lives in a temp folder recreated on
    every launch, so nothing can be added to it. But the home folder is no
    good either once the username contains an accent: Tesseract then fails
    with "Illegal byte sequence", because it opens files through an API that
    does not handle Unicode.

    Tried in order: the home folder if it is ASCII, its 8.3 short form, then
    a neutral system location.
    """
    home = Path.home() / ".elden-death-counter" / "tessdata"
    if _is_ascii(home):
        return home

    home.mkdir(parents=True, exist_ok=True)
    short = _short_path(home)
    if _is_ascii(short):
        return short

    base = os.environ.get("PROGRAMDATA") or os.environ.get("ALLUSERSPROFILE")
    if base and Path(base).is_dir():
        neutral = Path(base) / "elden-death-counter" / "tessdata"
        if _is_ascii(neutral):
            return neutral

    return Path(tempfile.gettempdir()) / "elden-counter-tessdata"


def _prepare_tessdata(binary: Path) -> Path | None:
    bundled = binary.parent / "tessdata"
    if _bundle_root() is None:
        # Regular install: copy nothing, unless the path is accented and
        # therefore unreadable by Tesseract.
        if bundled.is_dir() and not _is_ascii(bundled):
            short = _short_path(bundled)
            return short if _is_ascii(short) else bundled
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
    """Explain how to add a missing language, with the exact path."""
    folder = tessdata_dir()
    lines = [
        f"Download {lang}.traineddata from:",
        f"  https://github.com/tesseract-ocr/tessdata_fast/raw/main/{lang}.traineddata",
    ]
    if folder is not None:
        lines.append(f"and drop it in:\n  {folder}")
        lines.append("\nThis folder persists between runs, so you only need to "
                     "do it once.")
    else:
        lines.append("and drop it in your install's tessdata folder.")
    return "\n".join(lines)


def require_tesseract() -> None:
    """Make sure the engine is usable, configuring it if needed.

    The executable ships its own copy of Tesseract, but pytesseract still
    has to be told where it is and where the language data lives, otherwise
    it only looks at PATH.
    """
    if pytesseract is None:
        raise OcrUnavailable(
            "The pytesseract module is not installed.\n"
            "Run: pip install pytesseract, then install the Tesseract engine."
        )

    binary = _locate_binary()
    if binary is not None:
        pytesseract.pytesseract.tesseract_cmd = str(binary)
        tessdata = _prepare_tessdata(binary)
        if tessdata is not None:
            if not _is_ascii(tessdata):
                tessdata = _short_path(tessdata)
            # setdefault is not enough: a value inherited from the system
            # would point at a different install than the one selected.
            os.environ["TESSDATA_PREFIX"] = str(tessdata)

    prefix = os.environ.get("TESSDATA_PREFIX", "")
    if prefix and not prefix.isascii():
        raise OcrUnavailable(
            "The language data folder contains an accented character:\n"
            f"  {prefix}\n\n"
            "Tesseract cannot open such a path. Point TESSDATA_PREFIX at a "
            "folder without accents, for example "
            "C:\\ProgramData\\elden-death-counter\\tessdata, and copy the "
            ".traineddata files there."
        )

    try:
        pytesseract.get_tesseract_version()
    except Exception as exc:
        tried = "\n".join(f"  {c}" for c in _candidate_binaries())
        raise OcrUnavailable(
            "Tesseract was not found on this system.\n"
            "Windows: https://github.com/UB-Mannheim/tesseract/wiki\n"
            "  (tick your game's language during install)\n"
            "Linux: apt install tesseract-ocr\n"
            f"\nLocations tried:\n{tried}\n"
            f"\n({exc})"
        ) from exc


def available_languages() -> list:
    try:
        return sorted(pytesseract.get_languages(config=""))
    except Exception:
        return []


def normalise(text: str) -> str:
    """Uppercase, no accents or punctuation, so comparison is noise-free."""
    text = unicodedata.normalize("NFD", text.upper())
    return "".join(c for c in text if c.isalpha() and ord(c) < 128)


def variants(crop: np.ndarray) -> list:
    """Three preparations of the image, all tried.

    None is enough alone: the text is sometimes lighter than its background,
    sometimes darker, and its contrast varies enormously between areas of the
    game. This combination read 8 captures out of 12, where the best single
    preparation read 7.
    """
    stretched = cv2.normalize(crop, None, 0, 255, cv2.NORM_MINMAX)
    big = cv2.resize(stretched, None, fx=UPSCALE, fy=UPSCALE,
                     interpolation=cv2.INTER_CUBIC)

    local = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(crop)
    local = cv2.resize(local, None, fx=UPSCALE, fy=UPSCALE,
                       interpolation=cv2.INTER_CUBIC)

    _, binary = cv2.threshold(big, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return [255 - big, local, binary]


def read_text_verbose(crop: np.ndarray, lang: str):
    """Texts read, one per preparation, plus any errors.

    Telling "nothing to read" apart from "the engine failed" matters: both
    yield an empty string, but call for completely different fixes.
    """
    config = f"{TESSERACT_CONFIG} -l {lang}"
    texts, errors = [], []
    for image in variants(crop):
        try:
            texts.append(normalise(pytesseract.image_to_string(image, config=config)))
        except Exception as exc:
            texts.append("")
            message = str(exc).strip()
            if message and message not in errors:
                errors.append(message)
    return texts, errors


def read_text(crop: np.ndarray, lang: str) -> list:
    return read_text_verbose(crop, lang)[0]


def locate_text(band: np.ndarray, lang: str):
    """Propose the text zone by asking Tesseract where it sees words.

    Returns (x0, y0, x1, y1) in band coordinates, or None.
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
        except Exception as exc:
            print(f"  (automatic locating unavailable: "
                  f"{str(exc).strip()[:120]})")
            continue

        words = [i for i in range(len(data["text"]))
                 if data["text"][i].strip() and int(data["conf"][i]) > 45]
        if not words:
            continue

        # The busiest line: the death text sits on a single line.
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
    """What setup produces: where to look, and what to read there."""
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
    similarity: float = 0.60   # measured: true deaths >= 0.85, rest <= 0.40
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
        """Similarity between what is read in the zone and the reference."""
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
        """Call regularly. Returns True once per death."""
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
