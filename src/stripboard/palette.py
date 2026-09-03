"""Colour tables.

``COLORS`` cycles through visually distinct hues for successive traced nets.
``WIRE_COLORS`` maps the jumper colour names board files use, plus their single-letter
shorthands -- so ``color='k'`` and ``color='black'`` are the same wire.
"""

from __future__ import annotations

__all__ = ["COLORS", "WIRE_COLORS"]

# Trace colours, cycled per net by trace().
COLORS: list[tuple[int, int, int]] = [
    (255, 0, 0),
    (0, 0, 255),
    (0, 255, 0),
    (0, 255, 255),
    (220, 220, 0),
    (255, 0, 255),
    (64, 0, 255),
    (128, 255, 0),
    (128, 128, 128),
    (255, 0, 128),
    (128, 0, 255),
    (0, 96, 0),
    (0, 0, 96)
]

# Jumper wire colours, keyed by full name and by single-char shorthand.
WIRE_COLORS: dict[str, tuple[int, int, int]] = {
    'blue':   (16, 128, 255), 'b': (16, 128, 255),
    'white':  (192, 192, 192), 'w': (192, 192, 192),
    'red':    (255, 0, 0),     'r': (255, 0, 0),
    'green':  (16, 180, 16),   'g': (16, 180, 16),
    'black':  (0, 0, 0),       'k': (0, 0, 0),
    'yellow': (200, 160, 0),   'y': (200, 170, 0),
}
