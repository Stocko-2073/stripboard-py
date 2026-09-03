"""Metadata-insensitive PDF equality: strip the varying /CreationDate, then hash/diff.

Usage:
  python pdfcmp.py hash  <a.pdf> [b.pdf ...]     # print normalized sha1 of each
  python pdfcmp.py diff  <a.pdf> <b.pdf>          # exit 0 if drawing-identical
"""
import hashlib
import re
import sys

_DATE = re.compile(rb"/CreationDate\s*\([^)]*\)")


def norm(path):
    data = open(path, "rb").read()
    return _DATE.sub(b"/CreationDate ()", data)


def sha(path):
    return hashlib.sha1(norm(path)).hexdigest()


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "hash":
        for p in sys.argv[2:]:
            print(f"{sha(p)}  {p}")
    elif mode == "diff":
        a, b = sys.argv[2], sys.argv[3]
        if norm(a) == norm(b):
            print(f"IDENTICAL  {a} == {b}")
            sys.exit(0)
        print(f"DIFFER     {a} != {b}  ({sha(a)} vs {sha(b)})")
        sys.exit(1)
