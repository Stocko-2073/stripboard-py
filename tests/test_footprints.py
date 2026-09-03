"""Footprint pin geometry for every routable part builder.

Pin positions are the contract between the renderer and the autorouter: the builders
record the holes they actually drew, and `_build_problem` hands those to the solver. If a
footprint shifts, boards silently mis-route, so every builder's offsets are pinned here.
"""

from __future__ import annotations

import pytest

from tests.helpers import local_pins

# name -> (builder call, expected local pin offsets)
FOOTPRINTS = {
    "cap": (lambda b: b.cap(17, "D"),
            {"1": (0, 0), "2": (0, 1)}),
    "resist": (lambda b: b.resist(18, "R", "330", l=8),
               {"1": (0, 0), "2": (0, 8)}),
    "led": (lambda b: b.led(17, "R"),
            {"A": (0, 0), "K": (0, 1)}),
    "diode": (lambda b: b.diode(5, "B"),
              {"A": (0, 0), "K": (0, 1)}),
    "sip": (lambda b: b.sip(4, "D", 3, "A", pins=["1", "2", "3"]),
            {"1": (0, 0), "2": (0, 1), "3": (0, 2)}),
    "sip_upside_down": (
        lambda b: b.sip(13, "D", 7, "AMP", upside_down=True, label_scale=0.6,
                        pins=["LRC", "BCLK", "DIN", "GAIN", "SD", "GND", "VIN"]),
        {"VIN": (0, 0), "GND": (0, 1), "SD": (0, 2), "GAIN": (0, 3),
         "DIN": (0, 4), "BCLK": (0, 5), "LRC": (0, 6)}),
    "dip": (lambda b: b.dip(3, "C", 4, 4, "U1",
                            pins=["1", "2", "3", "4", "5", "6", "7", "8"]),
            {"1": (0, 0), "2": (0, 1), "3": (0, 2), "4": (0, 3),
             "5": (4, 3), "6": (4, 2), "7": (4, 1), "8": (4, 0)}),
    "dip_upside_down": (
        lambda b: b.dip(8, "P", 3, 3, "MIC", label_scale=0.6, labels_inside=False,
                        upside_down=True, pins=["LR", "WS", "SCK", "SD", "3V", "GND"]),
        {"SD": (0, 0), "3V": (0, 1), "GND": (0, 2),
         "SCK": (3, 0), "WS": (3, 1), "LR": (3, 2)}),
    "xiao": (lambda b: b.xiao(5, "T", upside_down=True, label_scale=0.6),
             {"RX": (0, 0), "D8": (0, 1), "D9": (0, 2), "D10": (0, 3), "3V3": (0, 4),
              "GND": (0, 5), "5V": (0, 6), "TX": (6, 0), "D5": (6, 1), "D4": (6, 2),
              "D3": (6, 3), "D2": (6, 4), "D1": (6, 5), "D0": (6, 6)}),
    "rp2040": (lambda b: b.rp2040(3, "C"),
               {"D0": (0, 0), "D1": (0, 1), "D2": (0, 2), "D3": (0, 3), "D4": (0, 4),
                "D5": (0, 5), "TX": (0, 6), "5V": (6, 0), "GND": (6, 1), "3V3": (6, 2),
                "D10": (6, 3), "D9": (6, 4), "D8": (6, 5), "RX": (6, 6)}),
    "big_button": (lambda b: b.big_button(13, "L"),
                   {"AL": (0, 0), "BL": (0, 2), "AR": (5, 0), "BR": (5, 2)}),
    "terminal": (lambda b: b.terminal(3, "C", 2),
                 {"1": (0, 0), "2": (0, 1)}),
}

# Auto-assigned instance ids, from the type name and an occurrence counter.
INSTANCE_IDS = {
    "cap": "C", "resist": "R", "led": "LED", "diode": "D", "sip": "A",
    "sip_upside_down": "AMP", "dip": "U1", "dip_upside_down": "MIC", "xiao": "XIAO",
    "rp2040": "RP2040", "big_button": "BTN", "terminal": "TERM",
}


@pytest.fixture
def wide_board(make_board):
    """24 columns, so the widest footprints fit without clamping at the edge."""
    return make_board(24, "Z", page=(40, 40))


@pytest.mark.parametrize("name", sorted(FOOTPRINTS))
def test_pin_offsets(wide_board, name):
    build, expected = FOOTPRINTS[name]
    assert local_pins(build(wide_board)) == expected


@pytest.mark.parametrize("name", sorted(FOOTPRINTS))
def test_builder_returns_a_locked_handle_with_the_expected_id(wide_board, name):
    build, _ = FOOTPRINTS[name]
    comp = build(wide_board)
    assert comp.id == INSTANCE_IDS[name]
    assert comp.locked is True, "parts are placed by the caller unless locked=False"


@pytest.mark.parametrize("name", sorted(FOOTPRINTS))
def test_pins_reach_the_router_at_the_same_offsets(wide_board, name):
    """`_build_problem` must hand the solver exactly the geometry that was drawn."""
    build, expected = FOOTPRINTS[name]
    comp = build(wide_board)
    _, instances, _ = wide_board._build_problem()
    inst = next(i for i in instances if i.id == comp.id)
    assert {p.local_id: p.offset for p in inst.type.pins} == expected


def test_repeated_builders_get_numbered_instance_ids(wide_board):
    """The first instance keeps the bare type name; later ones get a counter suffix."""
    ids = [wide_board.cap(3 + 2 * i, "C").id for i in range(3)]
    assert ids == ["C", "C2", "C3"]


def test_pin_accepts_ints_for_numeric_pins(wide_board):
    c = wide_board.cap(17, "D")
    assert c.pin(2) == c.pin("2") == ("C", "2")


def test_pin_rejects_unknown_names(wide_board):
    c = wide_board.cap(17, "D")
    with pytest.raises(KeyError, match="has no pin"):
        c.pin("VCC")


def test_zener_is_not_routable(wide_board):
    """Some legacy builders draw only -- they return no handle. Documented, not a bug."""
    assert wide_board.zener(7, "B") is None


def test_net_rejects_raw_tuples(wide_board):
    """Netlists take handle.pin(...) references, so typos fail loudly."""
    c = wide_board.cap(17, "D")
    with pytest.raises(TypeError, match="expect pin references"):
        wide_board.net("n1", c.pin("1"), (3, 4))
