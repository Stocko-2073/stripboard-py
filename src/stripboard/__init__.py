"""Design stripboard (protoboard) circuit layouts in Python.

Write a ``draw(sb)`` function that places components on the hole grid and either routes
them by hand (``jumper``/``cut``/``trace``) or declares a netlist and calls
``autoroute()``; then hand it to :func:`project`, which renders the board PDF and any
label, laser g-code or carrier you ask for::

    from stripboard import project

    def draw(sb):
        sb.text(1, 'A', 'HELLO')
        sb.led(4, 'C')

    project(draw, name='hello', width=12, height='K')

Coordinates are a 1-based integer grid: columns are numbers along ``x``, rows are letters
(``'A'`` == 1 ... ``'Z'`` == 26) or ints along ``y``. Copper strips run horizontally, so
two pins on the same row start out connected -- deciding where to break that is most of
the design work.

The package has no third-party dependencies: the PDF writer (:mod:`stripboard.pdf`) and
the autorouter (:mod:`stripboard.router`) both ship with it.
"""

from __future__ import annotations

from .board import StripBoard
from .component import Component
from .drc import (
    JumperConflictWarning,
    MissingGlyphWarning,
    ShortCircuitWarning,
    StripboardWarning,
    TraceCollisionWarning,
)
from .geometry import parse_row
from .project import project

# The single source of truth for the version; pyproject.toml reads it from here.
__version__ = "0.1.1"

__all__ = [
    "StripBoard",
    "Component",
    "project",
    "parse_row",
    "StripboardWarning",
    "JumperConflictWarning",
    "MissingGlyphWarning",
    "ShortCircuitWarning",
    "TraceCollisionWarning",
    "__version__",
]
