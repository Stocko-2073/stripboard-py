"""Serialization round-trip tests."""

from __future__ import annotations

import io

from stripboard.router import (
    Board,
    ComponentInstance,
    ComponentType,
    Net,
    PinDef,
    dump,
    load,
    route,
)
from stripboard.router.serialization import dumps, from_dict, loads, to_dict

BOARD = Board(34, 26)
PIN = ComponentType("P", pins=(PinDef("1", (0, 0)),))


def _result():
    inst = [ComponentInstance("P1", PIN, origin=(3, 4), locked=True),
            ComponentInstance("P2", PIN, origin=(10, 12), locked=True)]
    nets = [Net("N", frozenset({("P1", "1"), ("P2", "1")}))]
    return route(BOARD, inst, nets, seed=0)


def test_to_from_dict_roundtrip():
    r = _result()
    d = to_dict(r)
    r2 = from_dict(d)
    assert to_dict(r2) == d


def test_dumps_loads_roundtrip():
    r = _result()
    s = dumps(r)
    r2 = loads(s)
    assert r2.cost.total == r.cost.total
    assert r2.status == r.status
    assert {(*s2.__dict__.values(),) for s2 in r2.routing.all_strips()} == {
        (*s1.__dict__.values(),) for s1 in r.routing.all_strips()
    }


def test_dump_load_file_roundtrip():
    r = _result()
    buf = io.StringIO()
    dump(r, buf)
    buf.seek(0)
    r2 = load(buf)
    assert to_dict(r2) == to_dict(r)


def test_json_is_stable_across_dumps():
    r = _result()
    assert dumps(r) == dumps(r)
