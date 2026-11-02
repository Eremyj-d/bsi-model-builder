"""
bsi_model_builder.takeoff.pdfset — drawing-PDF ingestion for the geometry method (docs/BSI_STANDARDS.md §4).

What it does
------------
Opens one or more drawing PDFs and turns each page into page-level facts an estimator (or the LLM
interpretation stage) can act on:

* sheet number / title read from the title block,
* text spans with position, size and reading direction,
* thick structural line segments (beam sticks) merged collinear and split at column symbols,
* grid bubbles (circle + short tag) classified into the X axis (row across the top/bottom) and the
  Y axis (column down the left/right),
* a scale calibration (pt per foot) from the dimension strings between the bubbles,
* beam labels ("W12x26", "W16x31 [8]", "HSS5x5x5/16" …) matched to the nearest parallel line so the
  member's true length can be read from the line end points,
* a JSON-serialisable `page_report()` bundling all of it.

Coordinate frame (read this before using any number)
----------------------------------------------------
Every coordinate this module returns — text spans, lines, column symbols, bubbles, calibration origin and
member end points — is in the **displayed / upright page frame**: the page as a viewer shows it after the
PDF `/Rotate` entry is applied.  Origin top-left, x to the right, y DOWN, units PDF points (1/72 in).
This is the same frame `render_page()` rasterises, so a point (x, y) sits at pixel (x·dpi/72, y·dpi/72)
of the rendered PNG, and `page.rect` (not `page.mediabox`) gives the page size.

PyMuPDF reports `get_text("dict")` and `get_drawings()` in the UNROTATED page space; this module maps
every point, bbox and direction vector through `page.rotation_matrix` so text, lines and bubbles agree
with each other and with the pixmap.  Grid feet are then derived from that frame: X feet increase to
the right from the left-most X-axis bubble, Y feet increase UP the page (north) from the bottom-most
Y-axis bubble, i.e. `y_ft = (origin_y - y_pt) / pt_per_ft`.

Consequence: a page whose content is sideways in the viewer (e.g. a landscape plot saved with
/Rotate 90 so it displays portrait) is read sideways too — lengths and spacings are unaffected, but
the bubble rows/columns swap axes.  That is what the viewer shows and what the LLM sees in the PNG.

Limitations (known, by design)
------------------------------
* Raster-only pages (scans, or vector sheets flattened to an image) have no drawing paths and no text:
  `page_lines()` and `grid_bubbles()` return nothing; `has_vector` / `has_text` on `PageInfo` tell you.
  Use `render_page()` and hand the PNG to the vision stage instead.
* Grid bubbles are found as 4-bezier circles (what CAD exporters normally emit) or closed many-segment
  polylines that are square-ish with radius 6–20 pt.  Bubbles drawn as hexagons, as ellipses with very
  different radii, or as part of a form XObject that PyMuPDF flattens oddly, fall through to the
  text-only fallback (isolated short tags that line up) which is weaker.
* Beam sticks are matched by parallelism + proximity to the label.  Two collinear beams drawn tip-to-tip
  with no column symbol between them merge into one line; the per-label part assignment in `members()`
  recovers the common case (one label per bay) but a single long line with one label stays one member.
* Dimension strings are read only when they are a span of their own ("25'-0\"") lying in the band
  between two consecutive bubbles; stacked dimension strings or strings broken into several spans need
  `known_spacings` to be passed to `calibrate()`.
* Column symbols are small filled squares / quads (< 150 pt²).  W-column I-shapes drawn as outlines are
  not recognised as columns.
* Member labels are recognised by a steel-size regex (W, S, M, HP, C, MC, L, WT, MT, ST, HSS, PIPE,
  PL).  Rolled-shape families need an "x" dimension ("W12x26"), so column marks like "C1" are not
  mistaken for channels.  Text that PyMuPDF splits into several spans is not re-joined for labels.

Dependencies: pymupdf, numpy, stdlib only.
"""
from __future__ import annotations

import json
import math
import os
import re
import statistics
from dataclasses import asdict, dataclass
from typing import Any, Iterable

import numpy as np
import pymupdf

__all__ = [
    "DrawingSet", "PageInfo", "parse_ft_in", "find_ft_in", "merge_collinear", "split_at_points",
    "SIZE_RE", "SHEET_RE", "GRID_TAG_RE",
]

# --------------------------------------------------------------------------------------------- regexes
# Sheet numbers: S001, S-001, S1.03, S101A, A-301, M101, S-5010, C101, E201, SK-12, S2.1 …
SHEET_RE = re.compile(r"^(?P<disc>[A-Z]{1,2})(?P<sep>[-.]?)(?P<num>\d{1,4})(?P<dec>\.\d{1,2})?(?P<suf>[A-Z]?)$")
_SHEET_TOKEN_RE = re.compile(r"(?<![A-Z0-9])([A-Z]{1,2}[-.]?\d{2,4}(?:\.\d{1,2})?[A-Z]?)(?![A-Z0-9])")
_TITLE_LABEL_RE = re.compile(
    r"^\s*(SHEET|SHT|DATE|SCALE|DRAWN|CHECKED|CHK|DESIGNED|APPROVED|PROJECT|JOB|REV|FILE|PLOT|DWG|DRAWING|"
    r"ISSUE|CLIENT|OWNER|ENGINEER|ARCHITECT|CAD|SEAL|NOT FOR|PRELIMINARY|COPYRIGHT|©)\b", re.I)
