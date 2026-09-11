"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
import time

import cv2
import mss

from . import __version__
from .capture import crop_band, grab, imwrite_png, wait_for_death
from .counter import DEFAULT_STATE_PATH, DeathLog
from .ocr import (Detection, DetectorConfig, OcrUnavailable, TextDetector,
                  available_languages, locate_text,
                  missing_language_help, read_text_verbose,
                  require_tesseract, tessdata_dir)
from .server import serve
from .setup_ui import confirm_zone

DETECTION_PATH = DEFAULT_STATE_PATH.parent / "detection.json"
PREVIEW_PATH = DEFAULT_STATE_PATH.parent / "apercu-setup.png"
SAMPLES_DIR = DEFAULT_STATE_PATH.parent / "echantillons"

# A read takes about 350 ms. No point going faster: the death screen stays
# up for several seconds.
CHECKS_PER_SECOND = 2


# ---------------------------------------------------------------- setup

def cmd_setup(args) -> int:
    print(f"elden-counter {__version__}\n")

    try:
        require_tesseract()
    except OcrUnavailable as exc:
        print(exc)
        return 1

    langs = available_languages()
    if langs and args.lang not in langs:
        print(f"Language '{args.lang}' is not installed.")
        print(f"Available: {', '.join(langs)}\n")
        print(missing_language_help(args.lang))
        print(f"\nOr rerun with an available language: --lang {langs[0]}")
        return 1

    with mss.mss() as sct:
        for i, m in enumerate(sct.monitors[1:], start=1):
            marker = "  <-- selected" if i == args.monitor else ""
            print(f"Display {i}: {m['width']}x{m['height']}{marker}")
        print()

    try:
        band = wait_for_death(args.monitor)
    except KeyboardInterrupt:
        print("\nSetup cancelled.")
        return 1

    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    imwrite_png(SAMPLES_DIR / f"mort-{time.strftime('%Y%m%d-%H%M%S')}.png", band)
    print("Captured. Looking for the text...\n")

    height, width = band.shape[:2]
    proposed = locate_text(band, args.lang) or (
        int(width * 0.15), int(height * 0.40),
        int(width * 0.85), int(height * 0.70))

    zone = proposed
    if not args.no_confirm:
        try:
            zone = confirm_zone(band, proposed, port=args.port)
        except KeyboardInterrupt:
            print("\nSetup cancelled.")
            return 1

    x0, y0, x1, y1 = zone
    crop = band[y0:y1, x0:x1]

    # Keep the exact image handed to the OCR: first thing to look at when
    # a read fails.
    crop_path = DEFAULT_STATE_PATH.parent / "zone-lue.png"
    imwrite_png(crop_path, crop)

    texts, errors = read_text_verbose(crop, args.lang)
    readings = [t for t in texts if len(t) >= 4]

    if not readings:
        if errors:
            print("Tesseract failed:")
            for message in errors:
                print(f"  {message[:200]}")
            print(f"\nLanguage folder in use: {tessdata_dir()}")
            print(f"Languages visible: {', '.join(available_languages()) or 'none'}")
        else:
            print("No readable text in that zone.")
            print(f"What came back: {texts}")
            print(f"\nLook at the image actually analysed: {crop_path}")
            print("If the text is sharp there, try a slightly wider box,")
            print("or redo setup with the text fully faded in.")
        return 1

    # Text agreed on by several preparations is the safest bet.
    reference = max(readings, key=readings.count)
    Detection(zone, reference, args.lang).save(DETECTION_PATH)

    preview = cv2.cvtColor(cv2.convertScaleAbs(band, alpha=2.2, beta=25),
                           cv2.COLOR_GRAY2BGR)
    cv2.rectangle(preview, (x0, y0), (x1 - 1, y1 - 1), (90, 220, 255), 1)
    imwrite_png(PREVIEW_PATH, preview)

    print(f"Reference text: {reference}")
    print(f"Zone: {zone}")
    print(f"Settings saved: {DETECTION_PATH}")
    print(f"Preview: {PREVIEW_PATH}")
    print("\nCheck it with: elden-counter diagnose")
    return 0


# ------------------------------------------------------------------ run

