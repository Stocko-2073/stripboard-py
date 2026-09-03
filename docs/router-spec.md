# Stripboard Autorouter — Specification

This is new work; it is only tangentially related to the stripboard library in the
parent directory.

**Scale & scope.** This is a *protoboard* (stripboard) with through-hole parts —
not a PCB. Boards are small (a standard one is 34×26 = 884 holes total), only a
handful of components are typically unlocked, and nets are tiny: almost all are
2–3 pins, with the occasional ground net perhaps approaching ~10 pins. The problem
is far more constrained than PCB autorouting (single strip axis, vertical-only
jumpers, integer grid), so favor simple, near-exhaustive methods (simulated
annealing, semi-brute-force over placements/rotations) over heavyweight
analytical-placement / general-2D-routing machinery.

---

## 1. Coordinate system & board

- The **layout space** is a 2D grid of integer points `(x, y)`.
- A **board** is an axis-aligned rectangle in that space:
  `x ∈ [1, W]`, `y ∈ [1, H]`, bounds inclusive, origin at `(1, 1)`.
  - Default / typical size: `W = 34`, `H = 26`. Configurable.
  - Dimensions are `(x, y)`: `W = 34` is width (`x`), `H = 26` is height (`y`).
    Strips run along `x`.
- An element is **on board** iff every point it occupies satisfies
  `1 ≤ x ≤ W` and `1 ≤ y ≤ H`.
- **Invariant:** all pins, strips, jumpers, and keep-outs must be on board.
  (Cuts may fall off board; off-board cuts simply do not exist — see §5.)

Distances are Manhattan: `dist((x1,y1),(x2,y2)) = |x1-x2| + |y1-y2|`.

---

## 2. Entities

### 2.1 Strip (horizontal conductor)
A **strip** is a maximal run of adjacent points along a single row.

- Row `y`, columns `[xa, xb]` with `xa ≤ xb`.
- Occupies `{ (x, y) : xa ≤ x ≤ xb }`.
- `points(S) = xb − xa + 1`.
- `length(S) = xb − xa` (unit segments; a single point has length 0).
- **Minimum size is 1 point** (`xa = xb` allowed, e.g. for a lone pin): a single
  point has length 0, two points have length 1.

### 2.2 Jumper (vertical bridge)
A **jumper** is a two-endpoint vertical wire that arcs over the board.

- Column `x`, rows `ya < yb`.
- **Endpoints** `E(J) = { (x, ya), (x, yb) }` — soldered to the board.
- `vlength(J) = yb − ya`, **minimum 1**.
- **Keep-out** `K(J) = { (x, y) : ya < y < yb }` — the cells the wire spans over.
  - If `vlength = 1` there are no cells strictly between the endpoints, so
    `K(J) = ∅` (no keep-out).
  - The keep-out is exactly one column wide — the jumper's own column. It reserves
    no horizontal clearance on either side.

### 2.3 Component
A **component** is a rigid body defined in **local coordinates** (local origin at
`(0, 0)`), carrying:
- **pins** — points, each at a local offset, and
- **keep-out rectangles** — inclusive axis-aligned rectangles.

A component may consist of keep-outs only (no pins) yet must still be routed around.

An **instance** places a component by mapping its local coordinates onto the board:
- **Unlocked:** its world **origin** may be translated during placement, and it may
  be **rotated 180°** (no 90° rotation, no mirroring).
- **Locked:** origin and rotation are fixed at specified values.

**180° rotation** is taken about the local origin: a local offset `(dx, dy)` maps to
`(−dx, −dy)`, and an inclusive keep-out `[x0,x1]×[y0,y1]` maps to `[−x1,−x0]×[−y1,−y0]`.
Placement then adds the world origin. The transform is an involution
(`flip ∘ flip = identity`). The concrete input schema is §2.7.

### 2.4 Pin
A **pin** is a single point contributed by a component. Every pin belongs to
**exactly one** net (§2.7) and sits on its own strip, even when it reaches the net
only through an internal connection.

