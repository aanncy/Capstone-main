"""Diagram JSON -> draw.io XML, with a lane-aware layout and arrows routed around the boxes.

Layout   Steps go into columns by their place in the flow (longest path from the start, ignoring loops),
         each in its own lane. Steps of one lane that share a column are stacked in sub-rows.
Ports    Every arrow gets its own point on the side of the box that faces where it goes. The exits of a
         decision always leave from different sides, so Yes / No branches never share a line.
Routing  Arrows run only through the gaps between boxes (A* search), preferring few bends, few crossings
         and gaps that no other arrow uses yet.
Nudging  Arrows that share a gap are spread onto separate tracks, in the order with the fewest overlaps
         and crossings. Gaps that are too narrow are widened and everything is routed again.
Every point is written into the XML, so draw.io shows exactly this drawing."""
import bisect
import heapq
import html
import itertools
import textwrap

from .schema import Diagram

LANE_X, LANE_Y, HEADER = 40, 40, 32   # where the lanes start, and the width of their title strip
COL_GAP, PAD, ROW_GAP = 90, 40, 60    # starting size of the gaps arrows run in (grown when needed)
MARGIN, TRACK = 14, 14                # clearance kept around boxes; distance between parallel arrows
BEND, SHARE, CROSS = 60, 40, 50       # routing costs, in pixels of extra length
LINE_H = 16
# per type: characters per line, width, minimum height, height added around the text
SHAPES = {"start": (20, 160, 50, 20), "end": (20, 160, 50, 20), "task": (24, 180, 60, 24),
          "subprocess": (22, 190, 60, 24), "decision": (16, 190, 90, 56)}
ONE_PER_SIDE = {"start", "end", "decision"}  # shapes whose sides only have one clean attachment point
STYLES = {
    "start": "rounded=1;arcSize=50;html=1;whiteSpace=wrap;fillColor=#e0f2fe;strokeColor=#0369a1;",
    "end": "rounded=1;arcSize=50;html=1;whiteSpace=wrap;fillColor=#e0f2fe;strokeColor=#0369a1;",
    "task": "rounded=0;html=1;whiteSpace=wrap;fillColor=#ffffff;strokeColor=#334155;",
    "subprocess": "shape=process;html=1;whiteSpace=wrap;backgroundOutline=1;fillColor=#ffffff;strokeColor=#334155;",
    "decision": "rhombus;html=1;whiteSpace=wrap;fillColor=#fef9c3;strokeColor=#a16207;",
}
LANE = "swimlane;horizontal=0;startSize=32;html=1;whiteSpace=wrap;fillColor=#f8fafc;strokeColor=#94a3b8;fontStyle=1;"
EDGE = "edgeStyle=none;rounded=1;html=1;endArrow=block;endFill=1;jumpStyle=arc;jumpSize=10;strokeColor=#334155;"
LABEL = "labelBackgroundColor=#ffffff;fontSize=11;fontStyle=1;"
YES = {"yes", "y", "true", "approved", "pass", "passed", "valid", "ok"}
NO = {"no", "n", "false", "rejected", "fail", "failed", "invalid"}
OUT = {"R": (1, 0), "L": (-1, 0), "T": (0, -1), "B": (0, 1)}  # direction leaving each side of a box
MOVES = [(1, 0), (-1, 0), (0, 1), (0, -1)]  # A* directions; index ^ 1 is the opposite direction


def _e(s: str) -> str:
    return html.escape(s, quote=True)


def _r(v: float) -> float:
    return round(v, 2)


def _size(n) -> tuple[int, int]:
    chars, w, min_h, extra = SHAPES[n.type]
    lines = len(textwrap.wrap(n.label, chars)) or 1
    return w, max(min_h, lines * LINE_H + extra)


def _label_width(s: str) -> int:
    return 7 * len(s) + 10


