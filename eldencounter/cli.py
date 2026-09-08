"""Point d'entree en ligne de commande."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import mss

from .counter import DEFAULT_STATE_PATH, DeathLog
from .detector import DeathDetector, DetectorConfig, capture_template, grab
from .server import serve

TEMPLATE_PATH = DEFAULT_STATE_PATH.parent / "template.png"
FPS = 4


def cmd_setup(args) -> int:
    with mss.mss() as sct:
        for i, m in enumerate(sct.monitors[1:], start=1):
            marker = "  <-- selectionne" if i == args.monitor else ""
            print(f"Ecran {i} : {m['width']}x{m['height']}{marker}")
        print()

    try:
        capture_template(args.monitor, TEMPLATE_PATH)
    except KeyboardInterrupt:
        print("\nSetup annule.")
        return 1
    print("\nC'est pret. Lance maintenant : elden-counter run")
    return 0


def cmd_run(args) -> int:
    if not TEMPLATE_PATH.exists():
        print(f"Aucun template a l'emplacement attendu : {TEMPLATE_PATH}")
        print("Lance d'abord : elden-counter setup")
        return 1

    log = DeathLog()
    if args.boss:
        log.set_boss(args.boss, keep_count=args.keep)

    detector = DeathDetector(
        TEMPLATE_PATH,
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
    with mss.mss() as sct:
        monitor = sct.monitors[args.monitor]
        try:
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
                       help="capturer l'image de reference de l'ecran de mort")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("run", parents=[screen],
                       help="lancer la detection et l'overlay")
    p.add_argument("--boss", default=None, help="nom du boss affiche")
    p.add_argument("--keep", action="store_true",
                   help="garder le compteur de boss en cours")
    p.add_argument("--port", type=int, default=4747)
    p.add_argument("--threshold", type=float, default=0.72)
    p.add_argument("--confirm", type=int, default=3)
    p.add_argument("--debug", action="store_true",
                   help="afficher le score de correlation en continu")
    p.set_defaults(func=cmd_run)

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
