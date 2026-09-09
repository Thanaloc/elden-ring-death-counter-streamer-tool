"""Point d'entree en ligne de commande."""

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

# La lecture prend environ 350 ms : inutile de viser plus haut, l'ecran de
# mort reste affiche plusieurs secondes.
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
        print(f"La langue '{args.lang}' n'est pas installee.")
        print(f"Disponibles : {', '.join(langs)}\n")
        print(missing_language_help(args.lang))
        print(f"\nOu relance avec une langue disponible : --lang {langs[0]}")
        return 1

    with mss.mss() as sct:
        for i, m in enumerate(sct.monitors[1:], start=1):
            marker = "  <-- selectionne" if i == args.monitor else ""
            print(f"Ecran {i} : {m['width']}x{m['height']}{marker}")
        print()

    try:
        band = wait_for_death(args.monitor)
    except KeyboardInterrupt:
        print("\nSetup annule.")
        return 1

    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    imwrite_png(SAMPLES_DIR / f"mort-{time.strftime('%Y%m%d-%H%M%S')}.png", band)
    print("Capture faite. Recherche du texte...\n")

    height, width = band.shape[:2]
    proposed = locate_text(band, args.lang) or (
        int(width * 0.15), int(height * 0.40),
        int(width * 0.85), int(height * 0.70))

    zone = proposed
    if not args.no_confirm:
        try:
            zone = confirm_zone(band, proposed, port=args.port)
        except KeyboardInterrupt:
            print("\nSetup annule.")
            return 1

    x0, y0, x1, y1 = zone
    crop = band[y0:y1, x0:x1]

    # On garde l'image exacte soumise a l'OCR : c'est la premiere chose a
    # regarder quand la lecture echoue.
    crop_path = DEFAULT_STATE_PATH.parent / "zone-lue.png"
    imwrite_png(crop_path, crop)

    texts, errors = read_text_verbose(crop, args.lang)
    readings = [t for t in texts if len(t) >= 4]

    if not readings:
        if errors:
            print("Tesseract a echoue :")
            for message in errors:
                print(f"  {message[:200]}")
            print(f"\nDossier de langues utilise : {tessdata_dir()}")
            print(f"Langues visibles : {', '.join(available_languages()) or 'aucune'}")
        else:
            print("Aucun texte lisible dans cette zone.")
            print(f"Ce qui a ete lu : {texts}")
            print(f"\nRegarde l'image reellement analysee : {crop_path}")
            print("Si le texte y est net, essaie un cadre un peu plus large,")
            print("ou refais le setup avec le texte pleinement affiche.")
        return 1

    # Le meme texte lu par plusieurs preparations differentes est le plus sur.
    reference = max(readings, key=readings.count)
    Detection(zone, reference, args.lang).save(DETECTION_PATH)

    preview = cv2.cvtColor(cv2.convertScaleAbs(band, alpha=2.2, beta=25),
                           cv2.COLOR_GRAY2BGR)
    cv2.rectangle(preview, (x0, y0), (x1 - 1, y1 - 1), (90, 220, 255), 1)
    imwrite_png(PREVIEW_PATH, preview)

    print(f"Texte de reference : {reference}")
    print(f"Zone : {zone}")
    print(f"Reglage enregistre : {DETECTION_PATH}")
    print(f"Apercu : {PREVIEW_PATH}")
    print("\nVerifie avec : elden-counter diagnose")
    return 0


# ------------------------------------------------------------------ run

def cmd_run(args) -> int:
    print(f"elden-counter {__version__}\n")
    detection = Detection.load(DETECTION_PATH)
    manual = args.manual or detection is None
    if manual and not args.manual:
        print("Aucun reglage enregistre : demarrage en mode manuel.")
        print("Le comptage se fait aux raccourcis clavier.\n")

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
            print(f"{exc}\n\nDemarrage en mode manuel.\n")

    serve(log, port=args.port)
    print(f"Overlay disponible sur http://127.0.0.1:{args.port}")
    print("Ajoute-le dans OBS comme source navigateur, 600x300, "
          "fond transparent.\n")

    _bind_hotkeys(log)

    snap = log.snapshot()
    print(f"Boss : {snap['boss_name'] or 'aucun'} — {snap['boss_count']} morts "
          f"| total : {snap['total']}")
    if detector is not None:
        print(f"Recherche de : {detector.detection.reference}")
    print("Ctrl+C pour arreter.\n")

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
                        print(f"Mort comptee — {s['boss_count']} sur ce boss, "
                              f"{s['total']} au total")
                    elif args.debug:
                        print(f"{detector.last_score:.2f}  "
                              f"{detector.last_text[:24]:24s}", end="\r")
                    time.sleep(max(0.0, period - (time.time() - started)))
    except KeyboardInterrupt:
        s = log.snapshot()
        print(f"\nArret. {s['boss_count']} morts sur ce boss, "
              f"{s['total']} au total.")
    return 0