class _Layout:
    def __init__(self, d: Diagram):
        self.nodes = {n.id: n for n in d.nodes}
        self.idx = {n.id: i for i, n in enumerate(d.nodes)}
        self.lanes = [l.id for l in d.lanes] + sorted({n.lane for n in d.nodes} - {l.id for l in d.lanes})
        self.edges = [e for e in d.edges if e.source in self.nodes and e.target in self.nodes]
        self.size = {i: _size(n) for i, n in self.nodes.items()}
        self.back = self._back_edges()
        self.rank = self._ranks()
        self.sub = self._subrows()
        self.ncol = max(self.rank.values(), default=-1) + 1
        self.nsub = {l: 1 + max([self.sub[i] for i, n in self.nodes.items() if n.lane == l], default=0) for l in self.lanes}
        self.row_order = {}
        for l in self.lanes:
            for s in range(self.nsub[l]):
                self.row_order[(l, s)] = len(self.row_order)
        self.colgap = [COL_GAP] * (self.ncol + 1)
        self.pads = {l: [PAD, PAD] for l in self.lanes}
        self.rowgap = {l: [ROW_GAP] * (self.nsub[l] - 1) for l in self.lanes}
        self._choose_sides()
        for k, e in enumerate(self.edges):  # room for a label on an arrow that leaves sideways
            side = self.side[(k, 0)]
            if e.label and side in "LR":
                c = self.rank[e.source] + (side == "R")
                self.colgap[c] = max(self.colgap[c], _label_width(e.label) + 24)
        self.shift = {}  # arrow end -> times its port was moved along the side to resolve a clash
        for _ in range(10):
            self._place()
            self._ports()
            self._route()
            if self._nudge():
                continue
            clashes = self._clashes()
            if not clashes:
                break
            for item in clashes:
                self.shift[item] = self.shift.get(item, 0) + 1

    # ---- structure -------------------------------------------------------------------------------------

    def _back_edges(self) -> set[int]:
        """Edges that close a loop (found by depth-first search from the start). Ignored when ranking."""
        out = {i: [] for i in self.nodes}
        for k, e in enumerate(self.edges):
            out[e.source].append(k)
        roots = sorted(self.nodes, key=lambda i: (self.nodes[i].type != "start", self.idx[i]))
        state, back = {}, set()
        for root in roots:
            if root in state:
                continue
            state[root] = 1
            stack = [(root, iter(out[root]))]
            while stack:
                v, it = stack[-1]
                for k in it:
                    w = self.edges[k].target
                    if state.get(w) == 1:
                        back.add(k)
                    elif w not in state:
                        state[w] = 1
                        stack.append((w, iter(out[w])))
                        break
                else:
                    state[v] = 2
                    stack.pop()
        return back

    def _ranks(self) -> dict[str, int]:
        """Column of each step: the longest chain of forward arrows leading to it."""
        fwd = [e for k, e in enumerate(self.edges) if k not in self.back]
        indeg = {i: 0 for i in self.nodes}
        for e in fwd:
            indeg[e.target] += 1
        rank = {i: 0 for i in self.nodes}
        ready = sorted((i for i in self.nodes if indeg[i] == 0), key=self.idx.get)
        while ready:
            v = ready.pop(0)
            for e in fwd:
                if e.source == v:
                    rank[e.target] = max(rank[e.target], rank[v] + 1)
                    indeg[e.target] -= 1
                    if indeg[e.target] == 0:
                        ready.append(e.target)
        return rank

    def _subrows(self) -> dict[str, int]:
        """Stack steps of one lane that share a column, keeping each near its predecessors' sub-row."""
        sub, taken = {}, {}
        preds = {i: [] for i in self.nodes}
        for k, e in enumerate(self.edges):
            if k not in self.back:
                preds[e.target].append(e.source)
        for v in sorted(self.nodes, key=lambda i: (self.rank[i], self.idx[i])):
            lane = self.nodes[v].lane
            near = [sub[p] for p in preds[v] if p in sub and self.nodes[p].lane == lane]
            want = round(sum(near) / len(near)) if near else 0
            used = taken.setdefault((lane, self.rank[v]), set())
            for s in sorted(range(len(used) + 1 + want), key=lambda s: (abs(s - want), s)):
                if s not in used:
                    break
            used.add(s)
            sub[v] = s
        return sub

    def _row(self, i: str) -> tuple[str, int]:
        return self.nodes[i].lane, self.sub[i]

    def _choose_sides(self):
        """Pick the box side every arrow leaves and enters by. Exits first; entries avoid exit sides."""
        def sign(v):
            return (v > 0) - (v < 0)

        def out_cost(side, k):
            e = self.edges[k]
            dy = sign(self.row_order[self._row(e.target)] - self.row_order[self._row(e.source)])
            if k in self.back:
                cost = {"B": 2 if dy >= 0 else 3, "T": 2 if dy < 0 else 3, "L": 4, "R": 6}[side]
            else:
                cost = {"R": 0 if dy == 0 else 1, "B": 1.5 if dy > 0 else 3 if dy == 0 else 5,
                        "T": 1.5 if dy < 0 else 3 if dy == 0 else 5, "L": 8}[side]
            return cost - (0.1 if side == "R" and e.label.strip().lower() in YES else 0)

        def in_cost(side, k):
            e = self.edges[k]
            dy = sign(self.row_order[self._row(e.source)] - self.row_order[self._row(e.target)])
            if k in self.back:
                return {"R": 1.5, "B": 2 if dy >= 0 else 3, "T": 2 if dy < 0 else 3, "L": 4}[side]
            return {"L": 0 if dy == 0 else 0.5, "T": 1.2 if dy < 0 else 4, "B": 1.2 if dy > 0 else 4, "R": 8}[side]

        self.side = {}
        for end, cost in ((0, out_cost), (1, in_cost)):
            for v, n in self.nodes.items():
                items = [k for k, e in enumerate(self.edges) if (e.source if end == 0 else e.target) == v]
                used = {self.side[(k, 0)] for k, e in enumerate(self.edges) if e.source == v} if end else set()
                cap = 1 if n.type in ONE_PER_SIDE else 3
                for k, s in zip(items, _assign(items, cost, cap, used)):
                    self.side[(k, end)] = s

    # ---- geometry --------------------------------------------------------------------------------------

    def _place(self):
        colw = [120] * self.ncol
        rowh = {r: 60 for r in self.row_order}
        for i, (w, h) in self.size.items():
            colw[self.rank[i]] = max(colw[self.rank[i]], w)
            rowh[self._row(i)] = max(rowh[self._row(i)], h)
        x, self.vchan, colx = LANE_X + HEADER, [], []
        for k in range(self.ncol + 1):
            self.vchan.append((x, x + self.colgap[k]))
            x += self.colgap[k]
            if k < self.ncol:
                colx.append(x)
                x += colw[k]
        self.width = x - LANE_X
        y, self.lane_y, self.hchan, rows = LANE_Y, {}, {}, {}
        for l in self.lanes:
            top = y
            y += self.pads[l][0]
            self.hchan[("top", l)] = (top, y)
            for s in range(self.nsub[l]):
                rows[(l, s)] = (y, y + rowh[(l, s)])
                y += rowh[(l, s)]
                if s < self.nsub[l] - 1:
                    self.hchan[("gap", l, s)] = (y, y + self.rowgap[l][s])
                    y += self.rowgap[l][s]
            self.hchan[("bot", l)] = (y, y + self.pads[l][1])
            y += self.pads[l][1]
            self.lane_y[l] = (top, y)
        self.box = {}
        for i, (w, h) in self.size.items():
            c, (r0, r1) = self.rank[i], rows[self._row(i)]
            cx, cy = colx[c] + colw[c] / 2, (r0 + r1) / 2
            self.box[i] = (cx - w / 2, cy - h / 2, w, h)

    def _hchan_of(self, i: str, side: str):
        lane, s = self._row(i)
        if side == "T":
            return ("top", lane) if s == 0 else ("gap", lane, s - 1)
        return ("bot", lane) if s == self.nsub[lane] - 1 else ("gap", lane, s)

    def _ports(self):
        """Spread the arrows on each box side evenly, ordered to avoid crossing each other.
        Two different arrows must not meet at the same point in a gap (one leaving the box on one side of it,
        one entering the box on the other side): if two arrows that cross over there, no order of their tracks
        keeps them apart. The entering arrow then moves along its side."""
        self._place_ports()
        seen, moved = {}, False
        for item in sorted(self.stub, key=lambda it: (it[1], it)):
            other = seen.setdefault(self.stub[item], item)
            if other[0] != item[0] and item[1] and item not in self.shift:
                self.shift[item] = 1
                moved = True
        if moved:
            self._place_ports()

    def _place_ports(self):
        groups = {}
        for (k, end), side in self.side.items():
            e = self.edges[k]
            groups.setdefault((e.target if end else e.source, side), []).append((k, end))
        self.port, self.stub = {}, {}
        for (v, side), items in groups.items():
            def along(item):
                k, end = item
                other = self.box[self.edges[k].source if end else self.edges[k].target]
                return (other[1] + other[3] / 2) if side in "LR" else (other[0] + other[2] / 2)
            items.sort(key=lambda it: (along(it), it))
            x, y, w, h = self.box[v]
            # keep the arrow that comes most head-on at the middle of the side (so it stays straight), others beside it
            span, mid = (h, y + h / 2) if side in "LR" else (w, x + w / 2)
            z = min(range(len(items)), key=lambda n: abs(along(items[n]) - mid))
            step = 18 if side in "LR" else 30
            fits = all(abs(n - z) * step <= span / 2 - 8 for n in range(len(items)))
            for n, item in enumerate(items):
                f = 0.5 + (n - z) * step / span if fits else (n + 1) / (len(items) + 1)
                if item in self.shift:  # step out of another arrow's way: entries move down/right, exits up/left
                    f += self.shift[item] * 10 * (1 if item[1] else -1) / span
                    f = min(max(f, 6 / span), 1 - 6 / span)
                fx, fy = {"L": (0, f), "R": (1, f), "T": (f, 0), "B": (f, 1)}[side]
                px, py = _r(round(x + w * fx)), _r(round(y + h * fy))  # whole pixels, so lines stay straight
                fx, fy = (px - x) / w, (py - y) / h
                self.port[item] = (side, px, py, fx, fy)
                if side in "LR":
                    a, b = self.vchan[self.rank[v] + (side == "R")]
                    self.stub[item] = (_r((a + b) / 2), py)
                else:
                    a, b = self.hchan[self._hchan_of(v, side)]
                    self.stub[item] = (px, _r((a + b) / 2))

    # ---- routing ---------------------------------------------------------------------------------------

    def _route(self):
        vline = {_r((a + b) / 2): k for k, (a, b) in enumerate(self.vchan)}
        hline = {_r((a + b) / 2): key for key, (a, b) in self.hchan.items()}
        xs = sorted(set(vline) | {p[0] for it, p in self.stub.items() if self.port[it][0] in "TB"})
        ys = sorted(set(hline) | {p[1] for it, p in self.stub.items() if self.port[it][0] in "LR"})
        self.vline, self.hline = vline, hline
        xi, yi = {x: i for i, x in enumerate(xs)}, {y: j for j, y in enumerate(ys)}
        hblk = [[False] * len(xs) for _ in ys]  # hblk[j][i]: segment (xs[i], ys[j]) -> (xs[i+1], ys[j])
        vblk = [[False] * len(ys) for _ in xs]  # vblk[i][j]: segment (xs[i], ys[j]) -> (xs[i], ys[j+1])
        for x, y, w, h in self.box.values():
            x0, y0, x1, y1 = x - MARGIN, y - MARGIN, x + w + MARGIN, y + h + MARGIN
            for j in range(bisect.bisect_right(ys, y0), bisect.bisect_left(ys, y1)):
                for i in range(max(0, bisect.bisect_left(xs, x0) - 1), min(len(xs) - 1, bisect.bisect_left(xs, x1))):
                    hblk[j][i] = True
            for i in range(bisect.bisect_right(xs, x0), bisect.bisect_left(xs, x1)):
                for j in range(max(0, bisect.bisect_left(ys, y0) - 1), min(len(ys) - 1, bisect.bisect_left(ys, y1))):
                    vblk[i][j] = True
        usage, points = {}, {}
        # owners of fixed (non-gap) stretches touching each point, per orientation. Only one arrow may attach such
        # a stretch at a point: two arrows meeting there from opposite sides can end up overlapping whatever
        # order their tracks get. Every arrow's own end stretches are reserved up front.
        attach = {"h": {}, "v": {}}
        for (k, end), (x, y) in self.stub.items():
            attach["h" if self.port[(k, end)][0] in "LR" else "v"].setdefault((xi[x], yi[y]), set()).add(k)
        self.routes = {}

        def stub_cell(item):
            x, y = self.stub[item]
            return xi[x], yi[y]

        def length(k):
            (a, b), (c, d) = self.stub[(k, 0)], self.stub[(k, 1)]
            return abs(a - c) + abs(b - d)

        for k in sorted(range(len(self.edges)), key=lambda k: (k in self.back, length(k), k)):
            s, t = stub_cell((k, 0)), stub_cell((k, 1))
            sd = MOVES.index(OUT[self.port[(k, 0)][0]])
            td = MOVES.index(OUT[self.port[(k, 1)][0]]) ^ 1  # entering a box moves against its side's outward direction
            path = _astar(xs, ys, hblk, vblk, usage, points, attach, k, vline, hline, s, sd, t, td)
            for a, b in zip(path, path[1:]):
                key = ("h", a[1], min(a[0], b[0])) if a[1] == b[1] else ("v", a[0], min(a[1], b[1]))
                usage[key] = usage.get(key, 0) + 1
                fixed = ys[a[1]] not in hline if key[0] == "h" else xs[a[0]] not in vline
                for p in (a, b):
                    points.setdefault(p, set()).add(key[0])
                    if fixed:
                        attach[key[0]].setdefault(p, set()).add(k)
            points.setdefault(s, set()).add("h" if sd < 2 else "v")
            points.setdefault(t, set()).add("h" if td < 2 else "v")
            pts = [self.port[(k, 0)][1:3]] + [(xs[i], ys[j]) for i, j in path] + [self.port[(k, 1)][1:3]]
            self.routes[k] = _segments(pts, vline, hline)

    # ---- nudging ---------------------------------------------------------------------------------------

    def _nudge(self) -> bool:
        """Give arrows sharing a gap their own tracks. Returns True if a gap had to grow (route again)."""
        grew = False
        for kind in ("V", "H"):
            chans = {}
            for k, segs in self.routes.items():
                for m, (orient, coord, chan) in enumerate(segs):
                    if chan is not None and chan[0] == kind:
                        lo, hi = _extent(self._points(k), m)
                        chans.setdefault(chan, []).append((lo, hi, k, m))
            for chan, segs in chans.items():
                size = self._chan_size(chan)
                center = _r(sum(self.vchan[chan[1]]) / 2) if kind == "V" else _r(sum(self.hchan[chan[1]]) / 2)
                segs.sort()
                comps, hi = [], None
                for seg in segs:
                    if hi is None or seg[0] > hi + 0.5:
                        comps.append([])
                    comps[-1].append(seg)
                    hi = seg[1] if hi is None or seg[0] > hi + 0.5 else max(hi, seg[1])
                for comp in comps:
                    n = len(comp)
                    if n < 2:
                        continue
                    need = (n + 1) * TRACK + 2 * MARGIN
                    if size < need:
                        self._grow(chan, need)
                        grew = True
                    step = min(TRACK, (size - 2 * MARGIN) / (n - 1))
                    self._order_tracks([(k, m) for _, _, k, m in comp], center, step)
        return grew

    def _clashes(self) -> set:
        """Arrow ends whose first or last stretch still overlaps or touches another arrow."""
        lines = {k: _lines(self._points(k), k) for k in self.routes}
        out, ks = set(), sorted(lines)
        for n, a in enumerate(ks):
            for b in ks[n + 1:]:
                for s1 in lines[a]:
                    for s2 in lines[b]:
                        if _conflicts([s1], [s2]) < 1000:
                            continue
                        ends = [(k, end) for k, s in ((a, s1), (b, s2))
                                for end, edge_seg in ((0, lines[k][0]), (1, lines[k][-1])) if s is edge_seg]
                        # prefer moving an entry on a box whose sides can hold several arrows
                        ends.sort(key=lambda it: (self._one_per_side(it), -it[1], it))
                        if ends:
                            out.add(ends[0])
        return out

    def _one_per_side(self, item) -> bool:
        e = self.edges[item[0]]
        return self.nodes[e.target if item[1] else e.source].type in ONE_PER_SIDE

    def _chan_size(self, chan) -> float:
        a, b = self.vchan[chan[1]] if chan[0] == "V" else self.hchan[chan[1]]
        return b - a

    def _grow(self, chan, need: float):
        if chan[0] == "V":
            self.colgap[chan[1]] = max(self.colgap[chan[1]], need)
            return
        key = chan[1]
        if key[0] == "gap":
            self.rowgap[key[1]][key[2]] = max(self.rowgap[key[1]][key[2]], need)
        else:
            side = 0 if key[0] == "top" else 1
            self.pads[key[1]][side] = max(self.pads[key[1]][side], need)

    def _points(self, k: int) -> list[tuple[float, float]]:
        segs = self.routes[k]
        pts = [self.port[(k, 0)][1:3]]
        for a, b in zip(segs, segs[1:]):
            pts.append((a[1], b[1]) if a[0] == "v" else (b[1], a[1]))
        return pts + [self.port[(k, 1)][1:3]]

    def _order_tracks(self, items, center: float, step: float):
        """Try the orders of these parallel segments and keep the one with the fewest overlaps and crossings."""
        n = len(items)
        moving = {}  # route -> indexes of the segments that move: the nudged ones and their neighbours
        for k, m in items:
            moving.setdefault(k, set()).update(i for i in (m - 1, m, m + 1) if 0 <= i < len(self.routes[k]))
        spread = (n + 1) * step
        x0 = y0 = float("inf")
        x1 = y1 = float("-inf")
        for k, ms in moving.items():
            pts = self._points(k)
            for m in ms:
                for x, y in pts[m:m + 2]:
                    x0, y0, x1, y1 = min(x0, x - spread), min(y0, y - spread), max(x1, x + spread), max(y1, y + spread)
        others = []  # only what lies near the moving segments can conflict with them
        for k in self.routes:
            pts = self._points(k)
            for m, (a, b) in enumerate(zip(pts, pts[1:])):
                if m in moving.get(k, ()) or a == b:
                    continue
                if max(a[0], b[0]) >= x0 and min(a[0], b[0]) <= x1 and max(a[1], b[1]) >= y0 and min(a[1], b[1]) <= y1:
                    others.append((k, a, b))

        def score(order) -> float:
            for pos, (k, m) in enumerate(order):
                seg = self.routes[k][m]
                self.routes[k][m] = (seg[0], _r(center + (pos - (n - 1) / 2) * step), seg[2])
            mine = []
            for k, ms in moving.items():
                pts = self._points(k)
                mine += [(k, pts[m], pts[m + 1]) for m in ms]
            return _conflicts(mine, others) + _conflicts(mine, mine) / 2

        if n <= 5:
            best = min(itertools.permutations(items), key=score)
        else:  # greedy: insert each segment where it causes the least trouble
            best = []
            for it in items:
                best = min((best[:p] + [it] + best[p:] for p in range(len(best) + 1)),
                           key=lambda o: score(o + [x for x in items if x not in o]))
        score(best)


