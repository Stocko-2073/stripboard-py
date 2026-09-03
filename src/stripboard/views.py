"""The four canonical board views.

A board gets drawn more than once, because building one means looking at it from both
sides. Each preset is the set of ``show_*`` toggles that
:meth:`stripboard.StripBoard.begin_view` hands to ``begin_board``:

* ``FRONT``  -- component side, as you place parts
* ``BACK``   -- copper side, mirrored, as you cut tracks and solder
* ``DESIGN`` -- everything on, with nets flood-filled in colour to check connectivity
* ``LABEL``  -- the silkscreen alone, for printing or laser etching
"""

from __future__ import annotations

__all__ = ["VIEW_PRESETS"]

VIEW_PRESETS: dict[str, dict[str, bool]] = {
    'FRONT':  dict(show_strips=False, show_traces=False, show_crosses=False),
    'BACK':   dict(flip_x=True, show_strips=True, show_traces=False, show_crosses=True,
                   show_components=False, show_jumpers=False),
    'DESIGN': dict(show_strips=True, show_traces=True),
    'LABEL':  dict(show_strips=False, show_traces=False, show_crosses=False,
                   show_coordinates=False),
}