def cmd_run(args) -> int:
    print(f"elden-counter {__version__}\n")
    detection = Detection.load(DETECTION_PATH)
    manual = args.manual or detection is None
    if manual and not args.manual:
        print("No settings saved: starting in manual mode.")
        print("Counting happens on the hotkeys.\n")

    log = DeathLog()
    if args.boss:
        log.set_boss(args.boss, keep_count=args.keep)

    detector = None
    if not manual:
        try:
            detector = TextDetector(
                detection,
                DetectorConfig(similarity=args.similarity,
                               confirm_frames=args.confirm))
        except OcrUnavailable as exc:
            print(f"{exc}\n\nStarting in manual mode.\n")

    serve(log, port=args.port)
    print(f"Overlay available at http://127.0.0.1:{args.port}")
    print("Add it in OBS as a browser source, 600x300, transparent "
          "background.\n")

    _bind_hotkeys(log)

    snap = log.snapshot()
    print(f"Boss: {snap['boss_name'] or 'none'} - {snap['boss_count']} deaths "
          f"| total: {snap['total']}")
    if detector is not None:
        print(f"Looking for: {detector.detection.reference}")
    print("Ctrl+C to stop.\n")

    period = 1.0 / CHECKS_PER_SECOND
    try:
        if detector is None:
            while True:
                time.sleep(0.5)
        else:
            with mss.mss() as sct:
                monitor = sct.monitors[args.monitor]
                while True:
                    started = time.time()
                    if detector.update(crop_band(grab(sct, monitor)), started):
                        s = log.record_death()
                        print(f"Death counted - {s['boss_count']} on this boss, "
                              f"{s['total']} overall")
                    elif args.debug:
                        print(f"{detector.last_score:.2f}  "
                              f"{detector.last_text[:24]:24s}", end="\r")
                    time.sleep(max(0.0, period - (time.time() - started)))
    except KeyboardInterrupt:
        s = log.snapshot()
        print(f"\nStopped. {s['boss_count']} deaths on this boss, "
              f"{s['total']} overall.")
    return 0


def _bind_hotkeys(log: DeathLog) -> None:
    try:
        import keyboard
    except ImportError:
        print("The 'keyboard' module is missing: hotkeys disabled.")
        return

    def beaten():
        s = log.snapshot()
        log.clear_boss()
        print(f"Boss beaten in {s['boss_count']} deaths. Counter reset.")

    try:
        keyboard.add_hotkey("f9", lambda: log.adjust(+1))
        keyboard.add_hotkey("f10", lambda: log.adjust(-1))
        keyboard.add_hotkey("f11", lambda: log.reset_boss())
        keyboard.add_hotkey("f12", beaten)
        print("F9 +1 | F10 -1 | F11 reset boss | F12 boss beaten")
    except Exception as exc:
        print(f"Hotkeys unavailable ({exc}). On Windows, try running the "
              "terminal as administrator.")


# ------------------------------------------------------------- diagnostic

def cmd_diagnose(args) -> int:
    print(f"elden-counter {__version__}\n")
    detection = Detection.load(DETECTION_PATH)
    if detection is None:
        print(f"No settings at the expected location: {DETECTION_PATH}")
        print("Run this first: elden-counter setup")
        return 1

    try:
        detector = TextDetector(detection,
                                DetectorConfig(similarity=args.similarity))
    except OcrUnavailable as exc:
        print(exc)
        return 1

    print(f"Looking for: {detection.reference}")
    print(f"Watching for {args.seconds} seconds.\n")

    scores, best, best_text = [], -1.0, ""
    period = 1.0 / CHECKS_PER_SECOND
    deadline = time.time() + args.seconds

    with mss.mss() as sct:
        monitor = sct.monitors[args.monitor]
        while time.time() < deadline:
            started = time.time()
            score = detector.score(crop_band(grab(sct, monitor)))
            scores.append(score)
            if score > best:
                best, best_text = score, detector.last_text
            print(f"{score:.2f}  {detector.last_text[:30]}")
            time.sleep(max(0.0, period - (time.time() - started)))

    print(f"\nBest similarity  : {best:.2f}  (threshold {args.similarity})")
    print(f"Text read then   : {best_text}")
    print(f"Median similarity: {sorted(scores)[len(scores) // 2]:.2f}")
    return 0


