"""The OpenSCAD board label, for a two-colour 3D print.

Unlike the laser exporters, this one has to survive being a physical object. A plate the
wrong size will not sit on the board; a missing hole is a lead with nowhere to go; artwork
hanging off the edge prints into thin air. Those are the properties pinned here, and they
are all checkable because OpenSCAD's vector syntax is Python's -- the emitted literals
parse back with `ast.literal_eval`, so the file is its own oracle and no golden copy is
needed.

The width filter is the other half. A black-and-white `jumper()` draws a hairline to stand
for a wire, and a hairline is not something a 0.4 mm nozzle can lay down.
"""

from __future__ import annotations

import ast
import re

import pytest

from stripboard import StripBoard

PITCH_MM = 2.54


def captured(*, width=6, height="D", text="HI", **board_kwargs):
    """A LABEL render with stroke capture on -- what `project(scad=...)` builds."""
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


# ---- the plate ----------------------------------------------------------------------

def test_the_plate_is_the_board_outline_plus_a_bead(label_board, tmp_path):
    text = scad(label_board, tmp_path)
    # A 6-column, 4-row board outlines 7 x 5 pitches; the plate carries half a nozzle
    # bead on each side so the outline stroke sits on it rather than over the edge.
    assert param(text, "label_w") == pytest.approx(7 * PITCH_MM + 0.4, abs=1e-3)
    assert param(text, "label_h") == pytest.approx(5 * PITCH_MM + 0.4, abs=1e-3)


def test_the_plate_comes_from_the_board_not_from_the_ink(tmp_path):
    """Something drawn past the last column must not drag the plate out from under it."""
    sb = captured(text="HI")
    sb._cap_on = True
    sb.begin_view("LABEL", 6, "D", at=(0, 0))
    sb.text(20, "B", "MILES AWAY")
    sb.end_board()
    text = scad(sb, tmp_path)
    ink = max(x for p in sb._cap_paths for x, _ in p)
    assert ink > 7, "the stroke bounding box has to exceed the board for this to prove anything"
    assert param(text, "label_w") == pytest.approx(7 * PITCH_MM + 0.4, abs=1e-3)


def test_a_rotated_label_swaps_the_plate_dimensions(tmp_path):
    sb = StripBoard(page_width=16, page_height=16, black_and_white=True)
    sb._cap_on = True
    sb.begin_view("LABEL", 6, "D", at=(0, 0), rotate=True)
    sb.text(1, "A", "HI")
    sb.end_board()
    text = scad(sb, tmp_path)
    assert param(text, "label_w") == pytest.approx(5 * PITCH_MM + 0.4, abs=1e-2)
    assert param(text, "label_h") == pytest.approx(7 * PITCH_MM + 0.4, abs=1e-2)


def test_every_trace_point_lies_on_the_plate(label_board, tmp_path):
    text = scad(label_board, tmp_path)
    w, h = param(text, "label_w"), param(text, "label_h")
    pts = [pt for path in literal(text, "paths") for pt in path]
    assert pts, "expected some traces"
    assert all(0 <= x <= w and 0 <= y <= h for x, y in pts)


def test_the_y_axis_is_flipped_so_the_label_reads_upright(tmp_path):
    """Grid rows run downwards and OpenSCAD Y runs up: row A belongs at the top."""
    sb = captured(text="A")
    text = scad(sb, tmp_path)
    h = param(text, "label_h")
    glyph = [pt for path in literal(text, "paths") for pt in path
             if 0.4 < pt[0] < 3 * PITCH_MM]
    assert max(y for _, y in glyph) > h / 2


def test_pitch_is_configurable(label_board, tmp_path):
    doubled = scad(label_board, tmp_path, pitch_mm=2 * PITCH_MM)
    plain = scad(label_board, tmp_path)
    assert param(doubled, "label_w") - 0.4 == pytest.approx(
        2 * (param(plain, "label_w") - 0.4), abs=1e-3)


# ---- the width filter ---------------------------------------------------------------

def test_every_captured_path_records_the_width_it_was_painted_with(label_board):
    assert len(label_board._cap_widths) == len(label_board._cap_paths)
    assert all(w > 0 for w in label_board._cap_widths)


def test_a_scaled_glyph_records_a_narrower_stroke_than_a_plain_one():
    """`title()` scales by 1.5 after setting its width, `x_scale` shrinks below it."""
    sb = StripBoard(page_width=16, page_height=14, black_and_white=True)
    sb._cap_on = True
    sb.begin_view("LABEL", 6, "D", at=(0, 0))
    sb.text(1, "A", "I")
    plain = max(sb._cap_widths)
    sb.text(1, "B", "I", x_scale=0.6)
    shrunk = max(sb._cap_widths[len(sb._cap_paths) - 1:])
    sb.title(0, 0, "I")
    grown = max(sb._cap_widths)
    sb.end_board()
    assert shrunk < plain < grown
    assert grown == pytest.approx(0.15 * 1.5, abs=1e-6)


