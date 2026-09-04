# Stripboard Autorouter — Implementation Notes

**Non-normative.** `SPEC.md` is the source of truth for *what* is being built; this
file captures *how* — a suggested Python data model, algorithm sketch, feasibility
notes, and a test plan. Distilled from an implementation-focused review of the
spec. Some items depend on decisions still under discussion (input format, strip
minimum length, objective weights) and are flagged inline.

---

## 1. Suggested data model

`Point = tuple[int, int]`. Small board (≤ ~884 cells), so prefer clarity over
micro-optimization; add an occupancy index for O(1) overlap checks.

```python
# --- Templates (reusable definitions) ---
@dataclass(frozen=True)
class PinDef:
    local_id: str            # stable within the component type, e.g. "1", "VCC"
    offset: Point            # relative to the component's origin
    # net membership is assigned by the netlist, not here

@dataclass(frozen=True)
class ComponentType:
    name: str
    pins: tuple[PinDef, ...]
    keepouts: tuple[Rect, ...]          # local, inclusive rectangles
    internal: tuple[frozenset[str], ...]  # groups of local_ids tied inside the part

# --- Instances (a placed component) ---
@dataclass
class ComponentInstance:
    id: str
    type: ComponentType
    origin: Point            # world position of the type's origin
    flipped: bool            # 180° rotation about the origin
    locked: bool
    # world_pins() / world_keepouts() apply the transform below

# --- Electrical / routed entities ---
@dataclass
class Net:
    id: str
    pins: set[tuple[str, str]]   # (instance_id, local_id) refs
    weight: float = 1.0
    strips: list["Strip"] = field(default_factory=list)   # mutable, from routing
    jumpers: list["Jumper"] = field(default_factory=list)

@dataclass(frozen=True)
class Strip:
    y: int
    xa: int
    xb: int                  # invariant xa <= xb; on board
    net_id: str              # every strip belongs to a net (every pin has one)
    # length = xb - xa ; points() ; cuts() derived (on-board edges only)

@dataclass(frozen=True)
class Jumper:
    x: int
    ya: int
    yb: int                  # invariant ya < yb; on board
    net_id: str
    # endpoints() = {(x,ya),(x,yb)} ; keepout() = interior column, empty if vlength==1

@dataclass
class Board:
    w: int; h: int
    # objective weights live here (see §4 defaults)
```

**Cuts are never stored.** Provide a free function
`physical_cuts(strips) -> set[Point]` that unions each strip's on-board edge points
and dedupes; use it both for final output and for the on-the-fly cut count in the
cost (SPEC §5, §7).

**180° transform (SPEC §2.3):** rotation about the component's own origin, so a
local offset `(dx, dy) -> (-dx, -dy)` and an inclusive keep-out
`[x0,x1]×[y0,y1] -> [-x1,-x0]×[-y1,-y0]`; then translate by `origin`. It is an
involution — `flip(flip(x)) == x` — which makes a good unit-test invariant.

**Occupancy index.** Keep separate layers for **conductive** points (strip cells,
pins, jumper endpoints) and **clearance** points (jumper keep-out arc, component
keep-out). Collisions are defined only conductive-vs-conductive across nets
(SPEC §3.4); clearance layers drive the keep-out rules. A dict `point -> owner`
per layer, or a small 2D array, rebuilt cheaply.

**Constructor invariants worth enforcing:** strip/jumper ordering + on-board;
keep-out rects normalized; rotation is an involution; `physical_cuts` disjoint from
pins and jumper endpoints; every physical pin resolves onto a strip of its net.

---

## 2. Algorithm sketch

### Phase 1 — Placement
Minimize the separable HPWL sum (SPEC §7) over `(translation, 180° flip)` of the
handful of unlocked components. Locked pins are fixed anchors.

- ≤ 2 unlocked components: effectively brute-forceable over positions/flips.
- More: simulated annealing (move = pick a component, random translate/flip;
  Metropolis accept). Needs a seed for reproducibility.
- **Hard constraint the spec implies but doesn't spell out:** placement must stay
  *legal* — all components on board, no cross-component pin∩pin or keep-out∩keep-out
  — because Phase 2 cannot repair component-fixed geometry. Enforce in the move
  generator, don't just minimize HPWL.

### Phase 2 — Routing
The geometry makes this tractable: **a pin's strip is forced onto the pin's own
row** (strips are horizontal; pins are fixed after placement). So per net:

1. Group the net's same-row pins into one strip each (extent covering them).
2. Connect the per-row strips into one tree using **jumpers** — each jumper is a
   single vertical edge in one column that can bridge far-apart rows in one hop
   (arcing over intermediate rows; the arc must clear pins / other jumpers /
   component keep-outs, but may cross strips).
3. Extend strip extents to the minimum that reaches every jumper column and drops
   edge cuts, without colliding.

This is a **rectilinear-Steiner-like problem over rows**, joined by column jumpers:
horizontal axis is "free-ish copper," vertical axis is paid per jumper (`vlength`).
- 2–3-pin nets (the common case): near-trivial, effectively enumerable.
- ~10-pin ground net: still tiny (Dreyfus–Wagner over ≤10 terminals ≈ 59k states —
  instant).