### 2.5 Net
A **net** is an electrical group: a set of **pins**, plus the **jumpers** and
**strips** routed to connect them.
- Input netlists contain **pins only**; jumpers and strips are produced by routing.
- Two pins may be **internally connected**: electrically common inside a component,
  *without* being on the same strip. An internal connection contributes **length 0**
  and may be routed *through either pin*. Internal connections **define** net
  membership — tying pin B to pin A puts B in A's net (§2.7).

### 2.6 Cut
A **cut** is derived, not authored (see §5).

### 2.7 Input model (types, instances, nets)

The router is fed a **board**, a set of **component instances**, and a **netlist**.

**Component type** — a reusable template (footprint) in local coordinates
(origin `(0, 0)`, not stored):
- `pins`: each a stable `local_id` (e.g. `"1"`, `"VCC"`) and a local offset `(dx, dy)`.
- `keepouts`: local inclusive rectangles.
- `internal`: groups of `local_id`s that are electrically common inside the part.

**Component instance** — a placed occurrence of a type: an `id` (e.g. `"R3"`), its
`type`, a world `origin`, a `flipped` flag (180°, §2.3), and a `locked` flag. A
locked instance also fixes `origin` and `flipped`.

**Pin identity** is the pair `(instance_id, local_id)` — stable across placement, so
nets reference pins by identity, never by coordinate.

**Net** — an `id`/name (e.g. `"GND"`), a set of pin references `(instance_id,
local_id)`, and an optional importance `weight` (default 1).

**Net membership** is the closure over (a) explicit netlist membership and (b)
`internal` ties: if a pin is listed in a net, every pin internally tied to it joins
that net too. Listing two internally-tied pins in *different* nets is an input error.

**Every pin has a net.** A pin not otherwise assigned is given its own trivial net
named `NET_<instance_id>_<local_id>`. Such a net has one pin, `netLength = 0`, and
is trivially fully connected once its pin sits on a strip — so even NC / mechanical
pins get a (single-point) strip for physical stability.

---

## 3. Occupancy & placement rules

Each entity "occupies" a point set:

| Entity            | Occupies                                  |
|-------------------|-------------------------------------------|
| Strip             | its row points                            |
| Jumper            | endpoints `E(J)` **and** keep-out `K(J)`  |
| Pin               | its single point                          |
| Component keep-out| its rectangle points                     |
| Cut               | its point(s)                              |

Occupied points are of two kinds:
- **Conductive points** carry signal: **strip cells, pins, and jumper endpoints**.
- **Clearance points** are reserved but non-conductive: a **jumper's keep-out arc**
  `K(J)` and a **component keep-out**.

A jumper is two conductive points (its endpoints) joined by an arc whose cells are
*clearance*, not conductive — which is exactly why a jumper may pass over a strip
without connecting to it.

### 3.1 Forbidden overlaps (validity)

Checked between **distinct** entities (never a component against its own authored
geometry). These hold **globally**, regardless of net.

| Pair                                         | Rule            |
|----------------------------------------------|-----------------|
| strip ∩ strip                                | empty           |
| same-row strips                              | ≥ 1 empty column between them |
| pin ∩ pin                                    | empty           |
| keep-out ∩ keep-out                          | empty           |
| pin ∩ keep-out                               | empty           |
| jumper (endpoint **or** keep-out) ∩ keep-out | empty           |
| pin ∩ jumper (endpoint **or** keep-out)      | empty           |
| jumper ∩ jumper                              | empty           |
| cut ∩ pin                                    | empty           |
| cut ∩ jumper endpoint                        | empty           |

### 3.2 Permitted / required overlaps

