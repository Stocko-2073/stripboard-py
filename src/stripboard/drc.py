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

import warnings

__all__ = [
    "StripboardWarning",
    "JumperConflictWarning",
    "ShortCircuitWarning",
    "TraceCollisionWarning",
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


def warn(message: str, category: type[StripboardWarning]) -> None:
    """Raise a design-rule warning, attributed to the board file that caused it.

    ``stacklevel=3`` steps out of this function and out of the library method that
    detected the problem, so the reported location is the caller's ``draw()``.
    """
    warnings.warn(message, category, stacklevel=3)
