"""2D affine transforms, in PDF's own representation.

A matrix is the six-tuple ``(a, b, c, d, e, f)`` -- the same order and meaning as the
operands of PDF's ``cm`` operator -- and maps a point as::

    x' = a*x + c*y + e
    y' = b*x + d*y + f

These functions back two things at once. Board rendering emits ``cm`` operators into the
PDF content stream, and *in parallel* keeps its own copy of the current transformation
matrix so that stroked geometry can also be recorded in board-grid coordinates for the
exporters, along with the width each stroke was painted at. Both halves compose matrices
the same way, which is why the maths lives here rather than inside either one.
"""

from __future__ import annotations

import math

__all__ = ["IDENTITY", "Matrix", "compose", "apply", "scale_factor", "translation",
           "rotation", "scaling", "FLIP_X", "FLIP_Y"]

Matrix = tuple[float, float, float, float, float, float]

IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
FLIP_X: Matrix = (-1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
FLIP_Y: Matrix = (1.0, 0.0, 0.0, -1.0, 0.0, 0.0)


def compose(m_op: Matrix, top: Matrix) -> Matrix:
    """Compose so a point is transformed by `m_op` *first*, then `top`.

    That order is PDF ``cm`` semantics: a new ``cm`` pre-multiplies the existing CTM, so
    the most recently pushed transform is the one applied nearest the geometry.
    """
    a1, b1, c1, d1, e1, f1 = m_op
    a2, b2, c2, d2, e2, f2 = top
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


def apply(m: Matrix, x: float, y: float) -> tuple[float, float]:
    """Map the point (x, y) through `m`."""
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def scale_factor(m: Matrix) -> float:
    """The uniform scale `m` applies, as the geometric mean of its two axis scales.

    This is how a length carried in one space is measured in another -- a stroke width in
    particular, which PDF resolves against the matrix in effect when the path is painted
    rather than when the width was set, and reduces the same way when the two axes differ.
    """
    a, b, c, d, _e, _f = m
    return math.sqrt(abs(a * d - b * c))


def translation(dx: float, dy: float) -> Matrix:
    return (1.0, 0.0, 0.0, 1.0, dx, dy)


def rotation(cos_t: float, sin_t: float) -> Matrix:
    """A rotation from its cosine and sine, matching the ``cm`` operand layout."""
    return (cos_t, sin_t, -sin_t, cos_t, 0.0, 0.0)


def scaling(sx: float, sy: float) -> Matrix:
    return (sx, 0.0, 0.0, sy, 0.0, 0.0)
