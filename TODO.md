# TODO

Work queued from `POSTMORTEM_FEEDBACK.md` (U-BOT base board, `stripboard` 0.1.1 —
40 nets on 28x22, eight iterations to route). Every claim in that report was checked
against the source; the file references below are the confirmations.

The diagnostics, the public `link()` builder, the StepStick footprint and the pin-order
docs have shipped; what follows is what is left, all of it output-changing or larger.

Each task carries three sizes:

* **Scale** — how much code. XS (< 20 lines) · S (< 100) · M (a few hundred, one module) ·
  L (cross-module) · XL (architectural).
* **Scope** — what surface it touches.
* **Blast radius** — what can silently change. The one that matters here is
  **rendered output** and **solver output**: `CONTRIBUTING.md` asks that output-changing
  work land on its own commit with a changelog note, and it invalidates `.regression/`
  traces for every board that exercises it.

---

## Tier 1 — contained, changes solver output

Each of these needs its own commit, a changelog entry, and a `.regression/` re-capture.

### 1.1 Enumerate topologies over the feasibility graph
Report §3, and the best single fix in the report. `net_router.py:322` reads

```python
topos = _spanning_trees(k) if k <= 5 else _curated_trees(k)
```

and `_curated_trees` only ever yields a chain, k stars, and k-2 double-stars. Their
7-row 3V3 net had a valid path-plus-leaves shape in none of those sets, so it failed
*routed alone on an empty board*.

The fix is cheap because `fpair` — feasible columns for all k(k-1)/2 row pairs — is
already built ten lines above the choice. Restrict to the graph of pairs with a
non-empty column set and enumerate *its* spanning trees. Their 7-row net had ~10 such
edges; that graph's spanning tree count is small.

* Scale **M** · Scope: `_route_all_topologies` + one helper, `router/routing/net_router.py`
* Blast radius: **solver output for any net with ≥ 6 rows.** Keep it output-identical
  for k ≤ 5 by pruning only edges whose domain is empty (those branches already die at
  `_forward_check`), and gate the widened enumeration behind a node-count cap so a
  dense feasibility graph on a large net cannot blow the budget.
* Needs a regression board with a high-fan-out power net — `examples/` has none, so add
  one, or capture against the U-BOT board before landing.

### 1.2 Detour-row candidates ranked by usable span, exterior rows included
Report §4, confirmed. `_steiner_row_candidates:339` assigns `dist = 0` to every empty
row inside the net's span, sorts by row number, and truncates at
`_MAX_STEINER_ROWS = 6`. So a net spanning seven or more empty interior rows can never
reach an exterior row — and the exterior rows are exactly the free ones where a bus
crosses. Rank by free span within the net's column range instead of by row number, and
let exterior rows compete.

* Scale **S** for the ranking · Scope: one function
* Blast radius: **medium.** Only nets that fall through to the fallback are affected,
  but a net that currently *succeeds* via the fallback will pick a different row.

### 1.3 Allow two detour rows for wide nets
Report §4, third bullet: VM needed two. `_route_steiner_fallback` augments the row set
by exactly one row, so this is a nesting change, not new machinery — but it multiplies
the candidate searches and shares one `_NODE_BUDGET` across all of them.

* Scale **M** · Scope: `_route_steiner_fallback`
* Blast radius: **medium** on output, **real** on runtime. Gate on `k` and on the
  primary search having failed; measure before defaulting on.

### 1.4 Congestion field is identically zero for the most common unlocked part
Report §6 observed that `locked=False` on eight pull-ups produced an unroutable board
every time and concluded placement needs to become routing-aware (that is 2.3 below,
an XL). **The report mis-diagnosed the immediate cause.** `congestion_penalty`
(`router/placement.py:104`) sums the demand field only over `world_keepouts()`, and
`resist()` registers `keepouts = ()` whenever `l < 2` (`passives.py:183`). A 1-hole
pull-up therefore contributes **exactly zero** congestion penalty, so `_place_cost`
degenerates to pure HPWL for it — precisely the routability-blindness the module
docstring says the congestion term exists to prevent. At `l == 2` the keep-out is a
single cell, so the signal is nearly zero there too.