_DATE_RE = re.compile(r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b")

# Grid bubble tags: A, B, AA, 1, 12, 1.5, A.3, B2 (letter+digit variants are common on additions).
GRID_TAG_RE = re.compile(r"^(?:[A-Z]{1,2}(?:\.\d)?|\d{1,2}(?:\.\d)?|[A-Z]\d{1,2}|\d{1,2}[A-Z])$")

# A number in a steel size: 12, 20.7, 3/4, 5 1/2, 0.280, and an optional ft-in tail (1'-0") for plates.
_NUM = r"\d+(?:\.\d+)?(?:\s?\d+/\d+|/\d+)?(?:\s?['′](?:\s?-\s?\d+(?:\s\d+/\d+)?\s?[\"″]?)?|\s?[\"″])?"
_X = r"\s?[xX×]\s?"
SIZE_RE = re.compile(
    r"(?<![A-Za-z0-9/.])"
    r"(?P<size>"
    r"(?P<mult>\(?\d{1,2}\)?\s?)?"
    r"(?:"
    r"(?P<fam_x>HSS|HP|WT|MT|ST|MC|W|S|M|C|L)\s?(?P<rest_x>" + _NUM + r"(?:" + _X + _NUM + r")+)"
    r"|"
    r"(?P<fam_pl>PL|PIPE)\s?(?P<rest_pl>" + _NUM + r"(?:" + _X + _NUM + r")*"
    r"(?:\s?(?:STD|XS|XXS|X-STRONG|XX-STRONG|SCH\.?\s?\d+))?)"
    r")"
    r")"
)
_TAG_BRACKET_RE = re.compile(r"^[\[\(]\s*([^\]\)]*?)\s*[\]\)]$")

# Feet-inches: 25'-0", 23'-6 1/2", 30'-0 3/8", 12'-3 15/16", 25', 6", 6 1/2", 25'-0
_FT_IN_FULL = re.compile(
    r"""^\s*[+-]?\s*
        (?:(?P<ft>\d+)\s*['′’]\s*)?                     # feet
        (?:[-–]\s*)?                                     # dash between feet and inches
        (?:
            (?P<in>\d+)(?:\s+(?P<fn>\d+)\s*/\s*(?P<fd>\d+))?   # inches + optional fraction
          | (?P<fn2>\d+)\s*/\s*(?P<fd2>\d+)                    # fraction only
        )?
        \s*(?P<inmark>["″”]|'')?\s*(?:\(?TYP\.?\)?)?\s*[±]?\s*$""", re.X | re.I)
_FT_IN_SEARCH = re.compile(
    r"""(?<![\d/])\d+\s*['′’]\s*(?:[-–]\s*\d+(?:\s+\d+\s*/\s*\d+)?\s*(?:["″”]|'')?)?  # 25'-0 1/2"
      | (?<![\d/'])\d+(?:\s+\d+\s*/\s*\d+)?\s*["″”](?!\s*[xX×])                       # 6 1/2"
    """, re.X)


def parse_ft_in(text: str | None) -> float | None:
    """'25\\'-0"' -> 25.0, '23\\'-6 1/2"' -> 23.5417, '30\\'-0 3/8"' -> 30.03125, '12\\'-3 15/16"' -> 12.328125.
    Requires a foot or inch mark; a bare number returns None.  Negative values keep their sign."""
    if not text:
        return None
    s = str(text).strip()
    m = _FT_IN_FULL.match(s)
    if not m:
        return None
    ft, inch = m.group("ft"), m.group("in")
    fn, fd = m.group("fn") or m.group("fn2"), m.group("fd") or m.group("fd2")
    has_mark = bool(m.group("inmark")) or ("'" in s or "′" in s or "’" in s)
    if ft is None and inch is None and fn is None:
        return None
    if not has_mark:
        return None
    if ft is None and inch is not None and not m.group("inmark"):
        return None     # "25" with only a foot-mark-less number is ambiguous
    total = float(ft or 0)
    if inch is not None:
        total += float(inch) / 12.0
    if fn is not None and fd and float(fd) != 0:
        total += float(fn) / float(fd) / 12.0
    if s.lstrip().startswith("-"):
        total = -total
    return total


def find_ft_in(text: str) -> list[tuple[str, float]]:
    """Every feet-inch string inside a longer text, with its parsed value."""
    out = []
    for m in _FT_IN_SEARCH.finditer(text or ""):
        v = parse_ft_in(m.group(0))
        if v is not None:
            out.append((m.group(0).strip(), v))
    return out


# --------------------------------------------------------------------------------------------- geometry
def _dist(a, b) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _unit(dx: float, dy: float) -> tuple[float, float]:
    n = math.hypot(dx, dy)
    return (dx / n, dy / n) if n else (0.0, 0.0)


def _round(v: Any, nd: int = 3) -> Any:
    """Recursively make a structure JSON-serialisable: tuples -> lists, numpy -> python, floats rounded."""
    if isinstance(v, dict):
        return {str(k): _round(x, nd) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_round(x, nd) for x in v]
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return round(f, nd) if math.isfinite(f) else None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, np.ndarray):
        return _round(v.tolist(), nd)
    return v


def merge_collinear(lines: list[dict], tol_angle_deg: float = 1.0, tol_offset_pt: float = 1.0,
                    max_gap_pt: float = 3.0) -> list[dict]:
    """Merge collinear segments that touch / overlap / sit within `max_gap_pt` of each other into longer ones.

    Input/output records use the `page_lines()` shape (p1, p2, width, color, length …).  Each merged record
    carries `parts` (indices into the input list) and `n_parts`; width is the maximum of its parts.
    Grouping is bucketed on (angle, perpendicular offset) so it stays O(n) on busy sheets.
    """
    if not lines:
        return []
    recs = []
    for i, ln in enumerate(lines):
        (x1, y1), (x2, y2) = ln["p1"], ln["p2"]
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy)
        if L <= 1e-6:
            continue
        ang = math.degrees(math.atan2(dy, dx)) % 180.0          # [0, 180)
        ux, uy = math.cos(math.radians(ang)), math.sin(math.radians(ang))
        c = ux * y1 - uy * x1                                    # signed perpendicular offset of the line
        recs.append((i, ang, ux, uy, c, (x1, y1), (x2, y2)))
    n_ang = max(1, int(round(180.0 / tol_angle_deg)))
    buckets: dict[tuple[int, int], list[int]] = {}
    groups: list[dict] = []                                      # {ang, u, c, base, members:[rec idx]}

    def keys_for(ang, c):
        ai = int(round(ang / tol_angle_deg))
        ci = int(round(c / tol_offset_pt))
        out = []
        for da in (-1, 0, 1):
            a2 = ai + da
            flip = False
            if a2 < 0:
                a2 += n_ang; flip = True
            elif a2 >= n_ang:
                a2 -= n_ang; flip = True
            c2 = -c if flip else c
            ci2 = int(round(c2 / tol_offset_pt))
            for dc in (-1, 0, 1):
                out.append((a2, ci2 + dc))
        return out

    def perp_dist(g, p):
        ux, uy = g["u"]
        bx, by = g["base"]
        return abs(ux * (p[1] - by) - uy * (p[0] - bx))

    for ridx, (i, ang, ux, uy, c, p1, p2) in enumerate(recs):
        chosen = None
        for key in keys_for(ang, c):
            for gi in buckets.get(key, ()):
                g = groups[gi]
                dang = abs(g["ang"] - ang)
                dang = min(dang, 180.0 - dang)
                if dang > tol_angle_deg:
                    continue
                if perp_dist(g, p1) <= tol_offset_pt and perp_dist(g, p2) <= tol_offset_pt:
                    chosen = gi
                    break
            if chosen is not None:
                break
        if chosen is None:
            chosen = len(groups)
            groups.append({"ang": ang, "u": (ux, uy), "c": c, "base": p1, "members": []})
            ai = int(round(ang / tol_angle_deg)) % n_ang
            buckets.setdefault((ai, int(round(c / tol_offset_pt))), []).append(chosen)
        groups[chosen]["members"].append(ridx)

    merged: list[dict] = []
    for g in groups:
        ux, uy = g["u"]
        bx, by = g["base"]
        ivs = []
        for ridx in g["members"]:
            i, ang, _, _, _, p1, p2 = recs[ridx]
            t1 = ux * (p1[0] - bx) + uy * (p1[1] - by)
            t2 = ux * (p2[0] - bx) + uy * (p2[1] - by)
            ivs.append((min(t1, t2), max(t1, t2), i))
        ivs.sort()
        cur = [ivs[0][0], ivs[0][1], [ivs[0][2]]]
        runs = []
        for a, b, i in ivs[1:]:
            if a <= cur[1] + max_gap_pt:
                cur[1] = max(cur[1], b)
                cur[2].append(i)
            else:
                runs.append(cur)
                cur = [a, b, [i]]
        runs.append(cur)
        for a, b, idxs in runs:
            src = lines[idxs[0]]
            p1 = (bx + ux * a, by + uy * a)
            p2 = (bx + ux * b, by + uy * b)
            merged.append({
                "p1": p1, "p2": p2, "length": b - a,
                "width": max((lines[i].get("width") or 0.0) for i in idxs),
                "color": src.get("color"), "dashes": src.get("dashes"),
                "angle_deg": g["ang"], "parts": sorted(idxs), "n_parts": len(idxs),
            })
    return merged