| Pair                        | Rule                                                        |
|-----------------------------|-------------------------------------------------------------|
| pin ∩ strip                 | **required**, same net: every pin lies on a strip of its net |
| jumper endpoint ∩ strip     | permitted, same net — this is a *connection* (§4)           |
| jumper keep-out ∩ strip     | permitted, any net — a jumper may arc over strips           |
| strip ∩ component keep-out  | permitted — strips pass through keep-outs                   |
| cut ∩ component keep-out    | permitted (unconstrained)                                   |

### 3.3 Same-row gap ↔ cut

Rule 8/9: two strips on the same row must be separated by **≥ 1 empty column**.
That empty column is exactly where a **cut** lands (§5). Consequences:

- `strip(x=1:3, y=4)` and `strip(x=4:6, y=4)` — **invalid** (touching).
- `strip(x=1:3, y=4)` and `strip(x=5:6, y=4)` — **valid** (empty column at `x=4`).

Because the gap is guaranteed empty, a cut never lands in the middle of another
strip on the same row.

### 3.4 Cross-net collisions

- **Collision:** two *different* nets share a **conductive point** (§3). This is
  forbidden. Sharing only clearance points is fine — e.g. a jumper of one net may
  arc over a strip of another, since their conductive points never meet.
- A **connection** (pin-on-strip or jumper-endpoint-on-strip, §4) is only valid
  **within a single net**. A pin or jumper endpoint of net A landing on a strip of
  net B is an invalid inter-net connection (and is a collision).

---

## 4. Connectivity

### 4.1 Connection
A **connection** exists when either:
- a pin's point lies on a strip point, or
- a jumper endpoint lies on a strip point.

A connection is valid only within one net (§3.4).

### 4.2 Fully connected net
A net is **fully connected** iff it cannot be split into two separate sub-nets —
i.e. there is a path of connections (§4.1), jumpers, and internal connections
between **every** pair of pins in the net. Equivalently, all pins lie in a single
connected component of the electrical graph (§4.3).

Independently, every **jumper endpoint** must also connect (§4.1) to a strip of its
net — a jumper with a dangling endpoint is invalid. This is a separate requirement,
*not* implied by pin connectivity (a net joined entirely through strips could
otherwise carry a floating jumper).

### 4.3 Electrical graph & net length
Model the net as a weighted graph whose **nodes are conductive sites** — the net's
pins and jumper endpoints, each at a definite `(x, y)`. Do **not** collapse a strip
to a single node; that would erase horizontal distance. Edges:
- **Same-strip travel:** two sites on the same strip are joined by an edge of weight
  `|Δx|` (their column difference).
- **Jumper:** joins its two endpoints with weight `vlength(J)`.
- **Internal connection:** joins the two tied pins with weight 0.

`shortestPath(p, q)` = minimum-weight path between pins `p, q` in this graph.

**Net length** = `max` over all pin pairs `(p, q)` of `shortestPath(p, q)`
— the electrical **diameter** of the net. This is the definition used by the
routing cost (§7). It is *not* total routed copper: "jumpers + strips" describes
what a path is made of, not a sum over all material.

Corollary: extending a strip past the pins it serves does **not** change net
length — dead-end copper is not on any pin-to-pin path — but it can reduce cuts
(§5). This lets the router trade strip length for fewer cuts at equal net length.

---

## 5. Cuts (derived from strips, not a stored entity)

A **cut** is a *derived property of a strip*, never a first-class, movable entity.
It is the point immediately past a strip's edge, when that point is on board. For
a strip on row `y` spanning `[xa, xb]`:

    cuts(S) = { (xa − 1, y) : on board } ∪ { (xb + 1, y) : on board }

Examples:
- `strip(x=3:5, y=9)` → cuts at `(2,9)` and `(6,9)`.
- `strip(x=1:19, y=9)` → only `(20,9)` (`(0,9)` is off board).
- `strip(x=1:34, y=9)` on a 34-wide board → no cuts (both off board).
- single-point `strip(x=5:5, y=9)` → cuts at `(4,9)` and `(6,9)`.

Rules:
- A cut belongs to its **strip**, not to a row or a net. During routing there is
  no cut state to maintain: as strips are ripped up and pushed around, their cuts
  move and vanish with them automatically.
