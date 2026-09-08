"""The OpenSCAD board label, as a two-colour 3D print.

Where the g-code exporter hands the silkscreen to a laser, this hands it to a printer, and
a printer needs the artwork as *area* rather than as centrelines. So this exporter consumes
the ink capture -- every shape the renderer painted, in the order it painted them, with its
colour -- rather than the stroke capture the laser uses.

Colour is what makes that necessary. The renderer draws a glyph by filling a box in the
opposite colour and stroking the glyph over it, so white is how it erases: a point is inked
when the last shape covering it was black. Reproducing that gives the filled bodies and the
knocked-out lettering the printed label has, and it is why each black shape is emitted less
the white shapes painted after it.

The two bodies share one surface. The artwork is inlaid into the plate rather than standing
on it -- the plate carries a pocket the traces drop into, both flush at the top -- because
that is what a multi-material printer wants: one solid per filament, meeting on a plane.
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

# The static half of the emitted file. A stroke becomes a run of round-capped segments,
# which is what matches the renderer's own round caps and joins; a fill is its polygon.
# Shapes are indexed so the ink structure below can reference them without repeating
# coordinates, and `for` is an implicit union so one linear_extrude covers the lot.
_MODULES = """\
module shape(i) {
    s = shapes[i];
    if (s[0] == 0)
        polygon(s[1]);
    else
        for (k = [0 : len(s[1]) - 2])
            hull() {
                translate(s[1][k])     circle(d = nozzle, $fn = facets);
                translate(s[1][k + 1]) circle(d = nozzle, $fn = facets);
            }
}

module lead_holes() {
    for (h = holes)
        translate(h) circle(d = hole_d, $fn = facets);
}

module inlay(extra) {
    translate([0, 0, plate_h - inlay_h])
        linear_extrude(height = inlay_h + extra)
            difference() {
                intersection() {
                    ink();
                    square(plate);
                }
                lead_holes();
            }
}

module label_plate() {
    difference() {
        linear_extrude(height = plate_h)
            difference() {
                square(plate);
                lead_holes();
            }
        inlay(1);
    }
}

module label_traces() {
    inlay(0);
}