# ---------------------------------------------------------------- divers

def cmd_languages(args) -> int:
    """Check the engine works and list the available languages.

    Useful to the user and to the build pipeline alike: if a published binary
    ships without its languages, better to find out during the build than at
    the player's machine.
    """
    try:
        require_tesseract()
    except OcrUnavailable as exc:
        print(exc)
        return 1

    langs = available_languages()
    folder = tessdata_dir()
    print(f"Language folder: {folder}")
    if folder is not None and not str(folder).isascii():
        print("  WARNING: this path contains an accent, Tesseract will not "
              "be able to read it.")
    print(f"Available languages: {', '.join(langs) or 'none'}")

    utiles = [l for l in langs if l != "osd"]
    if len(utiles) < 2:
        print("\nEnglish only. To add a language:")
        print(missing_language_help("fra"))
        return 1
    return 0


def cmd_boss(args) -> int:
    log = DeathLog()
    log.set_boss(args.name, keep_count=args.keep, count=args.count)
    s = log.snapshot()
    print(f"Current boss: {s['boss_name']} - {s['boss_count']} deaths")
    return 0


def cmd_total(args) -> int:
    log = DeathLog()
    before = log.snapshot()["total"]
    log.set_total(args.value)
    s = log.snapshot()
    print(f"Lifetime total: {before} -> {s['total']}")
    print(f"Current boss unchanged: {s['boss_count']} deaths")
    return 0


def cmd_history(args) -> int:
    entries = DeathLog().history
    if not entries:
        print("No bosses archived yet.")
        return 0
    width = max(len(e["name"]) for e in entries)
    for e in entries:
        print(f"{e['name']:<{width}}  {e['deaths']:>4} deaths  {e['cleared_at'][:10]}")
    return 0


def cmd_reset(args) -> int:
    log = DeathLog()
    if args.all:
        log.reset_all()
        print("Everything reset, history included.")
    else:
        log.reset_boss()
        print("Boss counter reset. The total is untouched.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="elden-counter",
        description="Elden Ring death counter for OBS and Streamlabs.")
    parser.add_argument("--version", action="version",
                        version=f"elden-counter {__version__}")

    screen = argparse.ArgumentParser(add_help=False)
    screen.add_argument("--monitor", type=int, default=1,
                        help="display to watch (1 = primary)")
    screen.add_argument("--lang", default="eng",
                        help="game language, Tesseract code (eng, fra, deu...)")

    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("setup", parents=[screen],
                       help="learn the death text on screen")
    p.add_argument("--port", type=int, default=4748)
    p.add_argument("--no-confirm", action="store_true",
                   help="accept the detected zone without checking")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("run", parents=[screen], help="detection and overlay")
    p.add_argument("--boss", default=None)
    p.add_argument("--keep", action="store_true")
    p.add_argument("--port", type=int, default=4747)
    p.add_argument("--similarity", type=float, default=0.60)
    p.add_argument("--confirm", type=int, default=1)
    p.add_argument("--manual", action="store_true",
                   help="count only on hotkeys")
    p.add_argument("--debug", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("diagnose", parents=[screen],
                       help="watch what the detector reads")
    p.add_argument("--seconds", type=int, default=25)
    p.add_argument("--similarity", type=float, default=0.60)
    p.set_defaults(func=cmd_diagnose)

    p = sub.add_parser("languages", help="list the languages available")
    p.set_defaults(func=cmd_languages)

    p = sub.add_parser("boss", help="change the boss on screen")
    p.add_argument("name")
    p.add_argument("--keep", action="store_true",
                   help="keep the current boss count")
    p.add_argument("--count", type=int, default=None,
                   help="set the boss count to this value")
    p.set_defaults(func=cmd_boss)

    p = sub.add_parser("total", help="set the lifetime total")
    p.add_argument("value", type=int)
    p.set_defaults(func=cmd_total)

    p = sub.add_parser("history", help="list bosses you have beaten")
    p.set_defaults(func=cmd_history)

    p = sub.add_parser("reset", help="reset counters")
    p.add_argument("--all", action="store_true")
    p.set_defaults(func=cmd_reset)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