- **Physical collapse — output only.** In the final result, gather cuts across all
  strips and merge coincident positions into single physical cuts:

      physicalCuts = collapse( ⋃_S cuts(S) )

  Cut *entities* are materialized only here; during routing cuts stay attached to
  their strips. (The routing cost still counts distinct physical cut positions on
  the fly — §7 — but that is a transient count, not stored cut state.)
- A cut position may not coincide with a pin or a jumper endpoint (§3.1). Because
  same-row strips keep a ≥ 1 empty-column gap (§3.3), an edge cut never lands
  mid-strip on the same row.

---

## 6. Operations

- **Rip-up:** remove all jumpers and strips from a net, leaving only its pins.

---

## 7. Routing problem

**Inputs** (schema in §2.7)
- a **board** (dimensions + objective weights),
- **component instances** (locked and unlocked) of component types,
- a **netlist** mapping nets to their pin references.

**Phase 1 — Placement (starting point).**
Move unlocked components (translate; optionally rotate 180°) to minimize a
pre-routing Manhattan wirelength **summed over all nets**. Locked-component pins
are fixed anchors in this sum. The summation is what balances a component pulled
by several nets in different directions: equilibrium minimizes total pull, so no
separate balancing term is needed.

The per-net wirelength model is a **separable half-perimeter (HPWL)** that mirrors
the routing cost:

    place_cost = Σ_nets  w_net · [ w_x · xspan(net) + w_y · yspan(net) ]

where `xspan`/`yspan` are the bounding-box dimensions of the net's pins
(`xspan = max_x − min_x`, likewise `y`), `w_net` is the net's importance weight, and
`w_x`/`w_y` (suggested `1` / `5`) echo the routing weights (horizontal span tracks
strip length / electrical diameter; vertical span tracks jumper count, since each
row a net straddles needs a jumper). For the small nets this problem sees (Scale & scope,
top), HPWL equals the Manhattan MST for ≤ 3-pin nets and closely tracks it
otherwise, so a Manhattan MST is unnecessary; an all-pairs distance sum is avoided
because it over-weights high-fan-out nets.

**Phase 2 — Routing.**
Produce strips, jumpers, and (derived) cuts so that:
- every net is **fully connected** (§4.2),
- there are **no collisions** (§3.4),
- all §3.1 validity invariants hold.

**Objective (minimize).** A weighted sum. Suggested starting weights in
parentheses (tuning only — rationale in IMPLEMENTATION_NOTES §4):

```
cost = w_len (=1)  · Σ_nets  w_net · netLength     (electrical diameter, §4.3)
     + w_jmp (=10) · (number of jumpers)
     + w_cut (=3)  · (number of distinct physical cuts)
```

The cut count is the number of **distinct physical cut positions** derived from the
current strips (§5): a cut shared by two same-row strips counts once, since it is a
single piece of physical work. This is a pure recomputation from the strips, not
stored state.

Prefer longer strips when they reduce cost without raising net length
(§4.3 corollary).

**Output**
- final component placements (origin + rotation),
- per-net strips and jumpers,
- the set of physical cuts (collapsed, §5),
- a validity result and the cost breakdown.

---

## 8. Validation checklist

A layout is **valid** iff:
1. All pins, strips, jumpers, keep-outs are on board (§1).
2. Every strip is ≥ 1 point (§2.1).
3. Every jumper has vlength ≥ 1 (§2.2).
4. No forbidden overlaps (§3.1), including the same-row gap rule (§3.3).
5. No cross-net conductive collisions and no inter-net connections (§3.4).
6. Every pin lies on a strip of its own net (§3.2 / §4.1).
7. Every jumper endpoint lies on a strip of its net — no dangling jumpers (§4.2).
8. Every net is fully connected — single connected component (§4.2).
9. No derived cut coincides with a pin or jumper endpoint (§3.1 / §5).