if (part == "all" || part == "plate")  label_plate();
if (part == "all" || part == "traces") label_traces();
"""


class ScadMixin(_Base):
    def gen_scad(self, name, *, pitch_mm=2.54, nozzle_mm=0.4, min_stroke_mm=0.0,
                 min_fill_mm=0.3, hole_mm=1.2, plate_mm=1.0, inlay_mm=0.4, facets=10):
        """Write the captured LABEL artwork as an OpenSCAD board label to `name`.

        Two bodies for a two-filament print, meeting flush at the top face:
        ``label_plate()`` is a plate the size of the board with the artwork cut out of it
        as a pocket `inlay_mm` deep, and ``label_traces()`` is the artwork that drops into
        that pocket. A `part` parameter in the emitted file selects one at a time, so each
        can be rendered to its own STL.

        The artwork is what the label view *paints*, so filled component bodies and
        knocked-out lettering come through as they appear on the page, not merely as
        outlines. Every stroke is redrawn `nozzle_mm` wide -- a printer lays a bead of one
        width whatever the page used -- so jumper wires and lettering come out the same
        weight. `min_stroke_mm` and `min_fill_mm` drop anything too small to print, which
        is how the hole stipple stays out of the model; both count in millimetres, and the
        counts dropped are on the summary line and in the file's own header.

        `plate_mm` is the board's thickness and `inlay_mm` how deep the artwork sits below
        its top face; both reach the emitted file as named parameters, so they can be tried
        at other values without exporting again. A lead has to clear this label *and* the
        protoboard beneath it, so thinner is better, and `inlay_mm` equal to `plate_mm`
        carries the artwork the whole way through -- the thinnest a two-colour label can be.

        Every part pin and wire end is drilled through both bodies at `hole_mm` so the
        leads still pass. Those come from the marks the footprints draw -- ``dot()`` for a
        pin, ``jdot()`` for a wire end -- rather than from the netlist, because better than
        half the part builders draw pins without registering a component. Cuts are not
        drilled: a cut takes its hole with it and no lead goes through. The pad the
        footprint draws around a pin is left out of the artwork: it is a ring very nearly
        the width of the hole itself, so it asks for a bead thinner than a nozzle can lay,
        and the hole alone reads the same.

        The plate is the board outline, ``(board_width + 1) x (board_height + 1)`` holes at
        `pitch_mm`, taken from the board's own size and frame rather than from the painted
        extent -- artwork drawn off the board must not move the plate out from under the
        holes, and is clipped to it instead. The frame the renderer drew around the board is
        left out: a printed label is already cut to that edge. Consumes the capture of a
        single view; see :func:`_scad_render`.
        """
        if not self._cap_ink:
            raise ValueError("gen_scad: no captured geometry -- "
                             "render a view with _cap_on=True first (see _scad_render).")
        if not 0 < inlay_mm <= plate_mm:
            raise ValueError(f"gen_scad: inlay_mm ({inlay_mm}) must be more than zero and "
                             f"at most plate_mm ({plate_mm}); the artwork is inlaid into "
                             "the plate, and equal values inlay it the whole way through.")

        frame = self._cap_board
        corners = [transform.apply(frame, x, y)
                   for x, y in ((0, 0), (self.board_width + 1, 0),
                                (self.board_width + 1, self.board_height + 1),
                                (0, self.board_height + 1))]
        xs = [x for x, _ in corners]
        ys = [y for _, y in corners]
        x0, y1 = min(xs), max(ys)
        plate_w = (max(xs) - x0) * pitch_mm
        plate_h = (y1 - min(ys)) * pitch_mm

        def to_mm(pt):
            # Grid rows run top->down and OpenSCAD Y runs bottom->up, so Y inverts.
            return ((pt[0] - x0) * pitch_mm, (y1 - pt[1]) * pitch_mm)

        # ---- what is painted, in paint order -------------------------------------
        ops = []
        thin_strokes = thin_fills = 0
        for i, (kind, white, width, pts) in enumerate(self._cap_ink):
            if i == self._cap_outline:
                continue
            if kind == 'S' and width * pitch_mm < min_stroke_mm:
                thin_strokes += 1
                continue
            mm = [to_mm(pt) for pt in pts]
            span_x = max(x for x, _ in mm) - min(x for x, _ in mm)
            span_y = max(y for _, y in mm) - min(y for _, y in mm)
            if kind == 'F' and span_x < min_fill_mm and span_y < min_fill_mm:
                thin_fills += 1
                continue
            ops.append((kind, white, mm, (min(x for x, _ in mm), min(y for _, y in mm),
                                          max(x for x, _ in mm), max(y for _, y in mm))))

        # ---- resolve the paint order into one ink region -------------------------
        # A point is inked when the last shape over it was black, so a black shape stands
        # less the white shapes painted after it. Only the ones whose extents meet it can
        # take anything away, which keeps each difference to its own neighbourhood.
        shapes: list[tuple[int, list[tuple[float, float]]]] = []

        def shape_id(op):
            kind, _white, mm, _box = op
            pts = mm[:-1] if kind == 'F' and len(mm) > 2 and mm[0] == mm[-1] else mm
            shapes.append((0 if kind == 'F' else 1, pts))
            return len(shapes) - 1

        def meets(a, b):
            return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])

        groups = []
        for pos, op in enumerate(ops):
            if op[1]:
                continue
            over = [later for later in ops[pos + 1:] if later[1] and meets(op[3], later[3])]
            groups.append((shape_id(op), [shape_id(w) for w in over]))

        if not groups:
            raise ValueError("gen_scad: nothing left to print -- every painted shape was "
                             "dropped as too small, or erased by one painted over it.")

        holes = sorted({(round(x, 3), round(y, 3))
                        for x, y in map(to_mm, self._cap_holes)})

        # ---- serialize -----------------------------------------------------------
        def vec(pt):
            return f"[{pt[0]:.3f}, {pt[1]:.3f}]"

        def poly(pts):
            return "[" + ", ".join(vec(p) for p in pts) + "]"

        dropped = []
        if thin_strokes:
            dropped.append(f"{thin_strokes} strokes under {min_stroke_mm} mm")
        if thin_fills:
            dropped.append(f"{thin_fills} fills under {min_fill_mm} mm")
        painted = sum(1 for g in groups if not g[1])
        carved = len(groups) - painted

        lines = [
            "// OpenSCAD board label generated by stripboard.",
            f"// {len(groups)} painted shapes ({carved} with lettering knocked out of "
            f"them), {len(holes)} lead holes, {plate_w:.1f} x {plate_h:.1f} mm."
            + (f" Dropped as unprintable: {', '.join(dropped)}." if dropped else ""),
            f"// {plate_mm:.2f} mm thick with the artwork {inlay_mm:.2f} mm deep in it. Two"
            " bodies meeting flush at the top",
            "//   face, one per filament. Render one at a time:",
            f'//   openscad -D \'part="plate"\' -o plate.stl {Path(name).name}',
            "",
            'part    = "all";     // "all", "plate" or "traces"',
            f"nozzle  = {nozzle_mm:.3f};     // stroke width (mm): one nozzle bead",
            f"hole_d  = {hole_mm:.3f};     // lead hole diameter (mm)",
            f"plate_h = {plate_mm:.3f};     // board thickness (mm) -- the lead has to clear",
            "                     //   this plus the protoboard under it, so thinner is",
            "                     //   better; a couple of layers is the practical floor",
            f"inlay_h = {inlay_mm:.3f};     // trace height (mm): how deep the artwork sits",
            "                     //   below the top face. Set it equal to plate_h to",
            "                     //   carry the artwork the whole way through, which is",
            "                     //   the thinnest a two-colour label can be",
            f"facets  = {facets};        // facets per round cap and per hole",
            "",
            f"plate = [{plate_w:.3f}, {plate_h:.3f}];",
            "",
            "// [is_stroke, points]",
            "shapes = [",
        ]
        lines += [f"    [{kind}, {poly(pts)}]," for kind, pts in shapes]
        lines += ["];", "", "holes = ["]
        lines += [f"    {vec(pt)}," for pt in holes]
        lines += ["];", ""]

        lines += ["// Black shapes, each less the white ones painted over it.",
                  "module ink() {", "    union() {"]
        for black, over in groups:
            if over:
                subs = " ".join(f"shape({w});" for w in over)
                lines.append(f"        difference() {{ shape({black}); {subs} }}")
            else:
                lines.append(f"        shape({black});")
        lines += ["    }", "}", ""]
        lines += _MODULES.splitlines()

        target = Path(name)
        if target.parent != Path():
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {name}: {len(groups)} shapes, {len(holes)} holes, "
              f"{plate_w:.1f} x {plate_h:.1f} mm"
              + (f", dropped {', '.join(dropped)}" if dropped else ""))