Fix: when an instance has no keep-outs, charge the demand under its **pin bounding
box** (a part's holes block jumpers just as its body does). Two lines in
`congestion_penalty`, plus deciding whether pins should always count in addition to
keep-outs.

* Scale **S** · Scope: `router/placement.py`
* Blast radius: **placement ranking for boards with unlocked parts only.**
  `examples/` and the templates are entirely locked, so the shipped regression set
  will not move. Worth doing before 2.3 — it may make `locked=False` usable for small
  passives without any of the architectural work.

### 1.5 `sip(mod=...)` names holes that were never drawn
`_draw_sip` (`footprints/ics.py:33`) draws a hole every `mod` rows, but `_sip_pins`
(`:78`) maps a supplied `pins` list over `range(0, l)` — every row, ignoring `mod`. So
`sip(x, y, 4, pins=['A','B','C','D'], mod=2)` draws two holes and returns four pin
positions, two of which are on rows with no hole. `_dip_pins` (`:191`) steps by `mod` in
both branches, which is what makes this look like an oversight rather than a choice.

Nothing in the repo passes both `pins` and `mod`, so it is latent.

* Scale **XS** · Scope: `footprints/ics.py`, one test
* Blast radius: **any board passing both `pins` and `mod` to `sip()`** — which changes
  where its pins are, and therefore its route. Worth checking private designs before
  landing.

### 1.6 Strip trimming as an option
Report §9, confirmed: `minimize_cuts` (`router/routing/strip_extent.py:52`) extends the
outermost strips to `1` and `board.w` unconditionally, because a cut costs 3 and copper
costs nothing. Six strips ran the full 28 holes on their board, including a
battery-sense tap passing under the 12 V terminal — electrically fine, but every later
edit has to cut into something. Add a `trim` option (or a small per-hole cost past the
last pin/jumper) threaded through `RouteOptions` → `autoroute()`.

* Scale **S–M** · Scope: `strip_extent.py`, `RouteOptions`, `autoroute()`
* Blast radius: **none if opt-in**, total if defaulted. Opt-in.

### 1.7 `cap()` registers no body keep-out
Not in the report, found while checking §7. `resist()` registers `((0, 1, 0, l-1),)`
for `l >= 2`; `cap()` (`passives.py:69`) registers nothing at any `l`, so the router
will arc a jumper straight through a capacitor body. Same one-line shape as the
resistor's.

Also §11: `cap()` marks + at pin 1 and draws the mark mid-body when
`upside_down=True, l=2`; a `polarity` flag that moves the mark to the correct pin.

* Scale **XS** each · Scope: `footprints/passives.py`
* Blast radius: the keep-out **changes routing for any board with an `l >= 2` cap**.
  The polarity flag is drawing-only and opt-in.

### 1.8 No way to tell the router a track is already cut
The worst of the hand/auto mixing gaps, and the only one with no escape hatch. A hand
`sb.cut()` is invisible to the solver in **both** its forms, and a keep-out cannot stand in
for it, because `_strip_conflicts` (`net_router.py:81`) checks only conductive occupancy —
a strip is deliberately allowed to cross clearance. Demonstrated on a 12-wide board with a
net either side of a severed hole: `sb.cut(6, 'C')`, `sb.cut(6.5, 'C')` and
`sb.keepout(6, 'C')` all produce the same route, a single strip spanning columns 1-12
straight through the cut, reported `feasible` and passing the validator.

This is worse than the jumper case that `link()` fixed. Two wires in one hole is visible on
the board and already warns; a strip the solver believes is continuous when it is not gives
a board that renders correctly, validates, and does not work.

What it needs: severed holes as board geometry rather than component geometry — a set on
`Board` that `_strip_covers_foreign` and `_strip_cut_conflicts` consult, that
`strip_extent.minimize_cuts` stops extending at, and that the validator checks. Then a
builder (`sb.sever()`, or `sb.cut(..., declare=True)`) to populate it.

* Scale **M** · Scope: `model.py`, `net_router.py`, `strip_extent.py`, `validation.py`,
  `wiring.py`
* Blast radius: **none if the builder is opt-in** — no existing board declares a cut. It
  becomes total the moment plain `sb.cut()` declares by default, since any board that
  hand-cuts *and* autoroutes would start constraining the solver. Ship it opt-in.
* Highest priority on this list. It is the only entry here where the current behaviour can
  produce a board that looks right and is wrong.

### 1.9 Every cut is priced the same, but a buried one is not the same work
`cost_resolved` charges `w_cut * num_cuts` with all cuts equal. The one difficulty
difference among the cuts the router actually makes is whether it lands under a part body:
that cut has to be drilled before the part goes on, and discovering it late means
desoldering a module. On the U-BOT board it is 23 of 34.

The router only ever drills a whole hole — `Strip.xa`/`xb` are `int`, `edge_cuts` derives
from them and `physical_cuts` collapses those, so a half-column cut is unreachable from the
solver and needs no penalty of its own. Burial is the axis that varies.

`cost_resolved` already receives `instances`, so `world_keepouts()` is in hand and
`cuts_under_bodies` already computes the set. Add `num_buried_cuts` to `CostBreakdown` and
a weight for it.

* Scale **S** · Scope: `cost.py`, `result.py`, `Weights`
* Blast radius: **every board's cost**, so which placement and route win. Needs a
  re-capture, and a default weight chosen by comparing boards rather than by taste — start
  at parity with `w_cut` so the default ranking is unchanged, and let a board file raise it.

---

## Tier 2 — larger, and the ones to think hardest about before starting

### 2.1 Body keep-outs on module footprints by default
Report §7, confirmed: only `controls.py:87` (`big_button`), `connectors.py:182`
(`terminal`) and `passives.py:183` (`resist`) register keep-outs. `dip()`, `sip()`,
`xiao()` and `rp2040()` register pins only, so a jumper end can land under a module
body. Their board needed hand `sb.keepout()` calls for each module interior and the
XIAO's USB-C overhang.

The code is trivial (one rect per footprint, plus overhang rects for the modules that
have them). The decision is not:

* **Defaulting it on is a breaking change.** Any existing board whose route threads a
  jumper under a DIP stops routing. That is the *correct* answer physically — that
  board was never buildable — but it turns working designs into `PARTIAL` results on a
  patch upgrade.
* Recommended: add `body_keepout=` per footprint, default `False` for one release with
  a changelog note and a warning in `route_report`, then flip the default in the next
  minor.

* Scale **S** per footprint, **M** with the overhang rectangles
* Blast radius: **the whole shipped example/regression set** once defaulted on.

### 2.2 Conflict-attributed rip-up, and the cheap lookahead that may replace it
Report §5. Their left edge had three free columns and five vertical hops with exactly
one legal assignment; 60 attempts of reorder-plus-shuffle never found it because
`_next_order` (`ripup.py:120`) only knows *that* a net failed, never *which* placed
jumper blocked it — so it cannot rip up the right one. `Occupant.key`
(`occupancy.py:29`) already records the owner of every occupied cell, so the
attribution is available; `route_net` just discards it on failure.

Two separable pieces, and the order matters:

* **2.2a — least-contested-column tie-break.** The report's own cheaper win: when
  several columns tie on cost, prefer the one appearing in the fewest *other* nets'
  feasible sets. Claimed to solve the left edge with no rip-up at all. The wrinkle:
  `route_net` is strictly per-net and has no view of other nets' feasible sets, so
  `route_nets` must precompute them and pass them down — a new parameter through the
  Phase 2a boundary.
  Scale **M** · Blast radius: **high.** This changes the chosen column on essentially
  every multi-row net, so every regression trace moves.

* **2.2b — attributed rip-up.** `route_net` returns the blocking occupant keys;
  `route_nets` rips up those specific nets and retries (PathFinder-style negotiation
  on top of the existing `NegotiatedCongestion`).
  Scale **L** · Scope: `net_router.py` return contract, `ripup.py` loop, `Congestion`
  interface · Blast radius: **high**, plus a real risk of runtime regression.

Do 2.2a first and measure; it may make 2.2b unnecessary at this board size.

### 2.3 Two-pin unlocked parts placed as jumper candidates during routing
Report §6's actual proposal, and its best insight: *a two-pin part between two nets is
a jumper with a body.* Pull-ups, series resistors and decoupling caps all want to sit
exactly where a jumper between their two nets' strips would go, so placing them
*during* routing as jumper candidates carrying a keep-out — rather than before it —
is what would make `locked=False` useful for the parts people most want to leave loose.

This is an architectural change: it breaks the Phase 1 → Phase 2 separation that
`placement.py` and `pipeline.py` are both written around, and a part placed during
routing has to feed back into `Result.placements` and the redraw closures.

* Scale **XL** · Scope: `pipeline.py`, `placement.py`, `net_router.py`, `result.py`
* Blast radius: contained to boards using `locked=False` on two-pin parts — but the
  internal contract change touches everything.
* Do **1.4** first. If charging congestion over pin boxes makes eight unlocked pull-ups
  place sanely, this drops from "necessary" to "nice", and can wait for real demand.

### 2.4 Internal ties honoured by the tree search
Report §8, second bullet, confirmed and worse than described. `route_net:246` derives
`rows = sorted(pins_by_row)` and a tree over k rows always has k-1 jumpers, so a
zero-length internal tie between two rows can never reduce the jumper count — which
forced them to split GND into three nets and 3V3 into two purely to satisfy the router.
Editing a netlist to work around solver geometry is the wrong reason to edit a netlist.

Related cliff found while checking this: `_objective_lb:433` does
`diam_lb = 0.0 if ctx.net_pairs else _diameter_lb(...)`, because the diameter bound is
invalid once weight-0 shortcuts exist. So **any net with an internal tie loses its
lower bound entirely** and its branch-and-bound degenerates to exhaustive search inside
`_NODE_BUDGET`. Multi-pin-ground modules — like the two StepSticks on their board —
hit this. Fixing the tie-aware tree search and fixing the bound are the same piece of
work.

* Scale **L** · Scope: `net_router.py` (row derivation, `_build_candidate`,
  `_topo_info`, `_diameter_lb`, `_objective_lb`)
* Blast radius: **high** on output *and* on runtime for every net with internal ties.

### 2.5 DESIGN view colouring from `autoroute()`
Report §10, confirmed on both sides: `README.md:70` and `docs/coordinates.md:72` both
promise "each net flood-filled in colour", and `views.py` sets `show_traces=True` for
DESIGN — but `_render_routing` (`autoroute.py:118`) draws jumpers and cuts only, never
calls `trace()`. So on an autorouted board the strips stay grey and connectivity has to
be checked by reading `Result.routing.strips`. Either the code or the docs is wrong;
the docs describe the more useful behaviour.

Fix is small — call `trace()` from one pin of each net with the net's colour — but:

* it **changes the rendered PDF of every autorouted board**, which is the entire point
  and also the largest regression-trace churn on this list;
* `trace()` walks `self.connections` per hole (`connectivity.py:66`), which is O(n²)
  in connection count and is called once per hole reached — on a 40-net, 28x22 board
  that is a real render-time cost worth measuring;
* `trace()` raises `TraceCollisionWarning` when two traced nets meet, so a correct
  autoroute could start emitting DRC warnings if strips abut in ways the flood-fill
  reads as contact. Check that before landing.

* Scale **S** to write, **M** with the perf and warning work · Scope: `autoroute.py`,
  `connectivity.py`
* Blast radius: **every autorouted board's rendered output.**

### 2.6 `stripboard explain board.py --net GND`
Report §1's CLI half. Blocked on a design question worth settling before writing code:
`cli.py` runs board files as subprocesses (`_render:83`) and only ever looks at the PDF
they leave behind, so it has no handle on `sb.last_result`. Three ways out — import the
board module in-process; have `project()` optionally dump the `Result` via the
`router.serialization` round-trip that already exists; or add a `sb.explain()` the
board file calls itself. The middle one reuses the most and keeps the subprocess
isolation.

* Scale **M** · Scope: `cli.py`, `project.py`, maybe `serialization.py`
* Blast radius: **low** — a new subcommand, and `sb.explain()` already covers the
  in-board case.
* `router.explain_net` already does the analysis; this is the plumbing to reach it
  from a board file the CLI only ever ran as a subprocess.

### 2.7 Lift "one strip per row per net"
Report §2's second, more ambitious half: a second strip on the same row is just another
node in the spanning tree. The report is right that `Strip` does not require uniqueness
and only `pins_by_row` does — but the assumption is load-bearing further out than that:
`strip_extent.py`'s docstring states "the router makes one strip per net per row" and its
per-row coordination relies on it, and `_topo_info`/`_diameter_lb` index by row.

* Scale **XL** · Scope: `net_router.py`, `strip_extent.py`, `validation.py`
* Blast radius: **the whole solver.**
* `row_conflicts` already reports this case precisely, which was most of the value.
  Leave the restriction until a board appears that genuinely needs a second strip.

---

## Suggested order

1. **1.8** — a correctness gap, and additive if the builder is opt-in.
2. **1.1** — the highest-value solver fix, and cheap because `fpair` already exists. The
   3V3 net that failed on an empty board is this one.
3. **1.4** — a two-line fix that may deliver most of what "routability-aware placement"
   was wanted for. Re-measure `locked=False` after it before committing to **2.3** at all.
4. **1.2**, then **1.7**, then **2.1** behind an opt-in flag.
5. **2.2a** and measure before touching **2.2b**.
6. **2.5** — worth doing, but it is the largest rendered-output change here, so land it
   alone and re-capture the regression set deliberately.
7. **2.4**, **2.3**, **2.7** — real work, none of it blocking.

Held deliberately: **1.3** (measure 1.2 first), **1.5** (check private designs for
`sip(pins=..., mod=...)` first), **1.9** (pick the weight from boards, not taste),
**2.3** (measure 1.4 first), **2.7** (the diagnostics capture the value at a fraction of
the cost).