def _assign(items, cost, cap, blocked):
    """Choose a side per item: lowest total cost, at most cap items per side, never a blocked side."""
    sides = [s for s in "RBTL" if s not in blocked] or list("RBTL")
    if not items:
        return []

    def total(combo):
        c = sum(cost(s, k) for s, k in zip(combo, items))
        return c + sum(20 * max(0, combo.count(s) - cap) for s in set(combo))

    if len(items) <= 5:
        return list(min(itertools.product(sides, repeat=len(items)), key=total))
    picked = []
    for k in items:
        picked.append(min(sides, key=lambda s: cost(s, k) + 20 * (picked.count(s) >= cap)))
    return picked


def _astar(xs, ys, hblk, vblk, usage, points, attach, k, vline, hline, s, sd, t, td) -> list[tuple[int, int]]:
    """Cheapest orthogonal path over the grid from s (arrived moving sd) to t (must arrive moving td)."""
    def h(i, j):
        return abs(xs[i] - xs[t[0]]) + abs(ys[j] - ys[t[1]])

    best, parent = {(s[0], s[1], sd): 0}, {}
    heap = [(h(*s), 0, s[0], s[1], sd)]
    while heap:
        f, g, i, j, d = heapq.heappop(heap)
        if d == -1:  # goal reached
            break
        if best.get((i, j, d), float("inf")) < g:
            continue
        if (i, j) == t and d != td ^ 1:
            done = g + (BEND if d != td else 0)
            if done < best.get((i, j, -1), float("inf")):
                best[(i, j, -1)] = done
                parent[(i, j, -1)] = (i, j, d)
                heapq.heappush(heap, (done, done, i, j, -1))
        for nd, (dx, dy) in enumerate(MOVES):
            if nd == d ^ 1:
                continue
            ni, nj = i + dx, j + dy
            if not (0 <= ni < len(xs) and 0 <= nj < len(ys)):
                continue
            if dy == 0:
                key, blocked, chan, step = ("h", j, min(i, ni)), hblk[j][min(i, ni)], ys[j] in hline, abs(xs[ni] - xs[i])
            else:
                key, blocked, chan, step = ("v", i, min(j, nj)), vblk[i][min(j, nj)], xs[i] in vline, abs(ys[nj] - ys[j])
            used = usage.get(key, 0)
            if blocked or (used and not chan):  # outside the gaps arrows may only use a line once
                continue
            if (ni, nj) != t and (ni, nj) in points and xs[ni] not in vline and ys[nj] not in hline:
                continue  # nor a point there: arrows meeting where they cannot be spread apart look joined
            if not chan:
                owners = attach[key[0]]
                if (owners.get((i, j), set()) | owners.get((ni, nj), set())) - {k}:
                    continue

            cost = g + step + (BEND if nd != d else 0) + SHARE * used
            if points.get((ni, nj), set()) - {key[0]}:
                cost += CROSS
            if cost < best.get((ni, nj, nd), float("inf")):
                best[(ni, nj, nd)] = cost
                parent[(ni, nj, nd)] = (i, j, d)
                heapq.heappush(heap, (cost + h(ni, nj), cost, ni, nj, nd))
    state = (t[0], t[1], -1)
    if state not in parent:
        return [s, t] if s == t else [s]
    path = []
    while state in parent:
        state = parent[state]
        path.append(state[:2])
    path.reverse()
    out = [path[0]]
    for p in path[1:]:
        if p != out[-1]:
            out.append(p)
    return out


