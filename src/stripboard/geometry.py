"""Grid geometry shared across the package.

Boards use a 1-based integer hole grid. Rows may be written as letters (``'A'`` == 1 ...
``'Z'`` == 26) or as plain ints, and both spellings have to agree everywhere, so the
coercion lives in one place.
"""

from __future__ import annotations

__all__ = ["KAPPA", "parse_row"]

# Bezier control-point ratio for approximating a quarter circle: 4 * ((sqrt(2) - 1) / 3).
KAPPA = 0.5522848


def parse_row(y):
    """Coerce a row given as a letter (``'A'`` -> 1) or an int (``1`` -> 1) to an int.

    Idempotent, because it is applied at several layers on the way down.
    """
    return ord(y) - 64 if isinstance(y, str) else y
