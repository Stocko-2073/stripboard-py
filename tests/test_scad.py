"""The OpenSCAD board label, for a two-colour 3D print.

Unlike the laser exporters, this one has to survive being a physical object. A plate the
wrong size will not sit on the board; a missing hole is a lead with nowhere to go; artwork
that does not meet the plate flush will not print as two filaments.

Its input is the *ink* capture rather than the stroke capture, because a printer needs the
artwork as area: filled component bodies, and lettering knocked out of them. That makes
colour and paint order load-bearing -- the renderer draws a glyph by filling a box in the
opposite colour and stroking over it, so white is how it erases and a point is inked when
the last shape covering it was black. Most of what follows pins that down.

It is all checkable because OpenSCAD's vector syntax is Python's: the emitted literals
parse back with `ast.literal_eval`, so the file is its own oracle and no golden copy is
needed.
"""

from __future__ import annotations

import ast
import re

import pytest

from stripboard import StripBoard

PITCH_MM = 2.54


def captured(*, width=6, height="D", text="HI", **board_kwargs):
    """A LABEL render with ink capture on -- what `project(scad=...)` builds."""
    sb = StripBoard(page_width=16, page_height=14, black_and_white=True, **board_kwargs)
    sb._cap_on = True
    sb.begin_view("LABEL", width, height, at=(0, 0))
    sb.text(1, "A", text)
    sb.end_board()
    return sb


@pytest.fixture
def label_board():
    return captured()


def scad(board, tmp_path, **kwargs) -> str:
    target = tmp_path / "out.scad"
    board.gen_scad(target, **kwargs)
    return target.read_text(encoding="utf-8")


def literal(text, name):
    """The value of a top-level `name = ...;` assignment, as Python."""
    body = re.search(rf"^{name} *= *(.+?);$", text, re.MULTILINE | re.DOTALL).group(1)
    return ast.literal_eval(re.sub(r"//.*", "", body).strip())


def param(text, name) -> float:
    """The value of one of the emitted scalar parameters."""
    return float(re.search(rf"^{name} *= *([0-9.]+);", text, re.MULTILINE).group(1))


def ink(text) -> str:
    """The body of the emitted `ink()` module."""
    return text.split("module ink()")[1].split("module shape(")[0]


def strokes(text):
    return [pts for is_stroke, pts in literal(text, "shapes") if is_stroke]


def fills(text):
    return [pts for is_stroke, pts in literal(text, "shapes") if not is_stroke]


# ---- the plate ----------------------------------------------------------------------

def test_the_plate_is_the_board_outline_in_millimetres(label_board, tmp_path):
    # A 6-column, 4-row board spans 7 x 5 pitches once its surrounding holes count.
    text = scad(label_board, tmp_path)
    assert literal(text, "plate") == [
        pytest.approx(7 * PITCH_MM, abs=1e-3), pytest.approx(5 * PITCH_MM, abs=1e-3)]


def test_the_plate_comes_from_the_board_not_from_the_ink(tmp_path):
    """Something drawn past the last column must not drag the plate off the holes."""
    sb = StripBoard(page_width=30, page_height=14, black_and_white=True)
    sb._cap_on = True
    sb.begin_view("LABEL", 6, "D", at=(0, 0))
    sb.text(20, "B", "MILES AWAY")
    sb.end_board()
    text = scad(sb, tmp_path)
    painted = max(x for _, pts in literal(text, "shapes") for x, _ in pts)
    assert painted > 7 * PITCH_MM, "the ink has to exceed the board for this to prove anything"
    assert literal(text, "plate")[0] == pytest.approx(7 * PITCH_MM, abs=1e-3)


def test_a_rotated_label_swaps_the_plate_dimensions(tmp_path):
    sb = StripBoard(page_width=16, page_height=16, black_and_white=True)
    sb._cap_on = True
    sb.begin_view("LABEL", 6, "D", at=(0, 0), rotate=True)
    sb.text(1, "A", "HI")
    sb.end_board()
    assert literal(scad(sb, tmp_path), "plate") == [
        pytest.approx(5 * PITCH_MM, abs=1e-2), pytest.approx(7 * PITCH_MM, abs=1e-2)]


