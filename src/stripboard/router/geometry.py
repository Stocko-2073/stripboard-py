"""Spatial primitives: points, rectangles, the 180-degree flip, and helpers.

The layout space is a 2D integer grid. Coordinates are 1-based with the board origin
at ``(1, 1)`` (see spec section 1), but nothing in this module assumes a particular
origin -- these are pure geometry helpers. Distances are Manhattan.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

Point = tuple[int, int]


def manhattan(a: Point, b: Point) -> int:
    """Manhattan distance ``|x1-x2| + |y1-y2|`` (spec section 1)."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def flip_point(p: Point) -> Point:
    """180-degree rotation of a local offset about the origin: ``(dx, dy) -> (-dx, -dy)``.

    This is an involution: ``flip_point(flip_point(p)) == p`` (spec section 2.3).
    """
    return (-p[0], -p[1])


def in_bounds(p: Point, w: int, h: int) -> bool:
    """True iff ``1 <= x <= w`` and ``1 <= y <= h`` (spec section 1)."""
    x, y = p
    return 1 <= x <= w and 1 <= y <= h


@dataclass(frozen=True)
class Rect:
    """An inclusive, axis-aligned rectangle ``[x0, x1] x [y0, y1]``.

    Always normalized so ``x0 <= x1`` and ``y0 <= y1``. Construct via :meth:`of` (or the
    constructor directly with already-ordered corners); ``__post_init__`` enforces the
    ordering rather than silently accepting a reversed rectangle.
    """

    x0: int
    y0: int
    x1: int
    y1: int

    def __post_init__(self) -> None:
        if self.x0 > self.x1 or self.y0 > self.y1:
            raise ValueError(
                f"Rect corners must be ordered (x0<=x1, y0<=y1); got {self!r}. "
                "Use Rect.of() to normalize arbitrary corners."
            )

    @classmethod
    def of(cls, ax: int, ay: int, bx: int, by: int) -> Rect:
        """Build a normalized rectangle from two arbitrary corners."""
        return cls(min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))

    def points(self) -> Iterator[Point]:
        """Yield every integer point inside the (inclusive) rectangle."""
        for y in range(self.y0, self.y1 + 1):
            for x in range(self.x0, self.x1 + 1):
                yield (x, y)

    def flip(self) -> Rect:
        """180-degree rotation about the origin: ``[x0,x1]x[y0,y1] -> [-x1,-x0]x[-y1,-y0]``.

        An involution, like :func:`flip_point` (spec section 2.3).
        """
        return Rect(-self.x1, -self.y1, -self.x0, -self.y0)

    def translate(self, dx: int, dy: int) -> Rect:
        """Shift the rectangle by ``(dx, dy)``."""
        return Rect(self.x0 + dx, self.y0 + dy, self.x1 + dx, self.y1 + dy)

    def contains(self, p: Point) -> bool:
        x, y = p
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1

    def on_board(self, w: int, h: int) -> bool:
        """True iff the whole rectangle lies within a ``w x h`` board."""
        return in_bounds((self.x0, self.y0), w, h) and in_bounds((self.x1, self.y1), w, h)


def parse_row(y: int | str) -> int:
    """Resolve a row given as an int or a letter alias (``A=1 ... Z=26``).

    The wider stripboard tooling addresses rows by letter; the input layer accepts
    either form. Multi-character strings that are all digits are parsed as ints.
    """
    if isinstance(y, int):
        return y
    s = y.strip()
    if len(s) == 1 and s.isalpha():
        return ord(s.upper()) - ord("A") + 1
    if s.lstrip("-").isdigit():
        return int(s)
    raise ValueError(f"Cannot parse row {y!r}: expected an int or a single letter A-Z.")
