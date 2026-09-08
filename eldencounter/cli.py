"""Point d'entree en ligne de commande."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import mss
import numpy as np

from .counter import DEFAULT_STATE_PATH, DeathLog
from .detector import (MIN_CAPTURES, DeathDetector, DetectorConfig,
                       SignatureError, crop_band, extract_signature, grab,
                       imwrite_png, raw_score, save_signature,
                       signature_in_zone, signature_preview, wait_for_frames)
from .setup_ui import confirm_zone
from .server import serve

SIGNATURE_PATH = DEFAULT_STATE_PATH.parent / "signature.npz"
FPS = 4


PREVIEW_PATH = DEFAULT_STATE_PATH.parent / "apercu-setup.png"


SAMPLES_DIR = DEFAULT_STATE_PATH.parent / "echantillons"


def _store_samples(deaths, ambient) -> None:
    """
    Conserve les captures brutes du setup.

    Un setup qui donne une mauvaise signature n'est diagnosticable qu'avec
    les images d'origine. Les garder evite d'avoir a tout refaire.
    """
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    for old in SAMPLES_DIR.glob("*.png"):
        old.unlink()
    for i, frame in enumerate(deaths, start=1):
        imwrite_png(SAMPLES_DIR / f"mort-{i}.png", frame)
    for i, frame in enumerate(ambient, start=1):
        imwrite_png(SAMPLES_DIR / f"jeu-{i:02d}.png", frame)


def cmd_setup(args) -> int:
    with mss.mss() as sct:
        for i, m in enumerate(sct.monitors[1:], start=1):
            marker = "  <-- selectionne" if i == args.monitor else ""
            print(f"Ecran {i} : {m['width']}x{m['height']}{marker}")
        print()

    print(f"Il faut {MIN_CAPTURES} morts, a des endroits differents.")
    print("Entre les morts, joue et deplace-toi : les decors de jeu sont")
    print("preleves tout seuls et servent a eliminer l'interface.\n")

    try:
        deaths, ambient = wait_for_frames(args.monitor, MIN_CAPTURES)
    except KeyboardInterrupt:
        print("\nSetup annule.")
        return 1

    _store_samples(deaths, ambient)
    print(f"\nCaptures conservees dans {SAMPLES_DIR}")

    band_h, band_w = deaths[-1].shape[:2]
    fallback_box = (int(band_w * 0.10), int(band_h * 0.35),
                    int(band_w * 0.90), int(band_h * 0.75))

    template = mask = box = None
    try:
        template, mask, box, scores, dropped = extract_signature(deaths, ambient)
        if dropped:
            print(f"{dropped} capture(s) ecartee(s) : elles orientaient la "
                  "detection ailleurs que sur le texte.")
        print(f"Coherence des captures retenues : "
              f"{min(scores):.2f} a {max(scores):.2f}")
    except SignatureError as exc:
        if args.no_confirm:
            print(f"\n{exc}")
            return 1
        # Echouer ici serait le pire moment : c'est justement quand la
        # detection ne s'en sort pas qu'il faut pouvoir cadrer a la main.
        print(f"\n{exc}")
        print("\nLa detection automatique n'a pas abouti. Tu vas pouvoir "
              "tracer la zone du texte toi-meme.")

    if args.no_confirm and template is not None:
        pass
    else:
        proposed = box if box is not None else fallback_box
        shown = mask if mask is not None else np.zeros((1, 1), np.float32)
        try:
            zone = confirm_zone(deaths[-1], shown, proposed, port=args.port)
        except KeyboardInterrupt:
            print("\nSetup annule.")
            return 1
        if template is None or tuple(zone) != tuple(proposed):
            print("Reconstruction de la signature sur la zone choisie.")
            try:
                template, mask, box = signature_in_zone(deaths, ambient, zone)
            except SignatureError as exc:
                print(f"\n{exc}")
                return 1

    if template is None:
        print("\nAucune signature n'a pu etre construite.")
        return 1

    save_signature(SIGNATURE_PATH, template, mask)
    imwrite_png(PREVIEW_PATH, signature_preview(deaths[-1], mask, box))

    final = [raw_score(f, template, mask) for f in deaths]
    h, w = template.shape
    print(f"\nSignature enregistree : {SIGNATURE_PATH}")
    print(f"  {w}x{h} pixels, {int(mask.sum())} pixels retenus")
    print(f"  scores sur les captures : {min(final):.2f} a {max(final):.2f}")
    print(f"  apercu : {PREVIEW_PATH}")
    print("\nVerifie ensuite avec : elden-counter diagnose")
    return 0


def cmd_run(args) -> int:
    manual = args.manual or not SIGNATURE_PATH.exists()
    if manual and not args.manual:
        print("Aucune signature enregistree : demarrage en mode manuel.")
        print("Le comptage se fait aux raccourcis clavier.\n")

    log = DeathLog()
    if args.boss:
        log.set_boss(args.boss, keep_count=args.keep)

    detector = None
    if not manual:
        detector = DeathDetector(
            SIGNATURE_PATH,
            DetectorConfig(threshold=args.threshold, confirm_frames=args.confirm),
        )

    serve(log, port=args.port)
    print(f"Overlay disponible sur http://127.0.0.1:{args.port}")
    print("Ajoute-le dans OBS comme source navigateur, 600x300, fond transparent.\n")

    _bind_hotkeys(log, args.debug, detector)

    snap = log.snapshot()
    print(f"Boss : {snap['boss_name'] or 'aucun'} — {snap['boss_count']} morts "
          f"| total : {snap['total']}")
    print("Ctrl+C pour arreter.\n")

    period = 1.0 / FPS
    try:
        if detector is None:
            while True:
                time.sleep(0.5)
        else:
            with mss.mss() as sct:
                monitor = sct.monitors[args.monitor]
                while True:
                    started = time.time()
                    if detector.update(grab(sct, monitor)):
                        s = log.record_death()
                        print(f"Mort comptee — {s['boss_count']} sur ce boss, "
                              f"{s['total']} au total")
                    elif args.debug:
                        print(f"score={detector.last_score:.3f}", end="\r")
                    time.sleep(max(0.0, period - (time.time() - started)))
    except KeyboardInterrupt:
        s = log.snapshot()
        print(f"\nArret. {s['boss_count']} morts sur ce boss, {s['total']} au total.")
    return 0


def _bind_hotkeys(log: DeathLog, debug: bool, detector) -> None:
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


def cmd_diagnose(args) -> int:
    """
    Enregistre ce que le detecteur voit reellement pendant N secondes,
    avec l'image qui a obtenu le meilleur score. Sert a comprendre un
    non-declenchement sans avoir a deviner.
    """
    if not SIGNATURE_PATH.exists():
        print(f"Aucune signature : {SIGNATURE_PATH}. Lance d'abord le setup.")
        return 1

    detector = DeathDetector(SIGNATURE_PATH, DetectorConfig(threshold=args.threshold))
    out_dir = SIGNATURE_PATH.parent / "diagnostic"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Analyse pendant {args.seconds} secondes. Va mourir maintenant.\n")

    best_score, best_band, scores, lumas = -1.0, None, [], []
    period = 1.0 / FPS
    deadline = time.time() + args.seconds

    with mss.mss() as sct:
        monitor = sct.monitors[args.monitor]
        while time.time() < deadline:
            started = time.time()
            frame = grab(sct, monitor)
            score = detector.score(frame)
            scores.append(score)
            lumas.append(float(frame.mean()))
            if score > best_score:
                best_score, best_band = score, crop_band(frame)
            print(f"score={score:.3f}  luminance={lumas[-1]:6.1f}")
            time.sleep(max(0.0, period - (time.time() - started)))

    if best_band is not None:
        imwrite_png(out_dir / "meilleur-score.png", best_band)

    print(f"\nMeilleur score : {best_score:.3f}  (seuil actuel : {args.threshold})")
    print(f"Score median   : {sorted(scores)[len(scores) // 2]:.3f}")
    print(f"Luminance min  : {min(lumas):.1f}   max : {max(lumas):.1f}")
    print(f"\nImages dans : {out_dir}")
    return 0


def cmd_capture(args) -> int:
    """
    Enregistre des frames brutes : plusieurs ecrans de mort, et des moments
    de jeu normal preleves pendant l'attente. Sert a mettre au point la
    detection sur de vraies images plutot que sur des suppositions.
    """
    import keyboard

    out_dir = SIGNATURE_PATH.parent / "echantillons"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.png"):
        old.unlink()

    print(f"Enregistrement dans {out_dir}\n")
    print(f"Il faut {args.deaths} morts, a des endroits differents.")
    print("Appuie sur F8 a chaque fois que le texte de mort est affiche.")
    print("Le jeu normal est echantillonne tout seul entre les morts.\n")

    deaths, ambient = 0, 0
    last_sample = 0.0

    with mss.mss() as sct:
        monitor = sct.monitors[args.monitor]
        while deaths < args.deaths:
            now = time.time()

            if keyboard.is_pressed("esc"):
                print("\nInterrompu.")
                break

            if keyboard.is_pressed("f8"):
                deaths += 1
                imwrite_png(out_dir / f"mort-{deaths}.png",
                            crop_band(grab(sct, monitor)))
                print(f"  mort {deaths}/{args.deaths} enregistree")
                while keyboard.is_pressed("f8"):
                    time.sleep(0.05)
                last_sample = time.time() + 6.0   # laisse l'ecran de mort passer
                continue

            if now - last_sample > args.interval and ambient < args.gameplay:
                ambient += 1
                imwrite_png(out_dir / f"jeu-{ambient:02d}.png",
                            crop_band(grab(sct, monitor)))
                last_sample = now

            time.sleep(0.1)

    print(f"\n{deaths} morts et {ambient} frames de jeu dans :")
    print(f"  {out_dir}")
    print("\nCompresse ce dossier et envoie-le.")
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
        description="Compteur de morts Elden Ring pour OBS et Streamlabs.",
    )
    screen = argparse.ArgumentParser(add_help=False)
    screen.add_argument("--monitor", type=int, default=1,
                        help="ecran a analyser (1 = principal)")

    parser.add_argument("--monitor", type=int, default=None,
                        help=argparse.SUPPRESS)  # accepte avant la sous-commande
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("setup", parents=[screen],
                       help="apprendre a reconnaitre l'ecran de mort")
    p.add_argument("--port", type=int, default=4748,
                   help="port de la page de verification")
    p.add_argument("--no-confirm", action="store_true",
                   help="accepter la zone detectee sans verification")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("run", parents=[screen],
                       help="lancer la detection et l'overlay")
    p.add_argument("--boss", default=None, help="nom du boss affiche")
    p.add_argument("--keep", action="store_true",
                   help="garder le compteur de boss en cours")
    p.add_argument("--port", type=int, default=4747)
    p.add_argument("--threshold", type=float, default=0.55)
    p.add_argument("--confirm", type=int, default=3)
    p.add_argument("--manual", action="store_true",
                   help="ne compter qu'aux raccourcis clavier")
    p.add_argument("--debug", action="store_true",
                   help="afficher le score de correlation en continu")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("diagnose", parents=[screen],
                       help="enregistrer ce que le detecteur voit")
    p.add_argument("--seconds", type=int, default=25)
    p.add_argument("--threshold", type=float, default=0.55)
    p.set_defaults(func=cmd_diagnose)

    p = sub.add_parser("capture", parents=[screen],
                       help="enregistrer des frames brutes pour analyse")
    p.add_argument("--deaths", type=int, default=4)
    p.add_argument("--gameplay", type=int, default=12)
    p.add_argument("--interval", type=float, default=3.0)
    p.set_defaults(func=cmd_capture)

    p = sub.add_parser("boss", help="changer le boss affiche")
    p.add_argument("name")
    p.add_argument("--keep", action="store_true")
    p.set_defaults(func=cmd_boss)

    p = sub.add_parser("history", help="lister les boss vaincus")
    p.set_defaults(func=cmd_history)

    p = sub.add_parser("reset", help="remettre des compteurs a zero")
    p.add_argument("--all", action="store_true",
                   help="effacer aussi le total et l'historique")
    p.set_defaults(func=cmd_reset)

    global_monitor = None
    if "--monitor" in (argv if argv is not None else sys.argv[1:]):
        pre, _ = parser.parse_known_args(argv)
        global_monitor = pre.monitor

    args = parser.parse_args(argv)
    if global_monitor is not None and getattr(args, "monitor", 1) == 1:
        args.monitor = global_monitor
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
