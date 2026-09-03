"""Command line entry point: ``stripboard``.

Three subcommands, replacing the shell scripts this project used to carry:

* ``new``   scaffold a board file in the current directory
* ``build`` run a board file, optionally rasterize and open the PDF
* ``watch`` re-run a board file whenever it changes

Everything is stdlib and cross-platform. Rasterizing needs ``pdftoppm`` (poppler) and is
skipped with a note when it is absent.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from importlib.resources import files
from pathlib import Path
from string import Template

__all__ = ["main"]

NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _template() -> Template:
    text = (files("stripboard.templates") / "board.py.tmpl").read_text(encoding="utf-8")
    return Template(text)


def _title(name: str) -> str:
    """A human title for the board: upper case, separators turned into spaces."""
    return re.sub(r"\s+", " ", name.upper().replace("-", " ").replace("_", " ")).strip()


def cmd_new(args: argparse.Namespace) -> int:
    if not NAME_RE.match(args.name):
        print(f"error: name may contain only letters, digits, '-' or '_' "
              f"(got: {args.name!r})", file=sys.stderr)
        return 2

    # A hyphen is fine in a board name but not in a module name, and the output stem
    # follows the file so `new foo-bar` gives foo_bar.py -> foo_bar.pdf.
    stem = args.name.replace("-", "_")
    out_dir = Path(args.outdir)
    target = out_dir / f"{stem}.py"
    if target.exists():
        print(f"error: {target} already exists -- refusing to overwrite.", file=sys.stderr)
        return 1

    body = _template().substitute(
        title=_title(args.name),
        name=stem,
        filename=target.name,
        width=args.width,
        height=args.height,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")

    print(f"created {target}")
    print("next:")
    print(f"  1. set width/height and fill in draw() in {target}")
    print(f"  2. python {target}  -- writes {stem}.pdf")
    print("  3. flip designing = False in that file for the FRONT/BACK/DESIGN build sheet")
    return 0


def _open_file(path: Path) -> None:
    """Open `path` in the platform's default viewer, quietly doing nothing if we can't."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        elif os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except OSError as exc:
        print(f"note: could not open {path}: {exc}", file=sys.stderr)


def _render(script: Path) -> int:
    """Run a board script as its own program, in its own directory."""
    proc = subprocess.run([sys.executable, str(script.resolve())], cwd=script.parent)
    return proc.returncode


def cmd_build(args: argparse.Namespace) -> int:
    script = Path(args.file)
    if not script.is_file():
        print(f"error: no such board file: {script}", file=sys.stderr)
        return 2

    rc = _render(script)
    if rc != 0:
        return rc

    pdf = script.parent / f"{script.stem}.pdf"
    if not pdf.exists():
        # A board may name its output differently from its file; that is not an error.
        print(f"note: {pdf.name} not found -- check the name= passed to project()")
        return 0

    if args.png:
        if shutil.which("pdftoppm"):
            subprocess.run(["pdftoppm", "-png", "-r", str(args.dpi), "-singlefile",
                            str(pdf), str(pdf.with_suffix(""))], check=False)
            print(f"wrote {pdf.with_suffix('.png').name}")
        else:
            print("note: pdftoppm not found (install poppler) -- skipping --png",
                  file=sys.stderr)
    if args.open:
        _open_file(pdf)
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    script = Path(args.file)
    if not script.is_file():
        print(f"error: no such board file: {script}", file=sys.stderr)
        return 2

    print(f"watching {script} -- Ctrl-C to stop")
    last = 0.0
    try:
        while True:
            try:
                stamp = script.stat().st_mtime
            except FileNotFoundError:
                time.sleep(args.interval)
                continue
            if stamp != last:
                last = stamp
                print(f"\n--- {time.strftime('%H:%M:%S')} rebuilding ---")
                _render(script)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nstopped")
        return 0


def build_parser() -> argparse.ArgumentParser:
    from . import __version__

    ap = argparse.ArgumentParser(prog="stripboard", description=__doc__.splitlines()[0])
    ap.add_argument("--version", action="version", version=f"stripboard {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new", help="scaffold a new board file")
    new.add_argument("name", help="board name (letters, digits, '-' and '_')")
    new.add_argument("--width", type=int, default=18, help="board columns (default: 18)")
    new.add_argument("--height", default="Z",
                     help="board rows, a letter or an int (default: Z)")
    new.add_argument("-o", "--outdir", default=".", help="where to write it (default: .)")
    new.set_defaults(func=cmd_new)

    build = sub.add_parser("build", help="render a board file")
    build.add_argument("file", help="the board .py file")
    build.add_argument("--png", action="store_true", help="also rasterize via pdftoppm")
    build.add_argument("--dpi", type=int, default=300, help="--png resolution (default: 300)")
    build.add_argument("--open", action="store_true", help="open the PDF when done")
    build.set_defaults(func=cmd_build)

    watch = sub.add_parser("watch", help="re-render a board file whenever it changes")
    watch.add_argument("file", help="the board .py file")
    watch.add_argument("--interval", type=float, default=0.5,
                       help="poll interval in seconds (default: 0.5)")
    watch.set_defaults(func=cmd_watch)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