def split_at_points(lines: list[dict], points: Iterable[tuple[float, float]], tol_pt: float = 3.0,
                    end_margin_pt: float = 3.0) -> list[dict]:
    """Split lines wherever a point (e.g. a column symbol centre) lies ON the line, away from its ends.

    Beams drawn tip-to-tip across a column merge into one stick; the column symbol marks the support."""
    pts = list(points)
    if not pts or not lines:
        return list(lines)
    out = []
    for ln in lines:
        (x1, y1), (x2, y2) = ln["p1"], ln["p2"]
        L = ln.get("length") or _dist(ln["p1"], ln["p2"])
        if L <= 2 * end_margin_pt:
            out.append(ln); continue
        ux, uy = _unit(x2 - x1, y2 - y1)
        cuts = []
        for (px, py) in pts:
            t = ux * (px - x1) + uy * (py - y1)
            d = abs(ux * (py - y1) - uy * (px - x1))
            if d <= tol_pt and end_margin_pt < t < L - end_margin_pt:
                cuts.append(t)
        if not cuts:
            out.append(ln); continue
        ts = [0.0] + sorted(cuts) + [L]
        for a, b in zip(ts, ts[1:]):
            if b - a < 1e-6:
                continue
            rec = dict(ln)
            rec["p1"] = (x1 + ux * a, y1 + uy * a)
            rec["p2"] = (x1 + ux * b, y1 + uy * b)
            rec["length"] = b - a
            rec["split_at_column"] = True
            out.append(rec)
    return out


# --------------------------------------------------------------------------------------------- page info
@dataclass
class PageInfo:
    file: str
    page_index: int                 # index into DrawingSet.pages (global across files)
    file_page: int                  # 0-based page index inside `file`
    width_pt: float                 # displayed (rotated) size
    height_pt: float
    rotation: int
    sheet_number: str
    sheet_title: str
    has_vector: bool                # > 50 drawing paths
    has_text: bool
    text_chars: int
    image_count: int
    path_count: int

    def asdict(self) -> dict:
        return asdict(self)