def test_pitch_is_configurable(label_board, tmp_path):
    doubled = literal(scad(label_board, tmp_path, pitch_mm=2 * PITCH_MM), "plate")
    plain = literal(scad(label_board, tmp_path), "plate")
    assert doubled[0] == pytest.approx(2 * plain[0], abs=1e-3)


def test_the_board_frame_is_not_part_of_the_artwork(label_board, tmp_path):
    """A printed label is cut to the board edge already, so the drawn frame is dropped."""
    text = scad(label_board, tmp_path)
    w, h = literal(text, "plate")
    for pts in strokes(text):
        span_x = max(x for x, _ in pts) - min(x for x, _ in pts)
        span_y = max(y for _, y in pts) - min(y for _, y in pts)
        assert not (span_x > w - 0.01 and span_y > h - 0.01), "the frame reached the model"


def test_the_artwork_is_clipped_to_the_plate(label_board, tmp_path):
    assert "intersection()" in scad(label_board, tmp_path)
    assert "square(plate)" in scad(label_board, tmp_path)


def test_the_y_axis_is_flipped_so_the_label_reads_upright(tmp_path):
    """Grid rows run downwards and OpenSCAD Y runs up: row A belongs at the top."""
    text = scad(captured(text="A"), tmp_path)
    h = literal(text, "plate")[1]
    glyph = [pt for pts in strokes(text) for pt in pts if pt[0] < 3 * PITCH_MM]
    assert max(y for _, y in glyph) > h / 2


# ---- ink: fills, colour and paint order ---------------------------------------------

def test_a_filled_shape_is_captured_as_area(tmp_path):
    """A component body is a filled rectangle; outlining it would print the wrong thing."""
    sb = StripBoard(page_width=16, page_height=14, black_and_white=True)
    sb._cap_on = True
    sb.begin_view("LABEL", 6, "D", at=(0, 0))
    sb.box(2, "B", 2, 2, "F")
    sb.end_board()
    text = scad(sb, tmp_path)
    assert any(len(pts) == 4 for pts in fills(text)), "expected a rectangle as a polygon"


def test_a_fill_polygon_does_not_repeat_its_first_point(tmp_path):
    sb = StripBoard(page_width=16, page_height=14, black_and_white=True)
    sb._cap_on = True
    sb.begin_view("LABEL", 6, "D", at=(0, 0))
    sb.box(2, "B", 2, 2, "F")
    sb.end_board()
    for pts in fills(scad(sb, tmp_path)):
        assert pts[0] != pts[-1]


def test_inverted_lettering_is_knocked_out_of_its_box(tmp_path):
    """White text fills a black box and strokes the glyph white: the glyph is a hole."""
    sb = StripBoard(page_width=16, page_height=14, black_and_white=True)
    sb._cap_on = True
    sb.begin_view("LABEL", 6, "D", at=(0, 0))
    sb.white()
    sb.text(2, "B", "X")
    sb.end_board()
    assert "difference()" in ink(scad(sb, tmp_path))


def test_plain_lettering_does_not_saw_through_what_it_crosses(tmp_path):
    """Its white backing box blanks the page under the glyph, which a plate has no use
    for -- and applied as material it would cut an outline it crosses down to a sliver."""
    sb = StripBoard(page_width=20, page_height=16, black_and_white=True)
    sb._cap_on = True
    sb.begin_view("LABEL", 10, "H", at=(0, 0))
    sb.black()
    sb.box(2, "B", 6, 4)          # a stroked body outline
    sb.text(3, "C", "PDN")        # plain lettering laid across it
    sb.end_board()
    assert "difference()" not in ink(scad(sb, tmp_path)), \
        "the lettering's backing box cut the outline"


