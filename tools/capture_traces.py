#!/usr/bin/env python3
"""Capture normalized render traces for a directory of board scripts.

The refactor's safety net. Board designs are run as subprocesses in a scratch directory,
and every artifact they emit is reduced to a *normalized trace*: for a PDF, the
concatenated page content streams (every drawing operator, colour change and transform,
in order) with all document structure and metadata stripped; for g-code and SVG, the text
verbatim.

That choice is deliberate. Replacing the PDF backend legitimately changes the document
*structure* (object numbering, xref offsets, ``/Producer``, ``/CreationDate``) while the
rendered *content* must not change at all, so comparing content streams isolates exactly
the thing under test and stays diffable by eye.

Usage:

    # baseline, from the pre-refactor tree (its own venv has fpdf installed)
    python tools/capture_traces.py --boards ../stripboard \
        --python ../stripboard/venv/bin/python --libpath ../stripboard \
        --out .regression/before

    # after a refactor step, against the installed package
    python tools/capture_traces.py --boards ../stripboard --out .regression/after
    diff -r .regression/before .regression/after

``--boards`` may point at private board designs; nothing it produces is ever committed
(`.regression/` is gitignored).
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# fpdf and our own writer both frame content streams as "stream\n<body>\nendstream".
_STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.DOTALL)

TEXT_SUFFIXES = {".nc", ".svg", ".scad"}
BINARY_SUFFIXES = {".stl"}


def pdf_trace(data: bytes) -> str:
    """Reduce a PDF to its page content streams, dropping structure and metadata."""
    streams = [m.group(1) for m in _STREAM.finditer(data)]
    if not streams:
        raise ValueError("no content streams found -- is the PDF compressed?")
    parts = []
    for i, s in enumerate(streams, 1):
        # Newlines at the stream boundary are normalized away: they are whitespace as far
        # as PDF is concerned, and different writers frame the stream differently (PyFPDF
        # emitted one extra before `endstream`). Everything between is compared exactly.
        body = s.decode("latin-1").replace("\r\n", "\n").strip("\n")
        parts.append(f"%%% stream {i} ({len(body)} chars)\n{body}")
    return "\n".join(parts) + "\n"


def artifact_trace(path: Path) -> str | None:
    """Normalized trace for one produced artifact, or None if it isn't comparable."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return pdf_trace(path.read_bytes())
    if suffix in TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix in BINARY_SUFFIXES:
        # STLs come from an external openscad run; record only size so a missing
        # openscad shows up as a difference rather than a crash.
        return f"%%% binary artifact, {path.stat().st_size} bytes\n"
    return None


def board_scripts(boards: Path) -> list[Path]:
    """Board design scripts in `boards`: top-level .py files that drive the library."""
    found = []
    for p in sorted(boards.glob("*.py")):
        if p.name in {"stripboard.py", "conftest.py"} or p.name.startswith("test_"):
            continue
        src = p.read_text(encoding="utf-8", errors="replace")
        if re.search(r"^\s*from\s+stripboard\s+import|^\s*import\s+stripboard", src, re.M):
            found.append(p)
    return found


def variants(src: str) -> dict[str, str]:
    """The script as written, plus a build-mode twin if it has a `designing` toggle.

    Board files gate the fast one-page DESIGN preview against the full FRONT/BACK/DESIGN
    build sheet (plus label and carrier) with a module-level `designing` flag. Rendering
    both doubles the operator coverage of the trace for free.
    """
    out = {"": src}
    flipped, n = re.subn(r"(?m)^designing\s*=\s*(True|False)\s*$",
                         lambda m: f"designing = {'False' if m.group(1) == 'True' else 'True'}",
                         src, count=1)
    if n:
        out["__flipped"] = flipped
    return out


def run_variant(script: Path, source: str, suffix: str, python: str,
                libpath: str | None, out_dir: Path, timeout: int) -> tuple[int, str]:
    """Run one board variant in a scratch CWD and write its traces into `out_dir`."""
    stem = script.stem + suffix
    with tempfile.TemporaryDirectory(prefix="sbtrace-") as tmp:
        work = Path(tmp)
        target = work / f"{stem}.py"
        target.write_text(source, encoding="utf-8")

        env = dict(os.environ)
        # sys.path[0] is the script's own directory (the scratch dir), so an installed
        # `stripboard` wins unless --libpath points at a checkout to test instead.
        env["PYTHONPATH"] = libpath if libpath else ""
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        proc = subprocess.run([python, str(target)], cwd=work, env=env,
                              capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
            return 0, f"FAILED rc={proc.returncode}: {' | '.join(tail)}"

        written = 0
        for produced in sorted(work.rglob("*")):
            if not produced.is_file() or produced == target:
                continue
            try:
                trace = artifact_trace(produced)
            except ValueError as exc:
                return written, f"FAILED {produced.name}: {exc}"
            if trace is None:
                continue
            # Name the trace after the artifact, not the script: one board can emit a
            # board PDF, a label PDF, a .nc and an .stl, and they must not collide.
            dest = out_dir / f"{stem}--{produced.name}.trace"
            dest.write_text(trace, encoding="utf-8")
            written += 1
        return written, "ok" if written else "no comparable artifacts"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--boards", required=True, type=Path,
                    help="directory of board design scripts to render")
    ap.add_argument("--out", required=True, type=Path, help="directory to write traces into")
    ap.add_argument("--python", default=sys.executable,
                    help="interpreter to run the boards with (default: this one)")
    ap.add_argument("--libpath", default=None,
                    help="prepend to PYTHONPATH, to render against a checkout instead of "
                         "the installed package")
    ap.add_argument("--timeout", type=int, default=900, help="per-variant timeout in seconds")
    ap.add_argument("--only", default=None, help="only boards whose stem contains this")
    args = ap.parse_args(argv)

    # Boards run with cwd set to a scratch directory, so every path handed to the
    # subprocess has to be absolute before we get there. Use abspath, not resolve():
    # a venv's bin/python is a symlink to the base interpreter, and following it would
    # bypass the venv and its installed packages entirely.
    args.boards = Path(os.path.abspath(args.boards))
    args.python = os.path.abspath(args.python)
    if args.libpath:
        args.libpath = os.path.abspath(args.libpath)

    scripts = board_scripts(args.boards)
    if args.only:
        scripts = [s for s in scripts if args.only in s.stem]
    if not scripts:
        print(f"no board scripts found in {args.boards}", file=sys.stderr)
        return 1

    if args.out.exists():
        shutil.rmtree(args.out)
    args.out.mkdir(parents=True)

    total, failures = 0, []
    for script in scripts:
        src = script.read_text(encoding="utf-8", errors="replace")
        for suffix, source in variants(src).items():
            label = script.stem + suffix
            try:
                n, status = run_variant(script, source, suffix, args.python,
                                        args.libpath, args.out, args.timeout)
            except subprocess.TimeoutExpired:
                n, status = 0, f"FAILED timeout after {args.timeout}s"
            total += n
            if status.startswith("FAILED"):
                failures.append(f"{label}: {status}")
            print(f"  {label:<34} {n:>2} traces  {status}", flush=True)

    print(f"\n{total} traces written to {args.out}")
    if failures:
        print(f"{len(failures)} variant(s) did not render:", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