class DrawingSet:
    """One or more drawing PDFs opened together; every page gets a global `page_index`.

    All coordinates are in the displayed / upright page frame (see the module docstring)."""

    VECTOR_MIN_PATHS = 50
    TITLE_REGION = (0.75, 0.80)     # lower-right x-fraction, bottom y-fraction searched first for the sheet number

    def __init__(self, paths: list[str] | str):
        if isinstance(paths, (str, os.PathLike)):
            paths = [paths]
        self.paths = [str(p) for p in paths]
        self._docs: list[pymupdf.Document] = []
        self._pages: list[tuple[int, int]] = []        # (doc idx, page idx)
        self.pages: list[PageInfo] = []
        self._cache: dict[tuple, Any] = {}
        for di, p in enumerate(self.paths):
            doc = pymupdf.open(p)
            self._docs.append(doc)
            for pi in range(doc.page_count):
                self._pages.append((di, pi))
        for gi in range(len(self._pages)):
            self.pages.append(self._page_info(gi))

    # ---- lifecycle
    def close(self):
        for d in self._docs:
            try:
                d.close()
            except Exception:
                pass
        self._docs = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __len__(self):
        return len(self.pages)

    # ---- internals
    def _page(self, page_index: int) -> pymupdf.Page:
        di, pi = self._pages[page_index]
        return self._docs[di][pi]

    @staticmethod
    def _xf_point(p, m: pymupdf.Matrix) -> tuple[float, float]:
        q = pymupdf.Point(p[0], p[1]) * m
        return (float(q.x), float(q.y))

    @staticmethod
    def _xf_vec(v, m: pymupdf.Matrix) -> tuple[float, float]:
        return _unit(m.a * v[0] + m.c * v[1], m.b * v[0] + m.d * v[1])

    @staticmethod
    def _xf_rect(r, m: pymupdf.Matrix) -> tuple[float, float, float, float]:
        rr = pymupdf.Rect(r) * m
        return (float(rr.x0), float(rr.y0), float(rr.x1), float(rr.y1))

    def _raw_text(self, page_index: int) -> dict:
        key = ("rawtext", page_index)
        if key not in self._cache:
            page = self._page(page_index)
            m = page.rotation_matrix
            spans, lines = [], []
            d = page.get_text("dict")
            for b in d.get("blocks", []):
                if b.get("type", 0) != 0:
                    continue
                for ln in b.get("lines", []):
                    ldir = self._xf_vec(ln.get("dir", (1.0, 0.0)), m)
                    line_spans = []
                    for sp in ln.get("spans", []):
                        txt = sp.get("text", "")
                        if not txt.strip():
                            continue
                        rec = {
                            "text": txt, "bbox": self._xf_rect(sp["bbox"], m),
                            "origin": self._xf_point(sp.get("origin", sp["bbox"][:2]), m),
                            "size": float(sp.get("size", 0.0)), "dir": ldir, "font": sp.get("font", ""),
                            "flags": int(sp.get("flags", 0)), "line": len(lines),
                        }
                        spans.append(rec)
                        line_spans.append(rec)
                    if line_spans:
                        bb = self._xf_rect(ln["bbox"], m)
                        lines.append({"text": " ".join(s["text"].strip() for s in line_spans).strip(),
                                      "bbox": bb, "dir": ldir, "size": max(s["size"] for s in line_spans),
                                      "spans": [spans.index(s) for s in line_spans]})
            self._cache[key] = {"spans": spans, "lines": lines}
        return self._cache[key]

    def _raw_drawings(self, page_index: int) -> list[dict]:
        key = ("drawings", page_index)
        if key not in self._cache:
            self._cache[key] = self._page(page_index).get_drawings()
        return self._cache[key]

    # ---- page info / sheet detection
    def _page_info(self, gi: int) -> PageInfo:
        di, pi = self._pages[gi]
        page = self._docs[di][pi]
        drawings = self._raw_drawings(gi)
        raw = self._raw_text(gi)
        text_chars = sum(len(s["text"].strip()) for s in raw["spans"])
        try:
            image_count = len(page.get_images(full=True))
        except Exception:
            image_count = 0
        number, title = self._detect_sheet(gi)
        return PageInfo(file=self.paths[di], page_index=gi, file_page=pi, width_pt=float(page.rect.width),
                        height_pt=float(page.rect.height), rotation=int(page.rotation), sheet_number=number,
                        sheet_title=title, has_vector=len(drawings) > self.VECTOR_MIN_PATHS, has_text=text_chars > 0,
                        text_chars=text_chars, image_count=image_count, path_count=len(drawings))

    def _detect_sheet(self, page_index: int) -> tuple[str, str]:
        page = self._page(page_index)
        W, H = float(page.rect.width), float(page.rect.height)
        raw = self._raw_text(page_index)
        spans, lines = raw["spans"], raw["lines"]
        fx, fy = self.TITLE_REGION
        corner = (W, H)

        def centre(bb):
            return ((bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0)

        def in_region(bb):
            cx, cy = centre(bb)
            return cx >= fx * W and cy >= fy * H

        def digits(s):
            return sum(ch.isdigit() for ch in s)

        def anchored(sp):
            t = sp["text"].strip().upper()
            return t if SHEET_RE.match(t) else None

        def token(sp):
            t = sp["text"].strip().upper()
            if _TITLE_LABEL_RE.match(t) and not t.startswith(("SHEET", "SHT", "DWG", "DRAWING")):
                return None
            toks = _SHEET_TOKEN_RE.findall(t)
            return toks[-1] if toks else None

        cands: list[tuple[float, float, str, dict]] = []     # (rank, dist, number, span)
        for pass_no, (region_only, fn) in enumerate(((True, anchored), (True, token), (False, anchored), (False, token))):
            for sp in spans:
                if region_only and not in_region(sp["bbox"]):
                    continue
                num = fn(sp)
                if not num or digits(num) < 2 and not (sp["size"] >= 14):
                    continue
                cx, cy = centre(sp["bbox"])
                dist = math.hypot(corner[0] - cx, corner[1] - cy) / math.hypot(W, H)
                # inside the title region: nearest to the corner wins; elsewhere: biggest text, then nearest corner
                rank = dist if region_only else (-sp["size"] + dist)
                cands.append((pass_no, rank, num, sp))
            if cands:
                break
        if not cands:
            return "", ""
        cands.sort(key=lambda c: (c[0], c[1]))
        _, _, number, nsp = cands[0]
        ncx, ncy = centre(nsp["bbox"])
        # title: the longest nearby text line that is not the number and not a title-block label
        best = None
        for radius in (150.0, 300.0, 600.0):
            pool = []
            for ln in lines:
                t = ln["text"].strip()
                if not t or len(t) < 3 or SHEET_RE.match(t.upper()) or t.upper() == number:
                    continue
                if _TITLE_LABEL_RE.match(t) or _DATE_RE.search(t) or digits(t) > len(t) / 2:
                    continue
                if nsp["line"] == lines.index(ln):
                    continue
                lcx, lcy = centre(ln["bbox"])
                if math.hypot(lcx - ncx, lcy - ncy) > radius:
                    continue
                if radius > 150.0 and lcy > ncy:        # on a wider search only look above the number
                    continue
                pool.append((len(t), ln["size"], t))
            if pool:
                pool.sort(reverse=True)
                best = pool[0][2]
                break
        return number, (best or "")

    # ---- summaries
    def summary(self) -> list[dict]:
        return [p.asdict() for p in self.pages]

    def summary_table(self) -> str:
        rows = [("#", "FILE", "PG", "SHEET", "TITLE", "SIZE (in)", "ROT", "VEC", "PATHS", "TEXT", "IMG")]
        for p in self.pages:
            rows.append((str(p.page_index), os.path.basename(p.file), str(p.file_page + 1), p.sheet_number or "?",
                         (p.sheet_title or "")[:40], f"{p.width_pt / 72:.1f}x{p.height_pt / 72:.1f}", str(p.rotation),
                         "Y" if p.has_vector else "n", str(p.path_count), str(p.text_chars), str(p.image_count)))
        widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
        out = []
        for ri, r in enumerate(rows):
            out.append("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)).rstrip())
            if ri == 0:
                out.append("  ".join("-" * w for w in widths))
        return "\n".join(out)

    def find_sheet(self, sheet_number: str) -> int | None:
        sn = sheet_number.strip().upper()
        for p in self.pages:
            if p.sheet_number.upper() == sn:
                return p.page_index
        return None

    # ---- rendering
    def render_page(self, page_index: int, dpi: int = 150, clip: tuple | None = None, out_png: str | None = None):
        """Rasterise the page upright (page rotation honoured).  `clip` = (x0, y0, x1, y1) in the displayed frame.
        Returns PNG bytes, or the path when `out_png` is given."""
        page = self._page(page_index)
        kw: dict[str, Any] = {"dpi": dpi}
        if clip is not None:
            kw["clip"] = pymupdf.Rect(*clip)
        pix = page.get_pixmap(**kw)
        if out_png:
            pix.save(out_png)
            return out_png
        return pix.tobytes("png")

    # ---- text
    def page_text(self, page_index: int) -> list[dict]:
        """Text spans: text, bbox, origin, size, dir (unit reading-direction vector), font, flags, line (index)."""
        return [dict(s) for s in self._raw_text(page_index)["spans"]]

    def page_text_lines(self, page_index: int) -> list[dict]:
        """Text lines (spans sharing a baseline joined): text, bbox, dir, size, spans (indices into page_text)."""
        return [dict(l) for l in self._raw_text(page_index)["lines"]]

    # ---- vector content
    def page_lines(self, page_index: int, min_width: float = 0.85) -> dict:
        """Line segments and column symbols from the page's vector paths, in the displayed frame.

        Returns {"lines": [...], "column_symbols": [...], "n_paths": int, "n_segments_all": int}.
        A line: p1, p2, width, color, dashes, length, kind ("l" | "re-edge" | "re-thin" | "qu-edge").
        Rectangle edges of stroked rects are lines; filled rects with one side < 2 pt are a line along their long
        axis (width = the short side); filled rects / quads / 4-segment polygons < 150 pt² are column symbols.
        `min_width` filters the lines (None or 0 keeps everything); column symbols are never filtered."""
        key = ("lines", page_index, min_width)
        if key in self._cache:
            return self._cache[key]
        page = self._page(page_index)
        m = page.rotation_matrix
        lines: list[dict] = []
        symbols: list[dict] = []
        n_all = 0

        def add_line(p1, p2, width, color, dashes, kind):
            nonlocal n_all
            n_all += 1
            if min_width and (width or 0.0) < min_width:
                return
            p1, p2 = self._xf_point(p1, m), self._xf_point(p2, m)
            L = _dist(p1, p2)
            if L <= 1e-6:
                return
            lines.append({"p1": p1, "p2": p2, "width": float(width or 0.0),
                          "color": list(color) if color is not None else None, "dashes": dashes,
                          "length": L, "kind": kind})

        def add_symbol(rect, fill, kind):
            x0, y0, x1, y1 = rect
            symbols.append({"cx": (x0 + x1) / 2.0, "cy": (y0 + y1) / 2.0, "w": x1 - x0, "h": y1 - y0,
                            "area": (x1 - x0) * (y1 - y0), "fill": list(fill) if fill is not None else None,
                            "kind": kind})

        for d in self._raw_drawings(page_index):
            typ = d.get("type") or ""
            stroked, filled = "s" in typ, "f" in typ
            width = d.get("width") or 0.0
            color, fill, dashes = d.get("color"), d.get("fill"), d.get("dashes")
            items = d.get("items", [])
            # filled 4-segment polygon: a square column symbol, or a thick line that the exporter drew as a
            # filled sliver (Revit / Bluebeam style) -> line along its long axis, width = the short side
            if filled and items and all(it[0] == "l" for it in items) and len(items) in (3, 4, 5):
                rr = self._xf_rect(d["rect"], m)
                if (rr[2] - rr[0]) * (rr[3] - rr[1]) < 150.0 and min(rr[2] - rr[0], rr[3] - rr[1]) >= 2.0:
                    add_symbol(rr, fill, "poly")
                    if not stroked:
                        continue
                elif len(items) >= 4:
                    pts = [self._xf_point(it[1], m) for it in items[:4]]
                    e = [_dist(pts[i], pts[(i + 1) % 4]) for i in range(4)]
                    short, long_ = min(e), max(e)
                    if short < 2.0 and long_ >= 2.0 and abs(e[0] - e[2]) < 1.0 and abs(e[1] - e[3]) < 1.0:
                        i = e.index(long_)                                    # the long edge and its opposite
                        a1, a2 = pts[i], pts[(i + 1) % 4]
                        b2, b1 = pts[(i + 2) % 4], pts[(i + 3) % 4]
                        n_all += 1
                        if not (min_width and short < min_width):
                            p1 = ((a1[0] + b1[0]) / 2, (a1[1] + b1[1]) / 2)
                            p2 = ((a2[0] + b2[0]) / 2, (a2[1] + b2[1]) / 2)
                            lines.append({"p1": p1, "p2": p2, "width": short, "color": list(fill) if fill else None,
                                          "dashes": None, "length": _dist(p1, p2), "kind": "poly-thin"})
                        if not stroked:
                            continue
            for it in items:
                op = it[0]
                if op == "l":
                    if stroked:
                        add_line(it[1], it[2], width, color, dashes, "l")
                elif op == "re":
                    rr = self._xf_rect(it[1], m)
                    x0, y0, x1, y1 = rr
                    w, h = x1 - x0, y1 - y0
                    if stroked:
                        for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
                            add_line(a, b, width, color, dashes, "re-edge")
                    if filled:
                        if min(w, h) < 2.0 and max(w, h) >= 2.0:
                            if w >= h:
                                add_line((x0, (y0 + y1) / 2), (x1, (y0 + y1) / 2), min(w, h), fill, None, "re-thin")
                            else:
                                add_line(((x0 + x1) / 2, y0), ((x0 + x1) / 2, y1), min(w, h), fill, None, "re-thin")
                        elif w * h < 150.0:
                            add_symbol(rr, fill, "re")
                elif op == "qu":
                    q = it[1]
                    pts = [(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.lr.x, q.lr.y), (q.ll.x, q.ll.y)]
                    if stroked:
                        for a, b in zip(pts, pts[1:] + pts[:1]):
                            add_line(a, b, width, color, dashes, "qu-edge")
                    if filled:
                        rr = self._xf_rect(q.rect, m)
                        if (rr[2] - rr[0]) * (rr[3] - rr[1]) < 150.0:
                            add_symbol(rr, fill, "qu")
                # "c" (bezier) items are curves: handled by grid_bubbles(), ignored here
        res = {"lines": lines, "column_symbols": symbols, "n_paths": len(self._raw_drawings(page_index)),
               "n_segments_all": n_all}
        self._cache[key] = res
        return res

    def merged_lines(self, page_index: int, min_width: float = 0.85, split_at_columns: bool = True) -> list[dict]:
        """Thick lines merged collinear and (optionally) split at column-symbol centres."""
        pl = self.page_lines(page_index, min_width=min_width)
        merged = merge_collinear(pl["lines"])
        if split_at_columns and pl["column_symbols"]:
            merged = split_at_points(merged, [(s["cx"], s["cy"]) for s in pl["column_symbols"]], tol_pt=3.0)
        return merged

    # ---- grid bubbles
    def _circles(self, page_index: int) -> list[dict]:
        """Circle-like closed paths with radius 6–20 pt: 4-bezier circles or many-segment polylines."""
        page = self._page(page_index)
        m = page.rotation_matrix
        out = []
        for d in self._raw_drawings(page_index):
            items = d.get("items", [])
            if not items:
                continue
            ops = [it[0] for it in items]
            if all(o == "c" for o in ops) and len(ops) >= 2:
                kind = "bezier"
            elif all(o == "l" for o in ops) and len(ops) >= 8:
                kind = "polyline"
            else:
                continue
            first = items[0][1]
            last = items[-1][-1]
            closed = bool(d.get("closePath")) or _dist((first.x, first.y), (last.x, last.y)) <= 1.5
            if not closed:
                continue
            x0, y0, x1, y1 = self._xf_rect(d["rect"], m)
            w, h = x1 - x0, y1 - y0
            if w <= 0 or h <= 0 or abs(w - h) > max(1.5, 0.15 * max(w, h)):
                continue
            r = (w + h) / 4.0
            if not (6.0 <= r <= 20.0):
                continue
            out.append({"cx": (x0 + x1) / 2.0, "cy": (y0 + y1) / 2.0, "r": r, "kind": kind})
        # de-duplicate concentric / repeated rings
        uniq: list[dict] = []
        for c in out:
            if any(_dist((c["cx"], c["cy"]), (u["cx"], u["cy"])) <= 2.0 for u in uniq):
                continue
            uniq.append(c)
        return uniq

    def grid_bubbles(self, page_index: int, row_tol_pt: float | None = None) -> dict:
        """Grid bubbles = circle (r 6–20 pt) with a single short tag inside (A, AA, 1, 12, 1.5, A.3 …).

        Returns {"x_axis": {tag: [cx, cy]}, "y_axis": {tag: [cx, cy]}, "unassigned": {...},
                 "bubbles": [{tag, cx, cy, r, kind, gridline, beside, axis}], "markers": [...],
                 "method": "circles" | "polylines" | "text-only" | "none", "page_index": n}.
        X-axis bubbles share a horizontal row (tags across the top / bottom); Y-axis bubbles share a vertical column
        (down the left / right).  Duplicates of a tag (both sides of the plan) are averaged.  A circle with a title
        right beside it and no line touching it is a detail / section marker and is listed under "markers" instead.
        Falls back to isolated short tags that line up when no circles are drawn."""
        raw = self._raw_text(page_index)
        spans, text_lines = raw["spans"], raw["lines"]
        tags = []
        for i, s in enumerate(spans):
            t = s["text"].strip().upper()
            if GRID_TAG_RE.match(t):
                bb = s["bbox"]
                tags.append({"i": i, "tag": t, "cx": (bb[0] + bb[2]) / 2, "cy": (bb[1] + bb[3]) / 2,
                             "w": bb[2] - bb[0], "h": bb[3] - bb[1], "size": s["size"]})
        circles = self._circles(page_index)
        all_segs = self.page_lines(page_index, min_width=0)["lines"] if circles else []

        def has_gridline(c) -> bool:
            """A line ends at the circle edge or runs through the circle (the grid line)."""
            cx, cy, r = c["cx"], c["cy"], c["r"]
            for ln in all_segs:
                (x1, y1), (x2, y2) = ln["p1"], ln["p2"]
                if _dist((x1, y1), (cx, cy)) <= r + 4 or _dist((x2, y2), (cx, cy)) <= r + 4:
                    return True
                L = ln["length"]
                if L < 2 * r:
                    continue
                ux, uy = _unit(x2 - x1, y2 - y1)
                t = ux * (cx - x1) + uy * (cy - y1)
                if 0 <= t <= L and abs(ux * (cy - y1) - uy * (cx - x1)) <= 0.5 * r:
                    return True
            return False

        def marker_text(c) -> str:
            """Title text sitting right beside the circle = detail / section marker, not a grid bubble."""
            cx, cy, r = c["cx"], c["cy"], c["r"]
            for ln in text_lines:
                t = ln["text"].strip()
                if len(t) < 3 or GRID_TAG_RE.match(t.upper()) or parse_ft_in(t) is not None:
                    continue
                x0, y0, x1, y1 = ln["bbox"]
                if x0 <= cx <= x1 and y0 <= cy <= y1:
                    continue
                gx = max(x0 - (cx + r), (cx - r) - x1, 0.0)      # gap between circle box and text box
                gy = max(y0 - (cy + r), (cy - r) - y1, 0.0)
                if (gx <= 2.5 * r and gy == 0.0) or (gy <= 2.5 * r and gx == 0.0):
                    return t
            return ""

        bubbles: list[dict] = []
        markers: list[dict] = []
        method = "none"
        if circles:
            for c in circles:
                inside = [t for t in tags if _dist((t["cx"], t["cy"]), (c["cx"], c["cy"])) <= c["r"] * 0.9]
                if not inside:
                    continue
                if len(inside) == 1:
                    tag = inside[0]["tag"]
                else:
                    inside.sort(key=lambda t: (round(t["cy"]), t["cx"]))
                    tag = "".join(t["tag"] for t in inside)
                    if not GRID_TAG_RE.match(tag):
                        continue
                rec = {"tag": tag, "cx": c["cx"], "cy": c["cy"], "r": c["r"], "kind": c["kind"],
                       "gridline": has_gridline(c), "beside": marker_text(c)}
                if rec["beside"] and not rec["gridline"]:
                    rec["kind"] = "marker"
                    markers.append(rec)
                else:
                    bubbles.append(rec)
            if bubbles:
                method = "circles" if any(b["kind"] == "bezier" for b in bubbles) else "polylines"
        if not bubbles and not markers and tags:
            # text-only fallback (no tagged circles at all): short tags with no other text within 15 pt that line
            # up with at least one other tag.  Weaker — bubbles drawn as polylines / hexagons land here.
            iso = []
            for t in tags:
                near = [s for j, s in enumerate(spans) if j != t["i"]
                        and abs((s["bbox"][0] + s["bbox"][2]) / 2 - t["cx"]) < 15 + t["w"]
                        and abs((s["bbox"][1] + s["bbox"][3]) / 2 - t["cy"]) < 15 + t["h"]]
                if not near:
                    iso.append(t)
            for t in iso:
                mates = [u for u in iso if u is not t and (abs(u["cy"] - t["cy"]) < 4 or abs(u["cx"] - t["cx"]) < 4)]
                if mates:
                    bubbles.append({"tag": t["tag"], "cx": t["cx"], "cy": t["cy"], "r": max(t["w"], t["h"]) / 2 + 4,
                                    "kind": "text", "gridline": None, "beside": ""})
            if bubbles:
                method = "text-only"
        # classify
        for b in bubbles:
            tol = row_tol_pt if row_tol_pt is not None else max(4.0, 0.5 * b["r"])
            rowmates = sum(1 for o in bubbles if o is not b and o["tag"] != b["tag"] and abs(o["cy"] - b["cy"]) <= tol)
            colmates = sum(1 for o in bubbles if o is not b and o["tag"] != b["tag"] and abs(o["cx"] - b["cx"]) <= tol)
            if rowmates > colmates:
                b["axis"] = "x"
            elif colmates > rowmates:
                b["axis"] = "y"
            else:
                b["axis"] = "?"
        x_axis: dict[str, list] = {}
        y_axis: dict[str, list] = {}
        unassigned: dict[str, list] = {}
        for b in bubbles:
            target = x_axis if b["axis"] == "x" else y_axis if b["axis"] == "y" else unassigned
            target.setdefault(b["tag"], []).append((b["cx"], b["cy"]))

        def avg(d, by):
            out = {}
            for tag, pts in d.items():
                cx = sum(p[0] for p in pts) / len(pts)
                cy = sum(p[1] for p in pts) / len(pts)
                out[tag] = [cx, cy]
            return dict(sorted(out.items(), key=lambda kv: kv[1][by]))

        return {"x_axis": avg(x_axis, 0), "y_axis": avg(y_axis, 1), "unassigned": avg(unassigned, 0),
                "bubbles": bubbles, "markers": markers, "method": method, "page_index": page_index}

    # ---- calibration
    @staticmethod
    def _spacing_key_lookup(known: dict | None, a: str, b: str) -> float | None:
        if not known:
            return None
        for k, v in known.items():
            if isinstance(k, (tuple, list)) and len(k) == 2:
                ka, kb = str(k[0]).upper(), str(k[1]).upper()
            else:
                # "1-2", "A–B", "A.3-B" … grid tags carry dots but not dashes, so split on the dash
                parts = str(k).upper().replace("–", "-").replace("—", "-").split("-")
                if len(parts) < 2:
                    continue
                ka, kb = parts[0], parts[-1]
            if {ka.strip(), kb.strip()} == {a.upper(), b.upper()}:
                return float(v)
        return None

    def _dimension_between(self, page_index: int, p1: list, p2: list, axis: str, band_pt: float = 80.0) -> tuple[float, str] | None:
        """Find a feet-inch string lying in the band between two consecutive bubbles.  Returns (feet, text)."""
        raw = self._raw_text(page_index)
        cands = []
        if axis == "x":
            lo, hi = sorted((p1[0], p2[0]))
            mid = (lo + hi) / 2
            row = (p1[1] + p2[1]) / 2
        else:
            lo, hi = sorted((p1[1], p2[1]))
            mid = (lo + hi) / 2
            col = (p1[0] + p2[0]) / 2
        for item in list(raw["spans"]) + list(raw["lines"]):
            txt = item["text"].strip()
            v = parse_ft_in(txt)
            if v is None or v <= 0:
                continue
            bb = item["bbox"]
            cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
            if axis == "x":
                if not (lo + 2 <= cx <= hi - 2) or abs(cy - row) > band_pt:
                    continue
                score = abs(cx - mid) + 0.25 * abs(cy - row)
            else:
                if not (lo + 2 <= cy <= hi - 2) or abs(cx - col) > band_pt:
                    continue
                score = abs(cy - mid) + 0.25 * abs(cx - col)
            cands.append((score, v, txt))
        if not cands:
            return None
        cands.sort()
        return cands[0][1], cands[0][2]

    def calibrate(self, bubbles: dict, known_spacings: dict | None = None, page_index: int | None = None,
                  fallback_pt_per_ft: float | None = None) -> dict:
        """Points-per-foot from bubble positions and the dimension strings (or given spacings) between them.

        `known_spacings`: {"1-2": 25.0, ("A","B"): 30.0} in feet.  Without it the dimension strings printed in the
        band between consecutive bubbles are read from the page text.  Least squares over all pairs on both axes.
        Returns {"pt_per_ft", "x_ft": {tag: ft}, "y_ft": {tag: ft}, "origin_pt": (x, y), "residual_pt",
                 "method": "given spacings" | "dimension strings" | "assumed" | "unknown", "pairs": [...]}.
        X feet grow to the right from the left-most X bubble; Y feet grow UP the page from the bottom-most Y bubble."""
        if page_index is None:
            page_index = bubbles.get("page_index")
        xs = list(bubbles.get("x_axis", {}).items())      # sorted by cx
        ys = list(bubbles.get("y_axis", {}).items())      # sorted by cy (top first)
        # every drawn position of each tag (bubbles sit on both sides of a plan): the dimension strings run along
        # one of those rows / columns, not along the averaged position
        drawn: dict[str, list[tuple[float, float]]] = {}
        for b in bubbles.get("bubbles", []):
            drawn.setdefault(b["tag"], []).append((b["cx"], b["cy"]))
        pairs = []                                        # (axis, a, b, d_pt, s_ft, source)
        method = "unknown"
        for axis, seq in (("x", xs), ("y", ys)):
            for (ta, pa), (tb, pb) in zip(seq, seq[1:]):
                d_pt = abs(pb[0] - pa[0]) if axis == "x" else abs(pb[1] - pa[1])
                s = self._spacing_key_lookup(known_spacings, ta, tb)
                src = "given"
                if s is None and page_index is not None:
                    if axis == "x":
                        rows = sorted({round(p[1]) for p in drawn.get(ta, []) + drawn.get(tb, [])} or {round(pa[1])})
                        trials = [((pa[0], r), (pb[0], r)) for r in rows]
                    else:
                        cols = sorted({round(p[0]) for p in drawn.get(ta, []) + drawn.get(tb, [])} or {round(pa[0])})
                        trials = [((cc, pa[1]), (cc, pb[1])) for cc in cols]
                    best = None
                    for q1, q2 in trials:
                        found = self._dimension_between(page_index, q1, q2, axis)
                        if found and (best is None or found[2] < best[2]):
                            best = found
                    if best:
                        s, src = best[0], f"text {best[1]!r}"
                pairs.append({"axis": axis, "from": ta, "to": tb, "d_pt": d_pt, "ft": s, "source": src if s else ""})
        used = [p for p in pairs if p["ft"]]
        if used:
            S = np.array([p["ft"] for p in used], dtype=float)
            D = np.array([p["d_pt"] for p in used], dtype=float)
            k = float((D * S).sum() / (S * S).sum())
            residual = float(np.abs(D - k * S).max())
            method = "given spacings" if all(p["source"] == "given" for p in used) else "dimension strings"
            if known_spacings and any(p["source"] == "given" for p in used) and method == "dimension strings":
                method = "given spacings + dimension strings"
        elif fallback_pt_per_ft:
            k, residual, method = float(fallback_pt_per_ft), float("nan"), "assumed"
        else:
            k, residual = None, float("nan")
        origin_x = xs[0][1][0] if xs else (ys[0][1][0] if ys else 0.0)
        origin_y = ys[-1][1][1] if ys else (xs[0][1][1] if xs else 0.0)
        x_ft = {t: ((p[0] - origin_x) / k if k else None) for t, p in xs}
        y_ft = {t: ((origin_y - p[1]) / k if k else None) for t, p in ys}
        return {"pt_per_ft": k, "x_ft": x_ft, "y_ft": y_ft, "origin_pt": (origin_x, origin_y),
                "residual_pt": residual, "method": method, "pairs": pairs, "page_index": page_index}

    # ---- members
    @staticmethod
    def parse_size(text: str) -> tuple[str, str, str] | None:
        """Steel size at the start of / inside a label -> (size, tag, raw_match) or None."""
        m = SIZE_RE.search(text)
        if not m:
            return None
        fam = (m.group("fam_x") or m.group("fam_pl")).upper()
        rest = (m.group("rest_x") or m.group("rest_pl")).strip()
        rest = re.sub(r"\s*[xX×]\s*", "x", rest)
        mult = (m.group("mult") or "").strip()
        size = (f"{fam} {rest}" if fam in ("PL", "PIPE") else f"{fam}{rest}")
        if mult:
            size = mult + size
        tail = text[m.end():].strip(" ,;:-–")
        tag = tail
        bm = _TAG_BRACKET_RE.match(tail)
        if bm:
            tag = bm.group(1)
        return size, tag, m.group("size")

    def members(self, page_index: int, calibration: dict | None = None, size_regex: str | re.Pattern | None = None,
                min_width: float = 0.85, max_perp_pt: float = 25.0, tol_angle_deg: float = 3.0) -> list[dict]:
        """Beam labels matched to the nearest parallel thick line, with true length from the line end points.

        Each record: label, size, tag, x_pt, y_pt (label centre), dir, line {p1, p2, width, n_parts}, length_pt,
        length_ft, x1_ft, y1_ft, x2_ft, y2_ft (grid feet, +Y north = up the page), flag ("" or outlier text).
        Unmatched labels come back with line=None and flag "NO LINE"."""
        if calibration is None:
            calibration = self.calibrate(self.grid_bubbles(page_index), page_index=page_index)
        k = calibration.get("pt_per_ft")
        ox, oy = calibration.get("origin_pt", (0.0, 0.0))
        rx = re.compile(size_regex) if isinstance(size_regex, str) else size_regex
        spans = self._raw_text(page_index)["spans"]
        lines = self.merged_lines(page_index, min_width=min_width)
        sin_tol = math.sin(math.radians(tol_angle_deg))

        labels = []
        for s in spans:
            txt = s["text"].strip()
            if rx is not None:
                if not rx.search(txt):
                    continue
                parsed = self.parse_size(txt) or (txt, "", txt)
            else:
                parsed = self.parse_size(txt)
                if not parsed:
                    continue
            size, tag, _ = parsed
            bb = s["bbox"]
            cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
            d = s["dir"]
            # label extent along its own reading direction
            corners = [(bb[0], bb[1]), (bb[2], bb[1]), (bb[2], bb[3]), (bb[0], bb[3])]
            ts = [d[0] * (px - cx) + d[1] * (py - cy) for px, py in corners]
            half_len = (max(ts) - min(ts)) / 2.0
            labels.append({"label": txt, "size": size, "tag": tag, "x_pt": cx, "y_pt": cy, "dir": d,
                           "size_pt": s["size"], "half_len": half_len})

        # candidate line per label
        assign: dict[int, list[int]] = {}
        for li, lab in enumerate(labels):
            d = lab["dir"]
            best = None
            for lj, ln in enumerate(lines):
                (x1, y1), (x2, y2) = ln["p1"], ln["p2"]
                u = _unit(x2 - x1, y2 - y1)
                if abs(d[0] * u[1] - d[1] * u[0]) > sin_tol:
                    continue
                L = ln["length"]
                t = u[0] * (lab["x_pt"] - x1) + u[1] * (lab["y_pt"] - y1)
                perp = abs(u[0] * (lab["y_pt"] - y1) - u[1] * (lab["x_pt"] - x1))
                if perp > max_perp_pt:
                    continue
                a, b = t - lab["half_len"], t + lab["half_len"]
                overlap = min(b, L) - max(a, 0.0)
                if overlap < -0.5 * lab["half_len"]:
                    continue
                score = (perp, -overlap)
                if best is None or score < best[0]:
                    best = (score, lj, t)
            lab["_line"] = best[1] if best else None
            lab["_t"] = best[2] if best else None
            if best:
                assign.setdefault(best[1], []).append(li)

        # one label per merged line is the norm; several labels share a line -> hand each its own parts
        results = []
        raw_lines = self.page_lines(page_index, min_width=min_width)["lines"]
        for li, lab in enumerate(labels):
            rec = {"label": lab["label"], "size": lab["size"], "tag": lab["tag"], "x_pt": lab["x_pt"],
                   "y_pt": lab["y_pt"], "dir": lab["dir"], "line": None, "length_pt": None, "length_ft": None,
                   "x1_ft": None, "y1_ft": None, "x2_ft": None, "y2_ft": None, "flag": ""}
            lj = lab["_line"]
            if lj is None:
                rec["flag"] = "NO LINE"
                results.append(rec)
                continue
            ln = lines[lj]
            (x1, y1), (x2, y2) = ln["p1"], ln["p2"]
            u = _unit(x2 - x1, y2 - y1)
            t_lo, t_hi = 0.0, ln["length"]
            siblings = assign.get(lj, [])
            if len(siblings) > 1 and ln.get("n_parts", 1) > 1:
                # project each constituent part; give it to the nearest label (by projected centre)
                sib_t = {s: labels[s]["_t"] for s in siblings}
                mine = []
                for pi in ln["parts"]:
                    p = raw_lines[pi]
                    ta = u[0] * (p["p1"][0] - x1) + u[1] * (p["p1"][1] - y1)
                    tb = u[0] * (p["p2"][0] - x1) + u[1] * (p["p2"][1] - y1)
                    tm = (ta + tb) / 2
                    owner = min(sib_t, key=lambda s: abs(sib_t[s] - tm))
                    if owner == li:
                        mine.append((min(ta, tb), max(ta, tb)))
                if mine:
                    t_lo, t_hi = min(a for a, _ in mine), max(b for _, b in mine)
            p1 = (x1 + u[0] * t_lo, y1 + u[1] * t_lo)
            p2 = (x1 + u[0] * t_hi, y1 + u[1] * t_hi)
            Lpt = t_hi - t_lo
            rec["line"] = {"p1": p1, "p2": p2, "width": ln.get("width"), "n_parts": ln.get("n_parts", 1),
                           "shared": len(siblings) > 1}
            rec["length_pt"] = Lpt
            if k:
                rec["length_ft"] = Lpt / k
                rec["x1_ft"], rec["y1_ft"] = (p1[0] - ox) / k, (oy - p1[1]) / k
                rec["x2_ft"], rec["y2_ft"] = (p2[0] - ox) / k, (oy - p2[1]) / k
            else:
                rec["flag"] = "NO CALIBRATION"
            results.append(rec)

        # outlier flags
        by_size: dict[str, list[float]] = {}
        for r in results:
            if r["length_ft"] is not None:
                by_size.setdefault(r["size"], []).append(r["length_ft"])
        for r in results:
            L = r["length_ft"]
            if L is None:
                continue
            flags = []
            grp = by_size[r["size"]]
            if len(grp) >= 2:
                med = statistics.median(grp)
                if med > 0 and abs(L - med) / med > 0.35:
                    flags.append(f"35% OFF MEDIAN ({med:.2f} ft)")
            if L < 2.5:
                flags.append("SHORT < 2.5 ft")
            if L > 45.0:
                flags.append("LONG > 45 ft")
            if flags:
                r["flag"] = "; ".join(([r["flag"]] if r["flag"] else []) + flags)
        return results

    # ---- reports
    def page_report(self, page_index: int, calibration: dict | None = None, known_spacings: dict | None = None,
                    min_width: float = 0.85) -> dict:
        """Everything the interpretation stage needs for one page, JSON-serialisable (floats rounded to 3)."""
        info = self.pages[page_index]
        bubbles = self.grid_bubbles(page_index)
        if calibration is None:
            calibration = self.calibrate(bubbles, known_spacings=known_spacings, page_index=page_index)
        mem = self.members(page_index, calibration, min_width=min_width)
        pl = self.page_lines(page_index, min_width=min_width)
        merged = self.merged_lines(page_index, min_width=min_width)
        rep = {
            "file": info.file, "page_index": info.page_index, "file_page": info.file_page,
            "sheet_number": info.sheet_number, "sheet_title": info.sheet_title,
            "width_pt": info.width_pt, "height_pt": info.height_pt, "rotation": info.rotation,
            "frame": "displayed page frame: origin top-left, x right, y down, pt; grid feet +X right, +Y up (north)",
            "has_vector": info.has_vector, "has_text": info.has_text, "text_spans": len(self._raw_text(page_index)["spans"]),
            "image_count": info.image_count,
            "bubbles": {kk: v for kk, v in bubbles.items() if kk != "page_index"},
            "calibration": {kk: v for kk, v in calibration.items() if kk != "page_index"},
            "members": mem,
            "member_count": sum(1 for r in mem if r["line"] is not None),
            "unmatched_labels": sum(1 for r in mem if r["line"] is None),
            "column_symbols": len(pl["column_symbols"]),
            "column_symbol_points": [[s["cx"], s["cy"]] for s in pl["column_symbols"]],
            "lines_thick": len(pl["lines"]), "lines_merged": len(merged), "segments_all": pl["n_segments_all"],
        }
        return _round(rep)

    def export_page_json(self, page_index: int, path: str, **kw) -> str:
        rep = self.page_report(page_index, **kw)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2)
        return path

    def export_set_json(self, path: str, **kw) -> str:
        reps = {"pages": self.summary(), "reports": [self.page_report(i, **kw) for i in range(len(self.pages))]}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(_round(reps), f, indent=2)
        return path


if __name__ == "__main__":      # pragma: no cover
    import sys
    ds = DrawingSet(sys.argv[1:])
    print(ds.summary_table())
    for i in range(len(ds)):
        rep = ds.page_report(i)
        print(f"\n{rep['sheet_number']}: pt/ft={rep['calibration']['pt_per_ft']} members={rep['member_count']} "
              f"unmatched={rep['unmatched_labels']} columns={rep['column_symbols']}")