def test_a_white_fill_that_carves_a_shape_still_carves(tmp_path):
    """`shroud()` notches its body with a white fill: that one is real artwork."""
    sb = StripBoard(page_width=20, page_height=24, black_and_white=True)
    sb._cap_on = True
    sb.begin_view("LABEL", 10, "P", at=(0, 0))
    sb.shroud(4, "C")
    sb.end_board()
    assert "difference()" in ink(scad(sb, tmp_path))


def test_a_white_shape_is_never_ink_on_its_own(tmp_path):
    """White is how this renderer erases, so it contributes no material by itself."""
    sb = StripBoard(page_width=16, page_height=14, black_and_white=True)
    sb._cap_on = True
    sb.begin_view("LABEL", 6, "D", at=(0, 0))
    sb.white()
    sb.box(2, "B", 2, 2, "F")
    sb.end_board()
    with pytest.raises(ValueError, match="nothing left to print"):
        sb.gen_scad(tmp_path / "out.scad")


def test_only_overlapping_shapes_are_subtracted(tmp_path):
    """A knockout far from a body must not appear in that body's difference."""
    sb = StripBoard(page_width=20, page_height=16, black_and_white=True)
    sb._cap_on = True
    sb.begin_view("LABEL", 10, "H", at=(0, 0))
    sb.black()
    sb.box(1, "B", 2, 2, "F")
    sb.white()
    sb.box(8, "G", 2, 2, "F")
    sb.end_board()
    assert "difference()" not in ink(scad(sb, tmp_path))


# ---- strokes ------------------------------------------------------------------------

def test_a_jumper_wire_reaches_the_model(tmp_path):
    """It is a hairline on the page; a printer lays one bead whatever the page used."""
    sb = StripBoard(page_width=20, page_height=16, black_and_white=True)
    sb._cap_on = True
    sb.begin_view("LABEL", 10, "H", at=(0, 0))
    sb.jumper(2, "B", 6, "B")
    sb.end_board()
    hairlines = [w for kind, _white, w, _pts in sb._cap_ink
                 if kind == "S" and w * PITCH_MM < 0.2]
    assert hairlines, "expected the jumper to be drawn as a hairline"
    # The wire runs along one row, so it is the only horizontal stroke of that length.
    span = max(max(x for x, _ in pts) - min(x for x, _ in pts)
               for pts in strokes(scad(sb, tmp_path)))
    assert span == pytest.approx(4 * PITCH_MM, abs=1e-3)


def test_every_stroke_is_drawn_at_one_nozzle_width(label_board, tmp_path):
    text = scad(label_board, tmp_path, nozzle_mm=0.6)
    assert param(text, "nozzle") == 0.6
    assert "circle(d = nozzle, $fn = facets)" in text


def test_strokes_under_the_cutoff_can_be_dropped(tmp_path):
    sb = StripBoard(page_width=20, page_height=16, black_and_white=True)
    sb._cap_on = True
    sb.begin_view("LABEL", 10, "H", at=(0, 0))
    sb.jumper(2, "B", 6, "B")
    sb.text(1, "A", "HI")
    sb.end_board()
    everything = len(literal(scad(sb, tmp_path), "shapes"))
    strict = len(literal(scad(sb, tmp_path, min_stroke_mm=0.35), "shapes"))
    assert strict < everything


def test_a_pin_pad_is_not_part_of_the_artwork(tmp_path):
    """The pad is a ring the width of the hole it surrounds -- thinner than any bead."""
    sb = StripBoard(page_width=20, page_height=18, black_and_white=True)
    sb._cap_on = True
    sb.begin_view("LABEL", 10, "H", at=(0, 0))
    sb.black()
    sb.box(1, "B", 2, 2, "F")     # something to keep the model from being empty
    sb.dot(6, "C")
    sb.jdot(7, "C")
    sb.end_board()
    text = scad(sb, tmp_path)
    assert len(literal(text, "holes")) == 2, "the pads still drill their holes"
    pad_r = 0.35 * PITCH_MM
    for _is_stroke, pts in literal(text, "shapes"):
        near = [p for p in pts
                if abs(p[0] - 6 * PITCH_MM) < pad_r or abs(p[0] - 7 * PITCH_MM) < pad_r]
        assert not near or len(pts) == 4, "a pad mark reached the artwork"


