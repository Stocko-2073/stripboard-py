"""Assertion helpers shared across the test suite."""

from __future__ import annotations


def local_pins(component) -> dict[str, tuple[int, int]]:
    """A component's pin holes as offsets from its own origin.

    Builders record pins in *world* coordinates so the renderer and the router share one
    source of truth; footprint assertions want them origin-relative so they stay valid
    wherever the part is placed.
    """
    ox, oy = component.origin
    return {name: (wx - ox, wy - oy) for name, (wx, wy) in component.pins.items()}
