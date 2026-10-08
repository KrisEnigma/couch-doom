from __future__ import annotations

import argparse
import sys
import traceback

from .config import LOG_FILE, STATE_FILE
from .launch import build_command
from .launchers import Launchers
from .options import OptionsError, empty_options
from .sources import KEYS, Choice, plan
from .state import State


def _dry_run(opts, name: str | None) -> int:
    presets = opts.presets
    if name:
        presets = [p for p in presets if name.lower() in p.name.lower()]
        if not presets:
            print(f"No preset matches '{name}'", file=sys.stderr)
            return 1
    if not presets:
        print(f"No presets in {opts.path}", file=sys.stderr)
        return 1
    print(f"{opts.launcher}: {opts.path}\n")
    for p in presets:
        cmd = build_command(opts, p)
        print(f"[{p.section}] {p.name}")
        print(f"  cwd: {cmd.cwd}")
        print(f"  {cmd.display()}")
        for issue in cmd.issues:
            print(f"  ! {issue}")
        print()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="couch-doom", description=__doc__)
    ap.add_argument("--options", help="Launcher settings file: DoomRunner options.json, ZDL qZDL.ini or .zdl, DoomLauncher.sqlite, "
                                       "or a GZDoom/UZDoom/VKDoom program")
    ap.add_argument("--launcher", choices=KEYS, help="Only consider this launcher (default: the saved pick, or ask if several are found)")
    ap.add_argument("--windowed", action="store_true", help="Run in a window instead of fullscreen")
    ap.add_argument("--dry-run", action="store_true", help="Print launch commands and exit")
    ap.add_argument("--preset", help="With --dry-run: only presets whose name contains this text")
    ap.add_argument("--soundfont", help="SoundFont (.sf2/.sf3) for MIDI title music; overrides auto-detection")
    args = ap.parse_args(argv)

    state = State(STATE_FILE)
    explicit = Choice(*plan(args.options, args.launcher)[0]) if args.options else None
    launchers = Launchers(state, args.launcher, explicit)
    choice = launchers.startup()
    # Several launchers and no saved pick: the UI asks; a dry run has no one to ask, so it takes the first.
    pick = launchers.must_pick and not args.dry_run
    if choice is None and args.dry_run and launchers.choices:
        launchers.current = launchers.choices[0]
    try:
        opts, problem = launchers.load(), None
    except OptionsError as exc:
        opts, problem = empty_options(exc.tried[0] if exc.tried else STATE_FILE, exc.launcher), exc
        if not pick:
            # pythonw has no console: the in-app screen explains it, the log keeps it for later.
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            LOG_FILE.write_text(f"{exc.title}\n{exc.detail}\n" + "".join(f"  {p}\n" for p in exc.tried), encoding="utf-8")
    if args.dry_run:
        if problem:
            print(f"{problem.title}. {problem.detail}", file=sys.stderr)
            for p in problem.tried:
                print(f"  {p}", file=sys.stderr)
            return 2
        return _dry_run(opts, args.preset)

    from .ui import App

    app = App(opts, state, windowed=args.windowed, soundfont=args.soundfont, problem=problem, launchers=launchers, pick=pick)
    return app.run()


def _entry() -> int:
    try:
        return main()
    except SystemExit:
        raise
    except Exception:
        # pythonw has no console; keep crashes discoverable.
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOG_FILE.write_text(traceback.format_exc(), encoding="utf-8")
        raise


if __name__ == "__main__":
    sys.exit(_entry())