def _bind_hotkeys(log: DeathLog) -> None:
    try:
        import keyboard
    except ImportError:
        print("Module 'keyboard' absent : raccourcis desactives.")
        return

    def beaten():
        s = log.snapshot()
        log.clear_boss()
        print(f"Boss vaincu en {s['boss_count']} morts. Compteur remis a zero.")

    try:
        keyboard.add_hotkey("f9", lambda: log.adjust(+1))
        keyboard.add_hotkey("f10", lambda: log.adjust(-1))
        keyboard.add_hotkey("f11", lambda: log.reset_boss())
        keyboard.add_hotkey("f12", beaten)
        print("F9 +1 | F10 -1 | F11 remettre le boss a zero | F12 boss vaincu")
    except Exception as exc:
        print(f"Raccourcis indisponibles ({exc}). Sous Windows, lance le "
              "terminal en administrateur.")


# ------------------------------------------------------------- diagnostic

def cmd_diagnose(args) -> int:
    print(f"elden-counter {__version__}\n")
    detection = Detection.load(DETECTION_PATH)
    if detection is None:
        print(f"Aucun reglage a l'emplacement attendu : {DETECTION_PATH}")
        print("Lance d'abord : elden-counter setup")
        return 1

    try:
        detector = TextDetector(detection,
                                DetectorConfig(similarity=args.similarity))
    except OcrUnavailable as exc:
        print(exc)
        return 1

    print(f"Recherche de : {detection.reference}")
    print(f"Analyse pendant {args.seconds} secondes.\n")

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

    print(f"\nMeilleure similitude : {best:.2f}  (seuil {args.similarity})")
    print(f"Texte lu a ce moment  : {best_text}")
    print(f"Similitude mediane    : {sorted(scores)[len(scores) // 2]:.2f}")
    return 0


# ---------------------------------------------------------------- divers

def cmd_langues(args) -> int:
    """
    Verifie que le moteur est utilisable et liste les langues disponibles.

    Sert autant a l'utilisateur qu'a la chaine de construction : si le
    binaire publie n'embarque pas les langues, autant s'en apercevoir
    pendant le build plutot que chez le joueur.
    """
    try:
        require_tesseract()
    except OcrUnavailable as exc:
        print(exc)
        return 1

    langs = available_languages()
    folder = tessdata_dir()
    print(f"Dossier de langues : {folder}")
    if folder is not None and not str(folder).isascii():
        print("  ATTENTION : ce chemin contient un accent, Tesseract ne "
              "saura pas le lire.")
    print(f"Langues disponibles : {', '.join(langs) or 'aucune'}")

    utiles = [l for l in langs if l != "osd"]
    if len(utiles) < 2:
        print("\nSeul l'anglais est disponible. Pour ajouter une langue :")
        print(missing_language_help("fra"))
        return 1
    return 0


def cmd_boss(args) -> int:
    log = DeathLog()
    log.set_boss(args.name, keep_count=args.keep)
    s = log.snapshot()
    print(f"Boss courant : {s['boss_name']} — {s['boss_count']} morts")
    return 0


def cmd_history(args) -> int:
    entries = DeathLog().history
    if not entries:
        print("Aucun boss archive pour l'instant.")
        return 0
    width = max(len(e["name"]) for e in entries)
    for e in entries:
        print(f"{e['name']:<{width}}  {e['deaths']:>4} morts  {e['cleared_at'][:10]}")
    return 0


def cmd_reset(args) -> int:
    log = DeathLog()
    if args.all:
        log.reset_all()
        print("Tout a ete remis a zero, historique compris.")
    else:
        log.reset_boss()
        print("Compteur du boss remis a zero. Le total est conserve.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="elden-counter",
        description="Compteur de morts Elden Ring pour OBS et Streamlabs.")
    parser.add_argument("--version", action="version",
                        version=f"elden-counter {__version__}")

    screen = argparse.ArgumentParser(add_help=False)
    screen.add_argument("--monitor", type=int, default=1,
                        help="ecran a analyser (1 = principal)")
    screen.add_argument("--lang", default="fra",
                        help="langue du jeu, code Tesseract (fra, eng, deu...)")

    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("setup", parents=[screen],
                       help="reperer le texte de mort a l'ecran")
    p.add_argument("--port", type=int, default=4748)
    p.add_argument("--no-confirm", action="store_true",
                   help="accepter la zone detectee sans verification")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("run", parents=[screen], help="detection et overlay")
    p.add_argument("--boss", default=None)
    p.add_argument("--keep", action="store_true")
    p.add_argument("--port", type=int, default=4747)
    p.add_argument("--similarity", type=float, default=0.60)
    p.add_argument("--confirm", type=int, default=1)
    p.add_argument("--manual", action="store_true",
                   help="ne compter qu'aux raccourcis clavier")
    p.add_argument("--debug", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("diagnose", parents=[screen],
                       help="verifier ce que lit le detecteur")
    p.add_argument("--seconds", type=int, default=25)
    p.add_argument("--similarity", type=float, default=0.60)
    p.set_defaults(func=cmd_diagnose)

    p = sub.add_parser("langues", help="lister les langues reconnues")
    p.set_defaults(func=cmd_langues)

    p = sub.add_parser("boss", help="changer le boss affiche")
    p.add_argument("name")
    p.add_argument("--keep", action="store_true")
    p.set_defaults(func=cmd_boss)

    p = sub.add_parser("history", help="lister les boss vaincus")
    p.set_defaults(func=cmd_history)

    p = sub.add_parser("reset", help="remettre des compteurs a zero")
    p.add_argument("--all", action="store_true")
    p.set_defaults(func=cmd_reset)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