def test_a_hairline_below_the_cutoff_is_skipped(tmp_path):
    """A black-and-white jumper draws a 0.127 mm wire, far under a nozzle bead."""
    sb = StripBoard(page_width=16, page_height=14, black_and_white=True)
    sb._cap_on = True
    sb.begin_view("LABEL", 6, "D", at=(0, 0))
    sb.jumper(2, "B", 4, "B")
    sb.end_board()
    hairlines = [w for w in sb._cap_widths if w * PITCH_MM < 0.2]
    assert hairlines, "expected the jumper to draw a hairline"
    assert len(literal(scad(sb, tmp_path), "paths")) == len(sb._cap_paths) - len(hairlines)


def test_lowering_the_cutoff_keeps_more_paths(label_board, tmp_path):
    everything = literal(scad(label_board, tmp_path, min_stroke_mm=0.0), "paths")
    strict = literal(scad(label_board, tmp_path, min_stroke_mm=0.45), "paths")
    assert len(everything) > len(strict)


def test_the_skipped_count_is_reported_in_the_file(tmp_path):
    sb = StripBoard(page_width=16, page_height=14, black_and_white=True)
    sb._cap_on = True
    sb.begin_view("LABEL", 6, "D", at=(0, 0))
    sb.jumper(2, "B", 4, "B")
    sb.end_board()
    assert "skipped" in scad(sb, tmp_path)


# ---- lead holes ---------------------------------------------------------------------

def test_a_hole_is_punched_for_every_part_pin(tmp_path):
    sb = StripBoard(page_width=20, page_height=18, black_and_white=True)
    sb._cap_on = True
    sb.begin_view("LABEL", 10, "H", at=(0, 0))
    sb.led(3, "C")
    sb.end_board()
    assert len(literal(scad(sb, tmp_path), "holes")) == 2


def test_holes_are_punched_for_parts_that_register_no_component(tmp_path):
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


def test_coincident_holes_are_punched_once(tmp_path):
    """A wire soldered into a part's pin is one hole, not two."""
    sb = StripBoard(page_width=20, page_height=18, black_and_white=True)
    sb._cap_on = True
    sb.begin_view("LABEL", 10, "H", at=(0, 0))
    sb.led(3, "C")
    sb.jumper(3, "C", 6, "C")
    sb.end_board()
    marks = len(sb._cap_holes)
    holes = literal(scad(sb, tmp_path), "holes")
    assert marks > len(holes), "the led pin and the jumper end share a hole"
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
    """A part in column 3 on rows C and D punches three pitches in, three and four down."""
    sb = StripBoard(page_width=20, page_height=18, black_and_white=True)
    sb._cap_on = True
    sb.begin_view("LABEL", 10, "H", at=(0, 0))
    sb.led(3, "C")
    sb.end_board()
    text = scad(sb, tmp_path)
    h = param(text, "label_h")
    holes = literal(text, "holes")
    assert all(x == pytest.approx(3 * PITCH_MM + 0.2, abs=1e-3) for x, _ in holes)
    # Measured from the top edge, so they read as board rows rather than SCAD Y.
    rows = sorted(round((h - y - 0.2) / PITCH_MM) for _, y in holes)
    assert rows == [3, 4]


# ---- the emitted model --------------------------------------------------------------

def test_both_bodies_are_defined_and_instantiated(label_board, tmp_path):
    text = scad(label_board, tmp_path)
    for module in ("label_pins", "label_base", "label_traces"):
        assert f"module {module}()" in text
    assert 'part == "all" || part == "base"' in text
    assert 'part == "all" || part == "traces"' in text


def test_the_holes_are_subtracted_from_both_bodies(label_board, tmp_path):
    """A lead has to pass through the plate and the artwork standing on it."""
    text = scad(label_board, tmp_path)
    base = text.split("module label_base()")[1].split("module label_traces()")[0]
    traces = text.split("module label_traces()")[1]
    assert "label_pins();" in base
    assert "label_pins();" in traces


def test_the_traces_are_clipped_to_the_plate(label_board, tmp_path):
    traces = scad(label_board, tmp_path).split("module label_traces()")[1]
    assert "intersection()" in traces
    assert "square([label_w, label_h])" in traces


def test_the_nozzle_and_hole_diameter_reach_the_emitted_parameters(label_board, tmp_path):
    text = scad(label_board, tmp_path, nozzle_mm=0.6, hole_mm=1.5, base_mm=0.8,
                trace_mm=0.5)
    assert param(text, "nozzle") == 0.6
    assert param(text, "hole_d") == 1.5
    assert param(text, "base_h") == 0.8
    assert param(text, "trace_h") == 0.5


def test_the_traces_stand_on_top_of_the_plate(label_board, tmp_path):
    """Two solids sharing a plane, so a slicer sees one body per filament."""
    traces = scad(label_board, tmp_path).split("module label_traces()")[1]
    assert "translate([0, 0, base_h])" in traces
    assert "linear_extrude(height = trace_h)" in traces


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