**Hard parts to respect:**
- **Cut count doesn't decompose into per-edge costs** — it depends on final strip
  extents and on *sharing* of a cut column between same-row strips. A plain
  Lee/Dijkstra maze router can't minimize it directly; do a separate strip-extent
  optimization pass after the tree topology is fixed.
- **Net length is a `max` (diameter), non-additive** — greedy shortest-path tree
  growth doesn't directly minimize it; evaluate diameter on candidate topologies.
- **Nets compete for rows/columns** — a joint packing problem. Given the scale, use
  sequential routing with **rip-up-and-reroute / negotiated congestion**
  (PathFinder-style): route nets in an order; when one can't route cleanly, rip up
  (SPEC §6) and re-route conflicting nets with escalating congestion penalties. An
  outer loop over net ordering (or SA over orderings) polishes cost.
- **Jumper column choice:** for each needed row-pair, candidate columns are the free
  columns both strips can reach whose arc keep-out is clear — a small enumerable set.

**Suggested pipeline:** legal-SA placement → per-net near-exhaustive route
enumeration → global rip-up-and-reroute with congestion costs → strip-extent
post-pass for cuts. An ILP is feasible at this scale but is the "heavyweight
machinery" the spec deliberately avoids.

---

## 3. Complexity / feasibility

Everything is small: ~884 cells, few unlocked components, nets of 2–3 pins (rare
~10). Consequences:
- Validity checking: O(occupied points) with the occupancy index — trivial.
- Electrical graph + diameter: Floyd–Warshall on a per-net graph of a handful of
  nodes — negligible.
- Placement SA: converges fast; near-brute-force for ≤ 2 unlocked components.
- Per-net routing: near-enumerable; even the ground net's Steiner tree is tiny.

The real cost lives in the **global interaction** — rip-up/reroute iterations to
resolve cross-net congestion, and the **coupled objectives** (`max` diameter and
shared-cut counting) that force whole-net / whole-board cost re-evaluation instead
of summing local edge costs. Iteration count dominates, not per-step cost. Still
comfortably tractable at this scale.

---

## 4. Objective weights — suggested starting point

Purely for tuning (SPEC §7 leaves them TBD). Rationale: on a stripboard the copper
already exists, so **strip length is nearly free** and mostly a compactness
tiebreaker; a **cut** is one manual operation; a **jumper** is the costliest and
least reliable (a wire plus two solder joints).

| Weight | Suggested | Meaning |
|--------|-----------|---------|
| `w_len` | 1  | per grid unit of net-length (diameter) |
| `w_cut` | 3  | per distinct physical cut |
| `w_jmp` | 10 | per jumper |
| `w_x`   | 1  | placement, per unit horizontal span (≈ length) |
| `w_y`   | 5  | placement, per unit vertical span (≈ jumpers; discounted since one jumper spans several rows) |
| `w_net` | 1  | per-net importance, uniform by default |

Treat these as a first pass; expose them as config and revisit once real boards
exist.

---

## 5. Testing & validation

**Geometry unit tests (exact, straight from SPEC §5 examples):**
- `cuts()`: `strip(3:5,9)→{(2,9),(6,9)}`, `strip(1:19,9)→{(20,9)}`,
  `strip(1:34,9)→∅`, single-point `strip(5:5,9)→{(4,9),(6,9)}`.
- Jumper keep-out: `vlength==1→∅`; else the strict interior column.
- Rotation: `flip(flip(comp))==comp`; keep-out `[x0,x1]×[y0,y1]→[-x1,-x0]×[-y1,-y0]`.

**Validity-checker tests:** build each SPEC §3.1 forbidden case (touching same-row
strips, pin on a foreign net's strip, overlapping keep-outs, cut coincident with a
pin/endpoint) and assert rejection; build the §3.3 touching-vs-1-gap pair and each
§3.2 permitted overlap and assert acceptance — especially the cross-net arc-overs.

**Connectivity / net length:** hand-compute diameter for small nets; internal
connections give distance 0; metamorphic test of the §4.3 corollary — extending a
strip past its pins leaves `netLength` unchanged but can reduce cut count.

**Property-based (Hypothesis):** generate random *valid* layouts, assert:
- collision relation symmetric; distinct-cut count invariant under strip ordering;
- no physical cut coincides with a pin or jumper endpoint (§8.8);
- full connectivity is transitive;
- translating the whole scene by a constant on-board vector leaves cost/topology
  unchanged (metamorphic).

**End-to-end:** run the router, then run the *independent* §8 validator on its
output; assert (a) valid and (b) reported cost equals a fresh recomputation from
strips/jumpers (guards stale cached cost). Add golden tests on hand-designed
boards, and a fixed-seed determinism regression once tie-breaking is specified.

---

## 6. Open items that gate implementation

Listed here because they shape code:
- ~~**Input format**~~ — resolved; schema in SPEC §2.7 (component types/instances,
  `(instance_id, local_id)` pin identity, internal ties define membership, every
  pin gets a net).
- ~~**Strip minimum length**~~ — resolved; a strip may be a single point (length 0),
  so a lone pin is `X.X` (cut, point, cut).
- **Determinism:** tie-breaking among equal-cost placements/routes and multiple
  shortest paths; SA seed. Needed for reproducible tests.
- ~~**Infeasibility**~~ — resolved; the net carries a `NetStatus` with a reason,
  the run carries a `RouteStatus`, and `diagnose.explain_net` reports the row-pair
  feasibility a failing net was searched against.