def _segments(pts, vline, hline):
    """Polyline -> list of (orientation, coordinate, channel or None), with straight runs merged."""
    clean = [pts[0]]
    for p in pts[1:]:
        if p != clean[-1]:
            clean.append(p)
    segs = []
    for a, b in zip(clean, clean[1:]):
        orient, coord = ("h", a[1]) if a[1] == b[1] else ("v", a[0])
        if segs and segs[-1][0] == orient:
            continue
        chan = ("V", vline[coord]) if orient == "v" and coord in vline else \
               ("H", hline[coord]) if orient == "h" and coord in hline else None
        segs.append((orient, coord, chan))
    if not segs:
        segs.append(("h", clean[0][1], None))
    return segs


def _extent(pts, m):
    a, b = pts[m], pts[m + 1]
    return (min(a[1], b[1]), max(a[1], b[1])) if a[0] == b[0] else (min(a[0], b[0]), max(a[0], b[0]))


def _lines(pts, k):
    return [(k, a, b) for a, b in zip(pts, pts[1:]) if a != b]


def _conflicts(mine, others) -> float:
    """1000 per overlap or touching, 1 per crossing, between segments of different arrows."""
    total = 0.0
    for k1, a1, b1 in mine:
        h1 = a1[1] == b1[1]
        for k2, a2, b2 in others:
            if k1 == k2:
                continue
            h2 = a2[1] == b2[1]
            if h1 == h2:
                c = 1 if h1 else 0
                if abs(a1[c] - a2[c]) > 0.5:
                    continue
                o = 1 - c
                lo = max(min(a1[o], b1[o]), min(a2[o], b2[o]))
                hi = min(max(a1[o], b1[o]), max(a2[o], b2[o]))
                if hi >= lo - 0.5:
                    total += 1000
                continue
            hs, vs = ((a1, b1), (a2, b2)) if h1 else ((a2, b2), (a1, b1))
            x, y = vs[0][0], hs[0][1]
            x0, x1 = sorted((hs[0][0], hs[1][0]))
            y0, y1 = sorted((vs[0][1], vs[1][1]))
            if x0 - 0.5 <= x <= x1 + 0.5 and y0 - 0.5 <= y <= y1 + 0.5:
                inside = x0 + 0.5 < x < x1 - 0.5 and y0 + 0.5 < y < y1 - 0.5
                total += 1 if inside else 1000
    return total


