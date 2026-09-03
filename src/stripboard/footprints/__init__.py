"""Component footprints.

A footprint knows two things: how to draw the part, and where its pins land on the hole
grid. The second is what the autorouter consumes, so builders return a
:class:`stripboard.Component` handle carrying pin positions in world coordinates plus any
keep-out rectangles the part's body imposes.

The mixins are grouped by kind purely for navigability; `FootprintsMixin` recombines
them, and `StripBoard` exposes every builder as a method.
"""

from __future__ import annotations

from .connectors import ConnectorsMixin
from .controls import ControlsMixin
from .ics import IcsMixin
from .modules import ModulesMixin
from .passives import PassivesMixin

__all__ = ["FootprintsMixin"]


class FootprintsMixin(
    PassivesMixin,
    IcsMixin,
    ModulesMixin,
    ConnectorsMixin,
    ControlsMixin,
):
    """Every part builder, gathered from the per-kind mixins."""
