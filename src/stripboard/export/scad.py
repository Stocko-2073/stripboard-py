"""The OpenSCAD board label: the LABEL silkscreen as a two-colour 3D print.

Where the g-code exporter hands the silkscreen to a laser, this hands it to a printer. A
laser draws a line of no width at any scale; a nozzle lays a bead, so the artwork is
redrawn at one bead per stroke and strokes too thin to be a bead are dropped rather than
fattened. The result is two solids -- a plate and the artwork standing on it -- because a
slicer needs one body per filament.

Geometry comes from the stroke capture, and specifically from the widths recorded beside
it: nothing else distinguishes lettering from the hairline that stands for a wire.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .. import transform

if TYPE_CHECKING:
    # Resolves the state and sibling methods every mixin shares; see _state.py. At
    # runtime the base is `object`, so the MRO is unchanged.
    from .._state import BoardState as _Base
else:
    _Base = object

__all__ = ["ScadMixin"]

# The static half of the emitted file. Segments are built by a `for` over the path vector
# rather than emitted one `hull()` at a time: a plain label runs to a few hundred segments
# and a crowded one to thousands, and a loop keeps the file readable at any size. The
# boolean work stays 2D under a single `linear_extrude`, which is the cheap arrangement,
# and the pins are subtracted from both bodies so a lead passes through the whole stack.
_MODULES = """\
module label_pins() {
    for (h = holes)
        translate(h) circle(d = hole_d, $fn = facets);
}

module label_base() {
    linear_extrude(height = base_h)
        difference() {
            square([label_w, label_h]);
            label_pins();
        }
}

module label_traces() {
    translate([0, 0, base_h])
        linear_extrude(height = trace_h)
            difference() {
                intersection() {
                    union() {
                        for (p = paths)
                            for (i = [0 : len(p) - 2])
                                hull() {
                                    translate(p[i])     circle(d = nozzle, $fn = facets);
                                    translate(p[i + 1]) circle(d = nozzle, $fn = facets);
                                }
                    }
                    // Nothing may overhang the plate: it would print into thin air.
                    square([label_w, label_h]);
                }
                label_pins();
            }
}

if (part == "all" || part == "base")   label_base();
if (part == "all" || part == "traces") label_traces();
"""


class ScadMixin(_Base):
    def gen_scad(self, name, *, pitch_mm=2.54, nozzle_mm=0.4, min_stroke_mm=0.35,
                 hole_mm=1.2, base_mm=0.6, trace_mm=0.4, facets=10):
        """Write the captured LABEL strokes as an OpenSCAD board label to `name`.

        Two modules for a two-filament print: ``label_base()`` is a plate the size of the
        board and ``label_traces()`` stands on it, every stroke traced round-capped at
        `nozzle_mm`. A `part` parameter in the emitted file selects one body at a time, so
        each can be rendered to its own STL.

        Strokes narrower than `min_stroke_mm` are dropped, which is what keeps the hairline
        a black-and-white ``jumper()`` draws to stand for a wire from printing as artwork.
        The width consulted is the one PDF strokes with, resolved through the transform
        that positioned the geometry, so text shrunk by ``x_scale`` or a footprint's
        ``label_scale`` measures narrower than the same glyph at full size and drops out
        first: at the default cutoff a pin name set at 0.78 scale does not print. Lower
        `min_stroke_mm` to keep it -- 0.25 keeps every glyph the shipped examples draw
        while still dropping the hairlines. The count that went is on the summary line and
        in the file's own header, so it is never silent.

        Every part pin and every wire end is punched through both bodies at `hole_mm` so
        the leads still pass. Those come from the marks the footprints draw -- ``dot()``
        for a pin, ``jdot()`` for a wire end -- rather than from the netlist, because
        better than half the part builders draw pins without registering a component and
        a netlist would miss them. Cuts are not punched: a cut takes its hole with it and
        no lead goes through. Neither is ``drill()``, which marks its hole with neither,
        so its ring prints as artwork.

        The plate is the board outline, ``(board_width + 1) x (board_height + 1)`` holes
        at `pitch_mm`, taken from the board's own size and frame rather than from the
        stroke bounding box -- a title drawn off the board must not move the plate out
        from under the holes. Consumes the capture of a single view; see
        :func:`_scad_render`.
        """
        self._cap_bbox("gen_scad")  # for its error alone, when nothing was captured

        frame = self._cap_board
        corners = [transform.apply(frame, x, y)
                   for x, y in ((0, 0), (self.board_width + 1, 0),
                                (self.board_width + 1, self.board_height + 1),
                                (0, self.board_height + 1))]
        xs = [x for x, _ in corners]
        ys = [y for _, y in corners]
        x0, y1 = min(xs), max(ys)
        # The outline stroke is centred on the board edge, so half a bead of it falls
        # outside. The plate carries that half bead as a margin, which is what keeps the
        # border printable: clipped to the board exactly, it would come out half width.
        margin = nozzle_mm / 2
        label_w = (max(xs) - x0) * pitch_mm + nozzle_mm
        label_h = (y1 - min(ys)) * pitch_mm + nozzle_mm

        def to_mm(pt):
            # Grid rows run top->down and OpenSCAD Y runs bottom->up, so Y inverts.
            return ((pt[0] - x0) * pitch_mm + margin, (y1 - pt[1]) * pitch_mm + margin)

        kept = [p for p, w in zip(self._cap_paths, self._cap_widths, strict=True)
                if w * pitch_mm >= min_stroke_mm]
        skipped = len(self._cap_paths) - len(kept)

        # Dedup at micron scale: a wire end lands on a pin, and a link marks both.
        hole_mm_pts = sorted({(round(x, 3), round(y, 3))
                              for x, y in map(to_mm, self._cap_holes)})

        def vec(pt):
            x, y = pt
            return f"[{x:.3f}, {y:.3f}]"

        segments = sum(len(p) - 1 for p in kept)
        lines = [
            "// OpenSCAD board label generated by stripboard.",
            f"// {len(kept)} traces in {segments} segments, {len(hole_mm_pts)} pin holes, "
            f"{label_w:.1f} x {label_h:.1f} mm"
            + (f"; {skipped} strokes thinner than {min_stroke_mm} mm skipped."
               if skipped else "."),
            "// Two bodies for a two-filament print. Render one at a time with",
            f'//   openscad -D \'part="base"\' -o base.stl {Path(name).name}',
            "",
            'part    = "all";     // "all", "base" or "traces"',
            f"nozzle  = {nozzle_mm:.3f};     // trace width (mm): one nozzle bead",
            f"hole_d  = {hole_mm:.3f};     // pin hole diameter (mm)",
            f"base_h  = {base_mm:.3f};     // plate thickness (mm)",
            f"trace_h = {trace_mm:.3f};     // trace height above the plate (mm)",
            f"label_w = {label_w:.3f};    // plate width (mm)",
            f"label_h = {label_h:.3f};    // plate height (mm)",
            f"facets  = {facets};        // facets per round cap and per hole",
            "",
            "holes = [",
        ]
        lines += [f"    {vec(pt)}," for pt in hole_mm_pts]
        lines += ["];", "", "paths = ["]
        lines += [f"    [{', '.join(vec(to_mm(pt)) for pt in p)}]," for p in kept]
        lines += ["];", ""]
        lines += _MODULES.splitlines()

        target = Path(name)
        if target.parent != Path():
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {name}: {len(kept)} traces, {len(hole_mm_pts)} holes, "
              f"{label_w:.1f} x {label_h:.1f} mm, {skipped} thin strokes skipped")