def test_a_stroked_pin_marker_survives(tmp_path):
    """A footprint's pin-1 ring is drawn as a stroke, not a pad, and is wanted."""
    sb = StripBoard(page_width=24, page_height=20, black_and_white=True)
    sb._cap_on = True
    sb.begin_view("LABEL", 12, "K", at=(0, 0))
    sb.dip(4, "C", 3, 4, name="555")
    sb.end_board()
    ring = 0.5 * PITCH_MM * 2
    spans = [max(x for x, _ in pts) - min(x for x, _ in pts)
             for pts in strokes(scad(sb, tmp_path))]
    assert any(s == pytest.approx(ring, abs=1e-2) for s in spans), \
        "expected the pin-1 circle among the strokes"


def test_the_inlay_cannot_be_deeper_than_the_plate(label_board, tmp_path):
    with pytest.raises(ValueError, match="inlay_mm"):
        label_board.gen_scad(tmp_path / "out.scad", plate_mm=0.6, inlay_mm=0.8)


def test_the_inlay_may_run_the_whole_way_through(label_board, tmp_path):
    """Equal thicknesses are the thinnest a two-colour label can be, not an error."""
    text = scad(label_board, tmp_path, plate_mm=0.6, inlay_mm=0.6)
    assert param(text, "plate_h") == 0.6
    assert param(text, "inlay_h") == 0.6


def test_sub_nozzle_fills_are_dropped(label_board, tmp_path):
    """The board stipples every hole with a 0.05 mm dot, which cannot print."""
    text = scad(label_board, tmp_path)
    assert "fills under" in text, "expected the dropped count in the header"
    for pts in fills(text):
        span = max(max(x for x, _ in pts) - min(x for x, _ in pts),
                   max(y for _, y in pts) - min(y for _, y in pts))
        assert span >= 0.3


# ---- lead holes ---------------------------------------------------------------------

def test_a_hole_is_drilled_for_every_part_pin(tmp_path):
    sb = StripBoard(page_width=20, page_height=18, black_and_white=True)
    sb._cap_on = True
    sb.begin_view("LABEL", 10, "H", at=(0, 0))
    sb.led(3, "C")
    sb.end_board()
    assert len(literal(scad(sb, tmp_path), "holes")) == 2


def test_holes_are_drilled_for_parts_that_register_no_component(tmp_path):
    """Most part builders never call `_register`, so a netlist would miss their pins."""
    sb = StripBoard(page_width=20, page_height=18, black_and_white=True)
    sb._cap_on = True
    sb.begin_view("LABEL", 10, "H", at=(0, 0))
    sb.header(4, "B", 4)
    sb.end_board()
    assert not sb._route_components, "header() is expected not to register"
    assert len(literal(scad(sb, tmp_path), "holes")) == 4


def test_holes_include_jumper_and_link_ends(tmp_path):
    sb = StripBoard(page_width=20, page_height=18, black_and_white=True)
    sb._cap_on = True
    sb.begin_view("LABEL", 10, "H", at=(0, 0))
    sb.jumper(2, "B", 5, "B")
    sb.link(8, "B", "E")
    sb.end_board()
    assert len(literal(scad(sb, tmp_path), "holes")) == 4


def test_coincident_holes_are_drilled_once(tmp_path):
    """A wire soldered into a part's pin is one hole, not two."""
    sb = StripBoard(page_width=20, page_height=18, black_and_white=True)
    sb._cap_on = True
    sb.begin_view("LABEL", 10, "H", at=(0, 0))
    sb.led(3, "C")
    sb.jumper(3, "C", 6, "C")
    sb.end_board()
    holes = literal(scad(sb, tmp_path), "holes")
    assert len(sb._cap_holes) > len(holes), "the led pin and the jumper end share a hole"
    assert len(holes) == 3


