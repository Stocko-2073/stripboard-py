"""Design-rule warnings.

These report mistakes in a *board design* -- the caller's code -- not faults in this
library, which is why they are ``warnings`` rather than log records. A warning is visible
with no configuration, carries the offending source location, can be turned into a hard
error when you want a build to fail::

    python -W error::stripboard.drc.StripboardWarning my_board.py

and is directly assertable in tests with :func:`pytest.warns`. A logger would have been
silent by default, which is the wrong default for a design-rule check.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

__all__ = [
    "StripboardWarning",
    "JumperConflictWarning",
    "ShortCircuitWarning",
    "TraceCollisionWarning",
    "MissingGlyphWarning",
    "warn",
]


class StripboardWarning(UserWarning):
    """Base class for every design-rule warning this library raises."""


class JumperConflictWarning(StripboardWarning):
    """Two jumper ends land in the same hole, which only takes one wire."""


class ShortCircuitWarning(StripboardWarning):
    """A trace reached a hole explicitly marked not-connected with ``nc()``."""


class TraceCollisionWarning(StripboardWarning):
    """Two traced nets met, so they are electrically the same net on the board."""


class MissingGlyphWarning(StripboardWarning):
    """A character has no glyph in the built-in stroke font, so it was not drawn."""


def warn(message: str, category: type[StripboardWarning]) -> None:
    """Raise a design-rule warning, attributed to the board file that caused it.

    The stack level is found rather than hardcoded, because the distance from here to the
    caller differs per call site -- ``jumper()`` detects a conflict one frame deeper than
    ``draw_letter()`` does, and ``text()`` calls the latter from deeper still. Walking out
    to the first frame outside this package reports the board file in every case.
    """
    warnings.warn(message, category, stacklevel=_caller_stacklevel())


def _caller_stacklevel() -> int:
    """Frames from :func:`warn` out to the first one outside this package."""
    package_dir = str(Path(__file__).parent)
    # _getframe(1) is warn() itself, which is stacklevel 1; count outwards from there.
    frame: object | None = sys._getframe(1)
    level = 1
    while frame is not None:
        filename = frame.f_globals.get("__file__", "")
        if not filename.startswith(package_dir):
            return level
        frame = frame.f_back
        level += 1
    return level