def _label_offset(label: str, side: str, pts) -> tuple[float, float]:
    """Put a label beside the first stretch of its arrow, on the side the arrow does not turn to."""
    tw, th = _label_width(label), 14
    turn = None
    if len(pts) > 2:
        (x1, y1), (x2, y2) = pts[1], pts[2]
        turn = (x2 > x1) - (x2 < x1) if side in "TB" else (y2 > y1) - (y2 < y1)
    if side in "LR":
        dx = (8 + tw / 2) * (1 if side == "R" else -1)
        return dx, (th / 2 + 4) if turn == -1 else -(th / 2 + 4)
    dy = (8 + th / 2) * (1 if side == "B" else -1)
    return (-(tw / 2 + 6) if turn == 1 else tw / 2 + 6), dy


def to_drawio_xml(d: Diagram) -> str:
    lay = _Layout(d)
    names = {l.id: l.name for l in d.lanes}
    out = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
    for l in lay.lanes:
        top, bottom = lay.lane_y[l]
        out.append(
            f'<mxCell id="lane_{_e(l)}" value="{_e(names.get(l, l))}" style="{LANE}" vertex="1" parent="1">'
            f'<mxGeometry x="{LANE_X}" y="{top}" width="{lay.width}" height="{bottom - top}" as="geometry"/></mxCell>'
        )
    for n in d.nodes:
        x, y, w, h = lay.box[n.id]
        top = lay.lane_y[n.lane][0]
        out.append(
            f'<object label="{_e(n.label)}" id="{_e(n.id)}" source_ref="{_e(n.source_ref)}" confidence="{n.confidence}">'
            f'<mxCell style="{STYLES[n.type]}" vertex="1" parent="lane_{_e(n.lane)}">'
            f'<mxGeometry x="{_r(x - LANE_X)}" y="{_r(y - top)}" width="{w}" height="{h}" as="geometry"/></mxCell></object>'
        )
    for k, e in enumerate(lay.edges):
        (s_side, *_, sfx, sfy), (_, *_, tfx, tfy) = lay.port[(k, 0)], lay.port[(k, 1)]
        pts = lay._points(k)
        style = (f"{EDGE}exitX={sfx:.6g};exitY={sfy:.6g};exitDx=0;exitDy=0;exitPerimeter=0;"
                 f"entryX={tfx:.6g};entryY={tfy:.6g};entryDx=0;entryDy=0;entryPerimeter=0;")
        geo = '<mxGeometry relative="1" as="geometry">'
        label = e.label.strip()
        if label:
            color = "#15803d" if label.lower() in YES else "#b91c1c" if label.lower() in NO else "#334155"
            style += f"{LABEL}fontColor={color};"
            dx, dy = _label_offset(label, s_side, pts)
            geo = f'<mxGeometry x="-1" relative="1" as="geometry"><mxPoint x="{_r(dx)}" y="{_r(dy)}" as="offset"/>'
        waypoints = "".join(f'<mxPoint x="{_r(x)}" y="{_r(y)}"/>' for x, y in pts[1:-1])
        if waypoints:
            geo += f'<Array as="points">{waypoints}</Array>'
        out.append(
            f'<mxCell id="e{k + 1}" value="{_e(label)}" style="{style}" edge="1" parent="1" '
            f'source="{_e(e.source)}" target="{_e(e.target)}">{geo}</mxGeometry></mxCell>'
        )
    return (
        f'<mxfile host="app"><diagram id="d1" name="{_e(d.title)}"><mxGraphModel dx="1100" dy="700" grid="1" gridSize="10" '
        f'guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="0" pageScale="1" math="0" shadow="0"><root>'
        + "".join(out)
        + "</root></mxGraphModel></diagram></mxfile>"
    )
