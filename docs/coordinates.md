# Coordinates, strips, and views

## The grid

A board is a 1-based integer grid of holes.

- **Columns** are numbers along `x`, starting at 1 on the left.
- **Rows** are letters along `y` — `'A'` is 1, `'Z'` is 26 — or plain integers. Both
  spellings work everywhere, so `sb.led(4, 'C')` and `sb.led(4, 3)` are the same call.
  Board sizes accept either too: `height='T'` is `height=20`.

Rows keep going past `'Z'` as integers; the letters simply run out.

## Copper runs horizontally

This is the one fact the whole library is organised around. On a real stripboard, the
copper is a set of parallel strips on the underside, and each strip runs the full width
of the board along one row.

So **two pins on the same row are already connected**, with no wire and no effort. Most
of the design work is deciding where that is wrong and breaking it:

```python
sb.cut(7, 'F')                  # sever row F between columns 6 and 7
sb.jumper(3, 'B', 3, 'F')       # a wire on the component side, bridging rows B and F
```

A `cut` removes copper. A `jumper` adds a wire across strips. Between them you can wire
any circuit — a `trace` then colours in whatever ended up connected, so you can check it:

```python
sb.trace(3, 'B')                # flood-fill the net reachable from hole (3, B)
```

`trace` walks the strip outwards from that hole, stops at cuts, hops along jumpers, and
shades every hole it reaches. If a net comes out the wrong shape, you have found your
mistake before soldering anything.

## Component handles

Every part builder returns a handle. It knows where the part's pins actually landed, in
board coordinates:

```python
u1 = sb.dip(6, 'F', 3, 4, '555', pins=['GND', 'TRIG', 'OUT', 'RESET',
                                       'CTRL', 'THRESH', 'DISCH', 'VCC'])
u1.pin('VCC')          # ('555', 'VCC') -- a reference the netlist understands
u1.pins['VCC']         # (9, 6)          -- where that hole is
```

Pin geometry comes from the same code that drew the part, so the autorouter and the PDF
can never disagree about where a leg goes. Numeric pins accept ints: `c1.pin(2)` is
`c1.pin('2')`.

Some parts also declare **keep-outs** — the board area their body covers, which the
router must not run a jumper through:

```python
sb.resist(18, 'R', '330', l=8).keepouts    # ((0, 1, 0, 7),) -- the holes it lies across
```

## The four views

A board gets drawn several times, because building one means looking at it from more
than one side. `begin_view` selects a preset; `triptych` renders the first three side by
side as a build sheet.

| View | What it shows | When you use it |
|---|---|---|
| `FRONT` | Components and jumpers, no strips | Placing and soldering parts |
| `BACK` | Strips and cuts, mirrored left-to-right, no components | Cutting tracks — this is the side you are looking at |
| `DESIGN` | Everything, with each net flood-filled in colour | Checking your work |
| `LABEL` | The silkscreen alone, black and white | Printing or laser-etching the board top |

`BACK` is mirrored because when you flip the board over to cut tracks, column 1 is on
your right. Getting that wrong is the classic stripboard mistake, so the library does it
for you.

## Units

Board coordinates are hole pitches. Real stripboard is 0.1 inch (2.54 mm) pitch, which is
what the exporters assume:

```python
sb.gen_gcode('board.nc', pitch_mm=2.54)     # the default
```

Page sizes passed to `StripBoard` are in tenths of an inch, so they are on the same scale
as the grid — a board 18 holes wide fits comfortably on a `page_width=30` page. `project()`
derives sensible page sizes from the board size, so you rarely set them by hand.