def test_a_track_cut_is_not_a_lead_hole(tmp_path):
    """A cut drills the copper away; nothing is soldered through it."""
    sb = StripBoard(page_width=20, page_height=18, black_and_white=True)
    sb._cap_on = True
    sb.begin_view("DESIGN", 10, "H", at=(0, 0))
    sb.cut(4, "D")
    sb.end_board()
    assert sb.connections, "expected the cut to be recorded on a view that draws it"
    assert literal(scad(sb, tmp_path), "holes") == []


def test_holes_land_where_the_board_drew_them(tmp_path):
    """A part in column 3 on rows C and D drills three pitches in, three and four down."""
    sb = StripBoard(page_width=20, page_height=18, black_and_white=True)
    sb._cap_on = True
    sb.begin_view("LABEL", 10, "H", at=(0, 0))
    sb.led(3, "C")
    sb.end_board()
    text = scad(sb, tmp_path)
    h = literal(text, "plate")[1]
    holes = literal(text, "holes")
    assert all(x == pytest.approx(3 * PITCH_MM, abs=1e-3) for x, _ in holes)
    # Measured from the top edge, so they read as board rows rather than SCAD Y.
    assert sorted(round((h - y) / PITCH_MM) for _, y in holes) == [3, 4]


def test_holes_are_drilled_through_both_bodies(label_board, tmp_path):
    """A lead has to pass the plate and the artwork inlaid into it."""
    text = scad(label_board, tmp_path)
    plate = text.split("module label_plate()")[1].split("module label_traces()")[0]
    assert "lead_holes();" in plate
    assert "lead_holes();" in text.split("module inlay(")[1].split("module label_plate")[0]


# ---- the two bodies -----------------------------------------------------------------

def test_both_bodies_are_defined_and_instantiated(label_board, tmp_path):
    text = scad(label_board, tmp_path)
    for module in ("ink", "shape", "lead_holes", "inlay", "label_plate", "label_traces"):
        assert f"module {module}(" in text
    assert 'part == "all" || part == "plate"' in text
    assert 'part == "all" || part == "traces"' in text


def test_the_artwork_is_inlaid_flush_with_the_top_face(label_board, tmp_path):
    """Both solids end at plate_h, so a multi-material slicer sees them meet on a plane."""
    text = scad(label_board, tmp_path)
    assert "translate([0, 0, plate_h - inlay_h])" in text
    assert "linear_extrude(height = inlay_h + extra)" in text


def test_the_plate_has_the_artwork_subtracted(label_board, tmp_path):
    plate = scad(label_board, tmp_path).split("module label_plate()")[1]
    assert "inlay(1);" in plate, "the pocket is cut with an overshoot, not a coincident face"


def test_the_emitted_parameters_carry_the_options(label_board, tmp_path):
    text = scad(label_board, tmp_path, nozzle_mm=0.6, hole_mm=1.5, plate_mm=2.0,
                inlay_mm=0.8, facets=16)
    assert param(text, "nozzle") == 0.6
    assert param(text, "hole_d") == 1.5
    assert param(text, "plate_h") == 2.0
    assert param(text, "inlay_h") == 0.8
    assert param(text, "facets") == 16


# ---- file handling ------------------------------------------------------------------

def test_the_output_is_deterministic(label_board, tmp_path):
    assert scad(label_board, tmp_path) == scad(label_board, tmp_path)


def test_export_without_a_capture_is_an_error(tmp_path):
    sb = StripBoard(page_width=16, page_height=14, black_and_white=True)
    sb.begin_view("LABEL", 6, "D", at=(0, 0))
    sb.end_board()
    with pytest.raises(ValueError, match="no captured geometry"):
        sb.gen_scad(tmp_path / "out.scad")


def test_the_exporter_creates_missing_parent_directories(label_board, tmp_path):
    target = tmp_path / "deep" / "deeper" / "out.scad"
    label_board.gen_scad(target)
    assert target.exists()
