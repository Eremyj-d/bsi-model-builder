"""
workbook.py — the Bohling Steel takeoff workbook (12 tabs) built from a `Takeoff` (model.py).

    from bsi_model_builder.takeoff.workbook import build_workbook, ANCHORS
    path = build_workbook(takeoff, "Job_Takeoff.xlsx")      # -> the path written
    ANCHORS["Column Tonnage"]                               # -> "H21" for the sample (grand-total LBS cell of that tab)

Spec: docs/BSI_STANDARDS.md section 2.  House style (fonts, fills, ft-in display formula) is shared with
core/geometry_tab.py, which also writes tab 12.

TABS (in order)
    1 Summary                    inclusions / exclusions, drawings received, TONNAGE SUMMARY (IFERROR rollups of the
                                 fixed grand-total cells below), revision log, project notes, assumptions, FLAGS
    2 Column Tonnage             one row per column, TOTAL, BY SIZE SUMMARY (SUMIF), COLUMN GRAND TOTAL lbs / tons
    3 Beam Tonnage               SUMMARY BY SHEET (SUMIF on SHEET), ROLLUP BY MEMBER (sheet x size x length), gold memo
                                 rows (joists / deck — not summed), BY SIZE SUMMARY (SUMIF)
    4 Anchor Bolt Summary        Column ABs / Additional AB Groups / Lintel ABs, grand total
    5 Field Bolts & Anchors      Beam-to-Beam Shear / Cap Plate / Moment / Brace / Post-installed, grand total
    6 Misc Parts                 groups (Base Plates, Plate Washers, ...), gold memo row = Detail Register total
                                 (shown, NOT added), grand total (net)
    7 Misc Metals                same columns; NOT part of PROJECT TOTAL
    8 Detail Register            kits A, B, C ... (yellow QTY APPLIED inputs), subtotal per kit, closing gold
                                 "no new steel" kit, GRAND TOTAL, HOW TO USE THIS TAB
    9 Finish Summary             Primed / Galv rollup by SUMIF over each tab's FINISH column, HELD OUT list,
                                 RECONCILIATION (VARIANCE must read 0), PIECE COUNT check, galvanized-but-unquantified
    10 Beam Detail — by Member   one row per beam callout, TOTAL + tie-out check to Beam Tonnage
    11 S-Sheet Notes             SHEET | NOTE, reference only
    12 Model Geometry            written by core.geometry_tab.add_model_geometry_tab

FIXED GRAND-TOTAL CELLS
    Every tab's grand total sits at a fixed cell, recorded in the module-level dict ANCHORS when the workbook is
    built (a row's address depends on how many rows the job has, so the map is per build; it is also written into
    the workbook as defined names, e.g. COLUMN_TONNAGE_TOTAL_LBS).  Layout rule per tab:

        Summary                    PROJECT TOTAL lbs           col D, the row after the six rollup lines
        Column Tonnage             COLUMN GRAND TOTAL lbs      col H, last row of the tab
        Beam Tonnage               TOTAL — BEAMS lbs           col G, SUMMARY BY SHEET total row (top of the tab)
        Anchor Bolt Summary        GRAND TOTAL lbs             col I, last row
        Field Bolts & Anchors      GRAND TOTAL lbs             col H, last row
        Misc Parts                 GRAND TOTAL (net) lbs       col G, last row
        Misc Metals                GRAND TOTAL lbs             col G, last row
        Detail Register            GRAND TOTAL lbs             col I, row above HOW TO USE THIS TAB
        Finish Summary             VARIANCE                    col C, RECONCILIATION block (must be 0)
        Beam Detail — by Member    TOTAL lbs                   col F, last data row + 1 (check text in col G)
        Model Geometry             TOTAL lbs (modelled steel)  col T, TOTAL row

    For the sample takeoff (tests/data/sample_takeoff.json) the map is:
        {"Summary": "D30",                      # PROJECT TOTAL lbs (tons in E30)
         "Column Tonnage": "H21", "Beam Tonnage": "G7", "Anchor Bolt Summary": "I18",
         "Field Bolts & Anchors": "H26", "Misc Parts": "G15", "Misc Metals": "G10", "Detail Register": "I24",
         "Finish Summary": "C35",               # VARIANCE (must be 0)
         "Beam Detail — by Member": "F20",      # TOTAL lbs; tie-out text in G20
         "Model Geometry": "T35"}               # modelled-steel TOTAL lbs; piece-count text in P35

KEY_CELLS carries the other cells other code looks up (PROJECT TOTAL tons, Beam Detail check text, Model Geometry
piece-count text, ...).

CONVENTIONS (hard rules from the standard)
    * Lengths are shown in feet-inches in every visible cell via the display formula
      ftin_formula(ref) (nearest 1/8"), driven by a HIDDEN decimal-feet helper column (HEIGHT (DEC FT),
      LENGTH (DEC FT)) that also drives the weights.  Blank stays blank.
    * Every total / subtotal / rollup is a formula.  Summary lines are =IFERROR('<Tab>'!<cell>,0).
    * FINISH header is exactly "FINISH"; values Primed / Galv (steel) or Plain / Galv (hardware).
    * RFI column text = ", ".join(codes), filled by the highest priority (P1 F4CCCC, P2 FCE4D6, P3 FFF2CC,
      INFO E7E6E6).  Allowance rows get ORANGE FCE4D6 on their QTY / size cells.  GOLD FFE699 = memo.
    * Arial throughout, gridlines off, freeze panes under the header row, navy title row, blue header row,
      EAF1F8 / DEEAF1 zebra.
"""
from __future__ import annotations

import dataclasses
import math
import os
import re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter as CL
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.properties import PageSetupProperties

from ..core.geometry_tab import (BLUE, BORDER, BOLD, GOLD, HDR, LIGHT, LIGHT2, NAVY, NOTE, TITLE, TXT, VISIBLE,
                                 YELLOW, add_model_geometry_tab, ftin_formula)
from ..core.jobfile import DEFAULT_DATUM
from .model import Takeoff, parse_ft_in

# ----------------------------------------------------------------------------- constants
SUM, CT, BT, AB, FB, MP, MM, DR, FS, BD, SN, MG = (
    "Summary", "Column Tonnage", "Beam Tonnage", "Anchor Bolt Summary", "Field Bolts & Anchors", "Misc Parts",
    "Misc Metals", "Detail Register", "Finish Summary", "Beam Detail — by Member", "S-Sheet Notes", "Model Geometry")
TABS = [SUM, CT, BT, AB, FB, MP, MM, DR, FS, BD, SN, MG]

ORANGE, GREEN, RED, GREY = "FCE4D6", "E2EFDA", "FBE2E2", "E7E6E6"
GROUP, SUBTOT, KIT, LBLUE = "BDD7EE", "D9D9D9", "BDD7EE", "DDEBF7"
PRI_FILL = {"P1": "F4CCCC", "P2": "FCE4D6", "P3": "FFF2CC", "INFO": "E7E6E6"}
PRI_RANK = {"P1": 0, "P2": 1, "P3": 2, "INFO": 3}
ZEBRA = (LIGHT, LIGHT2)

F_GROUP = Font(name="Arial", size=9, bold=True, color=NAVY)
F_SEC = Font(name="Arial", size=10, bold=True, color=NAVY)
F_WHITE = Font(name="Arial", size=9, bold=True, color="FFFFFF")
F_GREEN = Font(name="Arial", size=9, bold=True, color="375623")
F_RED = Font(name="Arial", size=9, bold=True, color="9C0006")
F_BIGTOT = Font(name="Arial", size=10, bold=True, color="FFFFFF")

A_L = Alignment(horizontal="left", vertical="center", indent=1)
A_LW = Alignment(horizontal="left", vertical="center", wrap_text=True, indent=1)
A_LT = Alignment(horizontal="left", vertical="top", wrap_text=True)
A_C = Alignment(horizontal="center", vertical="center")
A_CW = Alignment(horizontal="center", vertical="center", wrap_text=True)
A_R = Alignment(horizontal="right", vertical="center")

N0, N1, N2 = "#,##0", "#,##0.0", "0.00"
TONS = '#,##0.00" T"'

#: grand-total cell of each tab (filled by build_workbook; see module docstring)
ANCHORS: dict[str, str] = {}
#: other cells that checks / other builders look up
KEY_CELLS: dict[str, str] = {}

_FILLS: dict[str, PatternFill] = {}


# ----------------------------------------------------------------------------- style helpers
def _pf(hex_: str) -> PatternFill:
    return _FILLS.setdefault(hex_, PatternFill("solid", fgColor=hex_))


def put(ws, r, c, v=None, font=TXT, fill=None, align=None, border=True, fmt=None):
    """write one styled cell (same signature pattern as geometry_tab.put, with the sheet passed in)"""
    cell = ws.cell(row=r, column=c, value=v)
    cell.font = font
    if fill:
        cell.fill = _pf(fill)
    if align:
        cell.alignment = align
    if border:
        cell.border = BORDER
    if fmt:
        cell.number_format = fmt
    return cell


def span(ws, r, c1, c2, v=None, font=TXT, fill=None, align=None, border=True, fmt=None, height=None):
    """style c1..c2 on row r, then merge them (value lives in the top-left cell)"""
    for c in range(c1, c2 + 1):
        put(ws, r, c, v if c == c1 else None, font, fill, align, border, fmt)
    if c2 > c1:
        ws.merge_cells(start_row=r, start_column=c1, end_row=r, end_column=c2)
    if height:
        ws.row_dimensions[r].height = height
    return ws.cell(row=r, column=c1)


def _lines(text, chars_per_line) -> int:
    n = 0
    for par in str(text if text is not None else "").split("\n"):
        n += max(1, math.ceil(len(par) / max(chars_per_line, 1)))
    return n


def _height(text, width_units, size=9) -> float:
    per_unit = 1.25 if size >= 9 else 1.45
    return max(14.0, _lines(text, width_units * per_unit) * (12.0 if size >= 9 else 11.0) + 3)


def _hdr(ws, r, heads, c0=1, height=30):
    for i, h in enumerate(heads):
        put(ws, r, c0 + i, h, HDR, BLUE, A_CW)
    ws.row_dimensions[r].height = height


def _hdr_spans(ws, r, spec, height=22):
    for c1, c2, text in spec:
        span(ws, r, c1, c2, text, HDR, BLUE, A_CW)
    ws.row_dimensions[r].height = height


def _band(ws, r, c1, c2, text, fill=GROUP, font=F_GROUP):
    """group / section title row across the table"""
    return span(ws, r, c1, c2, text, font, fill, A_L, height=16)


def _total_row(ws, r, c1, c2, label, fill=SUBTOT, font=BOLD, merge=False):
    """subtotal / total row: c1..c2 styled, label in c1; merged only when `merge` (values go in unmerged cells)"""
    if merge:
        return span(ws, r, c1, c2, label, font, fill, A_L)
    for c in range(c1, c2 + 1):
        put(ws, r, c, label if c == c1 else None, font, fill, A_L)


def _fin(v, hardware=False) -> str:
    """normalise a finish to the standard vocabulary: Primed / Galv (steel) or Plain / Galv (hardware)"""
    s = str(v or "").strip().lower()
    if s.startswith("galv") or s in ("hdg", "hot dip", "hot-dip", "hot dip galvanized", "hot-dip galvanized", "yes", "y"):
        return "Galv"
    return "Plain" if hardware else "Primed"


def _ft(ref: str) -> str:
    return ftin_formula(ref)


def _q(sheet: str) -> str:
    return "'" + sheet.replace("'", "''") + "'"


def _rng(sheet: str, col: str, r1: int, r2: int) -> str:
    return f"{_q(sheet)}!${col}${r1}:${col}${r2}"


def _uniq(seq):
    seen, out = set(), []
    for s in seq:
        k = str(s).upper()
        if k not in seen:
            seen.add(k)
            out.append(s)
    return out


class _Ctx:
    def __init__(self, t: Takeoff, wb: Workbook):
        self.t, self.wb = t, wb
        self.ws = {n: wb.create_sheet(n) if i else wb.active for i, n in enumerate(TABS[:-1])}
        self.ws[SUM].title = SUM
        self.rng: dict[str, dict] = {}
        self.memo_cells: dict[str, list[str]] = {"joist": [], "deck": [], "other": []}

    def rfi_fill(self, codes) -> str:
        best = None
        for code in codes or []:
            p = self.t.rfi_priority(code)
            if p in PRI_RANK and (best is None or PRI_RANK[p] < PRI_RANK[best]):
                best = p
        return PRI_FILL.get(best, YELLOW)

    def title(self, subject: str) -> str:
        h = self.t.header
        bld = f" | {h.building}" if h.building else ""
        return f"{h.job.upper()}{bld} | {subject} | {h.status}"


def _rfi_cell(ctx, ws, r, c, codes, zebra):
    txt = ", ".join(codes or [])
    if txt:
        put(ws, r, c, txt, BOLD, ctx.rfi_fill(codes), A_CW)
    else:
        put(ws, r, c, None, TXT, zebra, A_CW)


def _open(ctx, ws, subject, notes, widths, nvis, hidden=(), label=None):
    """title row, note rows, blank row (optionally carrying a section label); returns the header row number"""
    ws.sheet_view.showGridLines = False
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[CL(i)].width = w
    for i in hidden:
        ws.column_dimensions[CL(i)].hidden = True
    span(ws, 1, 1, nvis, ctx.title(subject), TITLE, NAVY, A_L, border=False, height=22)
    tot_w = sum(widths[:nvis])
    r = 2
    for ln in notes:
        span(ws, r, 1, nvis, ln, NOTE, None, A_LW, border=False, height=_height(ln, tot_w, 8))
        r += 1
    if label:
        put(ws, r, 1, label, F_SEC, None, A_L, border=False)
    return r + 1


def _finish_sheet(ws, hdr_row, nvis, freeze_row=None, titles=True):
    ws.freeze_panes = ws.cell(row=freeze_row or hdr_row + 1, column=1)
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    if titles:
        ws.print_title_rows = f"{hdr_row}:{hdr_row}"
    ws.print_area = f"A1:{CL(nvis)}{ws.max_row}"


def _anchor(ctx, tab, cell, name):
    ANCHORS[tab] = cell
    col = re.match(r"[A-Z]+", cell).group(0)
    row = cell[len(col):]
    ctx.wb.defined_names[name] = DefinedName(name, attr_text=f"{_q(tab)}!${col}${row}")


def _grade_note(rows, attr="grade"):
    gs = sorted({getattr(x, attr) for x in rows if getattr(x, attr, "")})
    return "; ".join(gs)


# ----------------------------------------------------------------------------- 2 Column Tonnage
def _column_tonnage(ctx):
    t, ws = ctx.t, ctx.ws[CT]
    cols = t.columns
    heads = ["MARK / LOCATION", "QTY", "SIZE", "BASE PLATE", "HEIGHT (FT-IN)", "LB/FT", "COL LBS", "TOTAL LBS",
             "BP ELEV (T/FTG → T/STL)", "ANCHORS", "FINISH", "GRADE", "NOTES / SOURCE", "RFI", "HEIGHT (DEC FT)"]
    widths = [26, 6, 14, 22, 14, 8, 11, 12, 30, 18, 9, 12, 48, 12, 10]
    nvis = 14
    notes = [f"One row per column mark. Height = top of footing (base-plate elevation) to top of steel; the hidden HEIGHT (DEC FT) "
             f"column drives the weights and the visible HEIGHT shows feet-inches to the nearest 1/8\". Grades: {_grade_note(cols) or 'per general notes'}.",
             "COL LBS = HEIGHT x LB/FT; TOTAL LBS = QTY x COL LBS. Column base plates and anchor rods are carried on Misc Parts and "
             "Anchor Bolt Summary. Orange = allowance / height TBD."]
    hdr = _open(ctx, ws, "COLUMN TONNAGE", notes, widths, nvis, hidden=[15])
    _hdr(ws, hdr, heads)
    r = hdr + 1
    _band(ws, r, 1, nvis, "▶  COLUMNS — column schedule / foundation plan")
    r += 1
    first = r
    n = max(len(cols), 1)
    for i in range(n):
        c = cols[i] if i < len(cols) else None
        z = ZEBRA[i % 2]
        orange = ORANGE if (c and c.allowance) else None
        lab = None
        if c:
            lab = f"{c.mark} — {c.location}" if c.location else c.mark
        put(ws, r, 1, lab, TXT, z, A_L)
        put(ws, r, 2, c.qty if c else None, TXT, orange or z, A_C)
        put(ws, r, 3, c.size if c else None, TXT, orange or z, A_L)
        put(ws, r, 4, c.base_plate if c else None, TXT, z, A_L)
        tbd = bool(c and c.height_ft is None)
        put(ws, r, 5, _ft(f"O{r}"), BOLD, ORANGE if tbd else z, A_R)
        put(ws, r, 6, c.lb_ft if c else None, TXT, z, A_R, fmt=N2)
        put(ws, r, 7, f'=IF(AND(ISNUMBER(O{r}),ISNUMBER(F{r})),O{r}*F{r},"")', TXT, z, A_R, fmt=N1)
        put(ws, r, 8, f'=IF(AND(ISNUMBER(B{r}),ISNUMBER(G{r})),B{r}*G{r},"")', BOLD, z, A_R, fmt=N1)
        put(ws, r, 9, c.bp_elev if c else None, TXT, z, A_L)
        put(ws, r, 10, c.anchors if c else None, TXT, z, A_L)
        put(ws, r, 11, _fin(c.finish) if c else None, TXT, z, A_C)
        put(ws, r, 12, c.grade if c else None, TXT, z, A_L)
        nt = " ".join(x for x in (("HEIGHT TBD —" if tbd else ""), (c.notes or ""), (f"[{c.sheet}]" if c.sheet else "")) if x) if c else None
        put(ws, r, 13, nt or None, TXT, z, A_LW)
        _rfi_cell(ctx, ws, r, 14, c.rfi if c else [], z)
        put(ws, r, 15, c.height_ft if c else None, TXT, z, A_R, fmt="0.0000")
        r += 1
    last = r - 1
    tot = r
    _total_row(ws, tot, 1, nvis, "TOTAL — COLUMNS")
    put(ws, tot, 2, f"=SUM(B{first}:B{last})", BOLD, SUBTOT, A_C)
    put(ws, tot, 8, f"=SUM(H{first}:H{last})", BOLD, SUBTOT, A_R, fmt=N0)
    ctx.rng[CT] = dict(first=first, last=last, fin="K", lbs="H", qty="B", qty_total=f"B{tot}")
    r = tot + 2

    # BY SIZE SUMMARY
    _band(ws, r, 1, nvis, "▶  BY SIZE SUMMARY")
    r += 1
    _hdr(ws, r, ["SIZE", "QTY", "TOTAL LF (FT-IN)", "LB/FT", "TOTAL LBS"], height=28)
    r += 1
    sizes = _uniq(c.size for c in cols) or [None]
    s_first = r
    for i, sz in enumerate(sizes):
        z = ZEBRA[i % 2]
        put(ws, r, 1, sz, TXT, z, A_L)
        if sz is None:
            for cc in (2, 3, 4, 5):
                put(ws, r, cc, None, TXT, z)
            put(ws, r, 15, None, TXT, z)
        else:
            put(ws, r, 2, f"=SUMIF($C${first}:$C${last},A{r},$B${first}:$B${last})", TXT, z, A_C)
            put(ws, r, 3, _ft(f"O{r}"), BOLD, z, A_R)
            put(ws, r, 4, f'=IFERROR(INDEX($F${first}:$F${last},MATCH(A{r},$C${first}:$C${last},0)),"")', TXT, z, A_R, fmt=N2)
            put(ws, r, 5, f"=SUMIF($C${first}:$C${last},A{r},$H${first}:$H${last})", TXT, z, A_R, fmt=N0)
            put(ws, r, 15, f"=SUMPRODUCT(($C${first}:$C${last}=A{r})*($B${first}:$B${last})*($O${first}:$O${last}))",
                TXT, z, A_R, fmt="0.0000")
        r += 1
    s_last = r - 1
    _total_row(ws, r, 1, 5, "CHECK TOTAL")
    ws.cell(row=r, column=2).value = f"=SUM(B{s_first}:B{s_last})"
    ws.cell(row=r, column=5).value = f"=SUM(E{s_first}:E{s_last})"
    ws.cell(row=r, column=5).number_format = N0
    ws.cell(row=r, column=5).alignment = A_R
    ws.cell(row=r, column=2).alignment = A_C
    put(ws, r, 6, f'=IF(ROUND(E{r}-H{tot},0)=0,"✓ ties to TOTAL","CHECK — by-size does not tie")', BOLD, None, A_L, border=False)
    r += 2

    # GRAND TOTAL
    span(ws, r, 1, 7, "COLUMN GRAND TOTAL — LBS / TONS", F_BIGTOT, NAVY, A_L, height=20)
    put(ws, r, 8, f"=H{tot}", F_BIGTOT, NAVY, A_R, fmt=N0)
    put(ws, r, 9, f"=H{r}/2000", F_BIGTOT, NAVY, A_R, fmt=TONS)
    _anchor(ctx, CT, f"H{r}", "COLUMN_TONNAGE_TOTAL_LBS")
    _finish_sheet(ws, hdr, nvis)


# ----------------------------------------------------------------------------- 3 Beam Tonnage
def _memo_kind(m) -> str:
    s = m.item.lower()
    if "deck" in s:
        return "deck"
    if "joist" in s or re.search(r"\bjg\b", s):
        return "joist"
    return "other"


def _beam_tonnage(ctx):
    t, ws = ctx.t, ctx.ws[BT]
    roll = t.beam_rollup()
    desc = {s.number: s.title for s in t.sheets}
    sheets = _uniq(g["sheet"] or "—" for g in roll)
    nvis = 10
    widths = [26, 10, 7, 9, 14, 12, 10, 12, 50, 12, 10]
    heads = ["SIZE", "SHEET", "QTY", "LB/FT", "LENGTH (FT-IN)", "TOTAL LBS", "FINISH", "GRADE", "NOTES", "RFI", "LENGTH (DEC FT)"]
    notes = [f"Beams rolled up from Beam Detail — by Member: one row per sheet x size x length (lengths to 1/8\"). Grades: "
             f"{_grade_note(t.beams) or 'per general notes'}. TOTAL LBS = QTY x LB/FT x LENGTH; the hidden LENGTH (DEC FT) carries the "
             "member-weighted length so the rollup ties to the detail to the pound.",
             "Open-web joists and roof deck are MEMO ONLY (gold) — shown for the record, not in the beam total or PROJECT TOTAL."]
    top_hdr = _open(ctx, ws, "BEAM TONNAGE", notes, widths, nvis, hidden=[11], label="SUMMARY BY SHEET:")
    n_s = max(len(sheets), 1)
    top_tot = top_hdr + n_s + 1
    roll_label = top_tot + 2
    roll_hdr = roll_label + 1
    r = roll_hdr + 1
    roll_first = r
    sub_rows = []
    by_sheet: dict[str, list[dict]] = {}
    for g in roll:
        by_sheet.setdefault(g["sheet"] or "—", []).append(g)

    put(ws, roll_label, 1, "ROLLUP BY MEMBER (one row per sheet x size x length; broken out by framing sheet):", F_SEC, None, A_L, border=False)
    _hdr(ws, roll_hdr, heads)
    if not roll:
        for cc in range(1, nvis + 1):
            put(ws, r, cc, None, TXT, ZEBRA[0])
        put(ws, r, 6, f'=IF(AND(ISNUMBER(C{r}),ISNUMBER(D{r}),ISNUMBER(K{r})),C{r}*D{r}*K{r},"")', TXT, ZEBRA[0], A_R)
        r += 1
    for s in sheets:
        _band(ws, r, 1, nvis, f"—  {s}  {desc[s].upper()}  —" if desc.get(s) else f"—  {s}  —")
        r += 1
        s_first = r
        for i, g in enumerate(by_sheet.get(s, [])):
            z = ZEBRA[i % 2]
            orange = ORANGE if g["allowance"] else None
            put(ws, r, 1, g["size"], TXT, orange or z, A_L)
            put(ws, r, 2, g["sheet"] or "—", TXT, z, A_C)
            put(ws, r, 3, g["qty"], TXT, orange or z, A_C)
            put(ws, r, 4, g["lb_ft"] or None, TXT, z, A_R, fmt=N2)
            put(ws, r, 5, _ft(f"K{r}"), BOLD, orange or z, A_R)
            put(ws, r, 6, f'=IF(AND(ISNUMBER(C{r}),ISNUMBER(D{r}),ISNUMBER(K{r})),C{r}*D{r}*K{r},"")', BOLD, z, A_R, fmt=N1)
            put(ws, r, 7, _fin(g["finish"]), TXT, z, A_C)
            put(ws, r, 8, g["grade"], TXT, z, A_L)
            put(ws, r, 9, g["notes"] or None, TXT, z, A_LW)
            _rfi_cell(ctx, ws, r, 10, g["rfi"], z)
            # member-weighted length: qty x lb/ft x length == the exact sum of the member weights
            lbft = g["lb_ft"] or 0
            ln = g["lbs"] / (g["qty"] * lbft) if lbft and g["qty"] else g["length_ft"]
            put(ws, r, 11, ln, TXT, z, A_R, fmt="0.0000")
            r += 1
        s_last = r - 1
        _total_row(ws, r, 1, nvis, f"TOTAL {s}")
        put(ws, r, 3, f"=SUM(C{s_first}:C{s_last})", BOLD, SUBTOT, A_C)
        put(ws, r, 6, f"=SUM(F{s_first}:F{s_last})", BOLD, SUBTOT, A_R, fmt=N0)
        sub_rows.append(r)
        r += 1
    roll_last = r - 1
    roll_tot = r
    _total_row(ws, roll_tot, 1, nvis, "TOTAL — ROLLUP BY MEMBER", GROUP, F_GROUP)
    put(ws, roll_tot, 3, "=" + ("+".join(f"C{x}" for x in sub_rows) if sub_rows else "0"), F_GROUP, GROUP, A_C)
    put(ws, roll_tot, 6, "=" + ("+".join(f"F{x}" for x in sub_rows) if sub_rows else "0"), F_GROUP, GROUP, A_R, fmt=N0)
    put(ws, roll_tot, 9, f'=IF(ROUND(G{top_tot}-F{roll_tot},0)=0,"✓ ties to SUMMARY BY SHEET","CHECK — SUMMARY BY SHEET does not tie")',
        F_GROUP, GROUP, A_L)
    ctx.rng[BT] = dict(first=roll_first, last=roll_last, fin="G", lbs="F", qty="C")

    # SUMMARY BY SHEET (top block; SUMIF on the SHEET column of the rollup)
    _hdr_spans(ws, top_hdr, [(1, 1, "SHEET"), (2, 5, "DESCRIPTION"), (6, 6, "PIECES"), (7, 7, "LBS"), (8, 8, "TONS")], height=22)
    rr = top_hdr + 1
    for i in range(n_s):
        z = ZEBRA[i % 2]
        s = sheets[i] if i < len(sheets) else None
        put(ws, rr, 1, s, TXT, z, A_L)
        span(ws, rr, 2, 5, desc.get(s) if s else None, TXT, z, A_L)
        if s:
            put(ws, rr, 6, f"=SUMIF($B${roll_first}:$B${roll_last},A{rr},$C${roll_first}:$C${roll_last})", TXT, z, A_C)
            put(ws, rr, 7, f"=SUMIF($B${roll_first}:$B${roll_last},A{rr},$F${roll_first}:$F${roll_last})", BOLD, z, A_R, fmt=N0)
            put(ws, rr, 8, f"=G{rr}/2000", TXT, z, A_R, fmt=N2)
        else:
            for cc in (6, 7, 8):
                put(ws, rr, cc, None, TXT, z)
        rr += 1
    _total_row(ws, top_tot, 1, 5, "TOTAL — BEAMS (all framing sheets)", GROUP, F_GROUP, merge=True)
    put(ws, top_tot, 6, f"=SUM(F{top_hdr + 1}:F{top_tot - 1})", F_GROUP, GROUP, A_C)
    put(ws, top_tot, 7, f"=SUM(G{top_hdr + 1}:G{top_tot - 1})", F_GROUP, GROUP, A_R, fmt=N0)
    put(ws, top_tot, 8, f"=SUM(H{top_hdr + 1}:H{top_tot - 1})", F_GROUP, GROUP, A_R, fmt=N2)
    _anchor(ctx, BT, f"G{top_tot}", "BEAM_TONNAGE_TOTAL_LBS")
    ctx.rng[BT]["pieces_total"] = f"F{top_tot}"

    # MEMO rows (gold) — joists / deck, NOT in the beam total
    r = roll_tot + 2
    if t.memo:
        _band(ws, r, 1, nvis, "▶  MEMO — OPEN-WEB JOISTS / ROOF DECK (shown for reference — NOT included in the beam total)", GOLD, BOLD)
        r += 1
        for m in t.memo:
            put(ws, r, 1, m.item, TXT, GOLD, A_LW)
            put(ws, r, 2, m.sheet, TXT, GOLD, A_C)
            put(ws, r, 3, m.qty, TXT, GOLD, A_C)
            put(ws, r, 4, m.lb_per_unit, TXT, GOLD, A_R, fmt=N2)
            put(ws, r, 5, _ft(f"K{r}"), BOLD, GOLD, A_R)
            put(ws, r, 6, f'=IF(AND(ISNUMBER(C{r}),ISNUMBER(D{r})),C{r}*D{r}*IF(ISNUMBER(K{r}),K{r},1),"")', BOLD, GOLD, A_R, fmt=N1)
            put(ws, r, 7, None, TXT, GOLD)
            put(ws, r, 8, None, TXT, GOLD)
            put(ws, r, 9, f"{m.qty:g} {m.unit}" + (f" — {m.note}" if m.note else "") + " — NOT in tonnage", TXT, GOLD, A_LW)
            _rfi_cell(ctx, ws, r, 10, m.rfi, GOLD)
            put(ws, r, 11, m.length_ft, TXT, GOLD, A_R, fmt="0.0000")
            ctx.memo_cells[_memo_kind(m)].append(f"F{r}")
            r += 1
        r += 1

    # BY SIZE SUMMARY
    _band(ws, r, 1, nvis, "▶  BY SIZE SUMMARY (SUMIF over the rollup)")
    r += 1
    _hdr(ws, r, ["SIZE", "", "QTY", "LB/FT", "TOTAL LF (FT-IN)", "TOTAL LBS"], height=28)
    r += 1
    sizes = _uniq(g["size"] for g in roll) or [None]
    z_first = r
    for i, sz in enumerate(sizes):
        z = ZEBRA[i % 2]
        put(ws, r, 1, sz, TXT, z, A_L)
        put(ws, r, 2, None, TXT, z)
        if sz is None:
            for cc in (3, 4, 5, 6):
                put(ws, r, cc, None, TXT, z)
            put(ws, r, 11, None, TXT, z)
        else:
            put(ws, r, 3, f"=SUMIF($A${roll_first}:$A${roll_last},A{r},$C${roll_first}:$C${roll_last})", TXT, z, A_C)
            put(ws, r, 4, f'=IFERROR(INDEX($D${roll_first}:$D${roll_last},MATCH(A{r},$A${roll_first}:$A${roll_last},0)),"")', TXT, z, A_R, fmt=N2)
            put(ws, r, 5, _ft(f"K{r}"), BOLD, z, A_R)
            put(ws, r, 6, f"=SUMIF($A${roll_first}:$A${roll_last},A{r},$F${roll_first}:$F${roll_last})", TXT, z, A_R, fmt=N0)
            put(ws, r, 11, f"=SUMPRODUCT(($A${roll_first}:$A${roll_last}=A{r})*($C${roll_first}:$C${roll_last})*($K${roll_first}:$K${roll_last}))",
                TXT, z, A_R, fmt="0.0000")
        r += 1
    z_last = r - 1
    _total_row(ws, r, 1, 6, "CHECK TOTAL")
    ws.cell(row=r, column=3).value = f"=SUM(C{z_first}:C{z_last})"
    ws.cell(row=r, column=3).alignment = A_C
    ws.cell(row=r, column=6).value = f"=SUM(F{z_first}:F{z_last})"
    ws.cell(row=r, column=6).number_format = N0
    ws.cell(row=r, column=6).alignment = A_R
    put(ws, r, 9, f'=IF(ROUND(F{r}-G{top_tot},0)=0,"✓ ties to TOTAL — BEAMS","CHECK — by-size does not tie")', BOLD, None, A_L, border=False)
    _finish_sheet(ws, top_hdr, nvis)


# ----------------------------------------------------------------------------- group helper for AB / bolts / parts
def _groups(rows, defaults, always=True):
    """ordered [(group, [rows])]: default groups first (kept even when empty if `always`), then data groups in order"""
    order = list(defaults) if always else []
    byg: dict[str, list] = {}
    keyname: dict[str, str] = {k.upper(): k for k in order}
    for x in rows:
        k = (x.group or "").strip() or "Other"
        name = keyname.setdefault(k.upper(), k)
        if name not in order:
            order.append(name)
        byg.setdefault(name, []).append(x)
    return [(g, byg.get(g, [])) for g in order]


# ----------------------------------------------------------------------------- 4 Anchor Bolt Summary
def _anchor_bolts(ctx):
    t, ws = ctx.t, ctx.ws[AB]
    heads = ["LOCATION", "MEMBER", "AB DIAMETER", "AB PER ITEM", "ITEM QTY", "TOTAL ABs", "AB LENGTH", "LB/EA", "TOTAL LBS",
             "FINISH", "GRADE", "NOTES / SOURCE", "RFI", "AB LENGTH (DEC FT)"]
    widths = [28, 22, 13, 10, 10, 11, 14, 8, 12, 9, 14, 52, 12, 10]
    nvis = 13
    notes = [f"Anchor rods / anchor bolts: {_grade_note(t.anchors) or 'F1554 Gr.55 U.N.O.'}. TOTAL ABs = AB PER ITEM x ITEM QTY; TOTAL LBS = TOTAL ABs x LB/EA. "
             "Anchor rods are keyed manually in Fabtrol (held out of the KSS) — see Finish Summary.",
             "FINISH is Plain or Galv. Orange = allowance / assumed."]
    hdr = _open(ctx, ws, "ANCHOR BOLT SUMMARY", notes, widths, nvis, hidden=[14])
    _hdr(ws, hdr, heads)
    r = hdr + 1
    subs = []
    first_all = r
    for gname, rows in _groups(t.anchors, ["Column ABs", "Additional AB Groups", "Lintel ABs"]):
        _band(ws, r, 1, nvis, f"▶  {gname.upper()}")
        r += 1
        gf = r
        for i in range(max(len(rows), 1)):
            a = rows[i] if i < len(rows) else None
            z = ZEBRA[i % 2]
            orange = ORANGE if (a and a.allowance) else None
            put(ws, r, 1, a.location if a else None, TXT, z, A_L)
            put(ws, r, 2, a.member if a else None, TXT, z, A_L)
            put(ws, r, 3, a.diameter if a else None, TXT, orange or z, A_C)
            put(ws, r, 4, a.per_item if a else None, TXT, orange or z, A_C)
            put(ws, r, 5, a.item_qty if a else None, TXT, orange or z, A_C)
            put(ws, r, 6, f'=IF(AND(ISNUMBER(D{r}),ISNUMBER(E{r})),D{r}*E{r},"")', TXT, z, A_C)
            dec = parse_ft_in(a.length) if a else None
            if a and dec is None and a.length:
                put(ws, r, 7, a.length, TXT, z, A_R)          # unreadable length: shown as called out
            else:
                put(ws, r, 7, _ft(f"N{r}"), BOLD, z, A_R)
            put(ws, r, 8, a.lb_ea if a else None, TXT, z, A_R, fmt=N2)
            put(ws, r, 9, f'=IF(AND(ISNUMBER(F{r}),ISNUMBER(H{r})),F{r}*H{r},"")', BOLD, z, A_R, fmt=N1)
            put(ws, r, 10, _fin(a.finish, hardware=True) if a else None, TXT, z, A_C)
            put(ws, r, 11, a.grade if a else None, TXT, z, A_L)
            put(ws, r, 12, a.notes if a else None, TXT, z, A_LW)
            _rfi_cell(ctx, ws, r, 13, a.rfi if a else [], z)
            put(ws, r, 14, dec, TXT, z, A_R, fmt="0.0000")
            r += 1
        gl = r - 1
        _total_row(ws, r, 1, nvis, f"Subtotal — {gname}")
        put(ws, r, 6, f"=SUM(F{gf}:F{gl})", BOLD, SUBTOT, A_C)
        put(ws, r, 9, f"=SUM(I{gf}:I{gl})", BOLD, SUBTOT, A_R, fmt=N0)
        subs.append(r)
        r += 2
    last_all = r - 2
    span(ws, r, 1, 5, "GRAND TOTAL — ANCHOR BOLTS", F_BIGTOT, NAVY, A_L, height=20)
    put(ws, r, 6, "=" + "+".join(f"F{x}" for x in subs), F_BIGTOT, NAVY, A_C)
    for cc in (7, 8):
        put(ws, r, cc, None, F_BIGTOT, NAVY)
    put(ws, r, 9, "=" + "+".join(f"I{x}" for x in subs), F_BIGTOT, NAVY, A_R, fmt=N0)
    for cc in (10, 11, 12, 13):
        put(ws, r, cc, None, F_BIGTOT, NAVY)
    _anchor(ctx, AB, f"I{r}", "ANCHOR_BOLT_TOTAL_LBS")
    ctx.rng[AB] = dict(first=first_all, last=last_all, fin="J", lbs="I", qty="F", total_ea=f"F{r}")
    _finish_sheet(ws, hdr, nvis)


# ----------------------------------------------------------------------------- 5 Field Bolts & Anchors
def _field_bolts(ctx):
    t, ws = ctx.t, ctx.ws[FB]
    heads = ["CONNECTION TYPE", "LOCATION", "BOLT / ANCHOR SPEC", "PER CONN.", "CONN. QTY", "TOTAL EA", "LB/EA", "TOTAL LBS",
             "FINISH", "NOTES / SOURCE", "RFI"]
    widths = [28, 30, 26, 10, 10, 10, 8, 12, 9, 56, 12]
    nvis = 11
    notes = ["High-strength bolts A325-N (nut + washer included in LB/EA) and post-installed anchors. TOTAL EA = PER CONN. x CONN. QTY; "
             "TOTAL LBS = TOTAL EA x LB/EA. Field bolts are keyed manually in Fabtrol (held out of the KSS) — see Finish Summary.",
             "FINISH is Plain or Galv. Post-installed anchors are itemized with product and finish. Orange = allowance / assumed."]
    hdr = _open(ctx, ws, "FIELD BOLTS & ANCHORS", notes, widths, nvis)
    _hdr(ws, hdr, heads)
    r = hdr + 1
    subs = []
    first_all = r
    for gname, rows in _groups(t.bolts, ["Beam-to-Beam Shear", "Beam-on-Column Cap Plate", "Moment", "Brace", "Post-installed"]):
        _band(ws, r, 1, nvis, f"▶  {gname.upper()}")
        r += 1
        gf = r
        for i in range(max(len(rows), 1)):
            b = rows[i] if i < len(rows) else None
            z = ZEBRA[i % 2]
            orange = ORANGE if (b and b.allowance) else None
            put(ws, r, 1, b.connection_type if b else None, TXT, z, A_L)
            put(ws, r, 2, b.location if b else None, TXT, z, A_L)
            put(ws, r, 3, b.spec if b else None, TXT, orange or z, A_L)
            put(ws, r, 4, b.per_conn if b else None, TXT, orange or z, A_C)
            put(ws, r, 5, b.conn_qty if b else None, TXT, orange or z, A_C)
            put(ws, r, 6, f'=IF(AND(ISNUMBER(D{r}),ISNUMBER(E{r})),D{r}*E{r},"")', TXT, z, A_C)
            put(ws, r, 7, b.lb_ea if b else None, TXT, z, A_R, fmt=N2)
            put(ws, r, 8, f'=IF(AND(ISNUMBER(F{r}),ISNUMBER(G{r})),F{r}*G{r},"")', BOLD, z, A_R, fmt=N1)
            put(ws, r, 9, _fin(b.finish, hardware=True) if b else None, TXT, z, A_C)
            put(ws, r, 10, b.notes if b else None, TXT, z, A_LW)
            _rfi_cell(ctx, ws, r, 11, b.rfi if b else [], z)
            r += 1
        gl = r - 1
        _total_row(ws, r, 1, nvis, f"Subtotal — {gname}")
        put(ws, r, 6, f"=SUM(F{gf}:F{gl})", BOLD, SUBTOT, A_C)
        put(ws, r, 8, f"=SUM(H{gf}:H{gl})", BOLD, SUBTOT, A_R, fmt=N0)
        subs.append(r)
        r += 2
    last_all = r - 2
    span(ws, r, 1, 5, "GRAND TOTAL — FIELD BOLTS & ANCHORS", F_BIGTOT, NAVY, A_L, height=20)
    put(ws, r, 6, "=" + "+".join(f"F{x}" for x in subs), F_BIGTOT, NAVY, A_C)
    put(ws, r, 7, None, F_BIGTOT, NAVY)
    put(ws, r, 8, "=" + "+".join(f"H{x}" for x in subs), F_BIGTOT, NAVY, A_R, fmt=N0)
    for cc in (9, 10, 11):
        put(ws, r, cc, None, F_BIGTOT, NAVY)
    _anchor(ctx, FB, f"H{r}", "FIELD_BOLT_TOTAL_LBS")
    ctx.rng[FB] = dict(first=first_all, last=last_all, fin="I", lbs="H", qty="F", total_ea=f"F{r}")
    _finish_sheet(ws, hdr, nvis)


# ----------------------------------------------------------------------------- 6 Misc Parts / 7 Misc Metals
PART_HEAD = ["QTY", "SHAPE", "THICKNESS", "SIZE / DIMENSIONS", "LENGTH (FT-IN)", "LB/EA", "TOTAL LBS", "FINISH", "GRADE",
             "SOURCE / NOTES", "MARK", "RFI", "LENGTH (DEC FT)"]
PART_W = [7, 11, 12, 40, 14, 9, 12, 9, 13, 48, 10, 12, 10]


def _parts_tab(ctx, tab, subject, notes, rows, defaults, always, memo_dr, grand_label, anchor_name):
    ws = ctx.ws[tab]
    nvis = 12
    hdr = _open(ctx, ws, subject, notes, PART_W, nvis, hidden=[13])
    _hdr(ws, hdr, PART_HEAD)
    r = hdr + 1
    subs = []
    first_all = r
    for gname, grows in _groups(rows, defaults, always):
        _band(ws, r, 1, nvis, f"▶  {gname.upper()}")
        r += 1
        gf = r
        for i in range(max(len(grows), 1)):
            p = grows[i] if i < len(grows) else None
            z = ZEBRA[i % 2]
            orange = ORANGE if (p and p.allowance) else None
            put(ws, r, 1, p.qty if p else None, TXT, orange or z, A_C)
            put(ws, r, 2, p.shape if p else None, TXT, z, A_C)
            put(ws, r, 3, p.thickness if p else None, TXT, z, A_C)
            put(ws, r, 4, p.size if p else None, TXT, orange or z, A_LW)
            put(ws, r, 5, _ft(f"M{r}"), BOLD, z, A_R)
            put(ws, r, 6, p.lb_ea if p else None, TXT, z, A_R, fmt=N2)
            put(ws, r, 7, f'=IF(AND(ISNUMBER(A{r}),ISNUMBER(F{r})),A{r}*F{r},"")', BOLD, z, A_R, fmt=N1)
            put(ws, r, 8, _fin(p.finish) if p else None, TXT, z, A_C)
            put(ws, r, 9, p.grade if p else None, TXT, z, A_L)
            put(ws, r, 10, p.source if p else None, TXT, z, A_LW)
            put(ws, r, 11, p.mark if p else None, TXT, z, A_C)
            _rfi_cell(ctx, ws, r, 12, p.rfi if p else [], z)
            put(ws, r, 13, p.length_ft if p else None, TXT, z, A_R, fmt="0.0000")
            r += 1
        gl = r - 1
        span(ws, r, 1, 6, f"Subtotal — {gname}", BOLD, SUBTOT, A_L)
        put(ws, r, 7, f"=SUM(G{gf}:G{gl})", BOLD, SUBTOT, A_R, fmt=N0)
        for cc in range(8, nvis + 1):
            put(ws, r, cc, None, BOLD, SUBTOT)
        subs.append(r)
        r += 1
    last_all = r - 1
    r += 1
    if memo_dr:
        gt_dr = ANCHORS.get(DR)
        span(ws, r, 1, 6, "Detail Register total (see tab) — not added", BOLD, GOLD, A_L)
        put(ws, r, 7, f"=IFERROR({_q(DR)}!{gt_dr},0)" if gt_dr else None, BOLD, GOLD, A_R, fmt=N0)
        put(ws, r, 8, None, TXT, GOLD)
        put(ws, r, 9, None, TXT, GOLD)
        put(ws, r, 10, "MEMO — counted once, on the Detail Register tab and its own Summary line; Misc Parts is shown net of it.", NOTE, GOLD, A_LW)
        put(ws, r, 11, None, TXT, GOLD)
        put(ws, r, 12, None, TXT, GOLD)
        r += 2
    span(ws, r, 1, 6, grand_label, F_BIGTOT, NAVY, A_L, height=20)
    put(ws, r, 7, "=" + "+".join(f"G{x}" for x in subs), F_BIGTOT, NAVY, A_R, fmt=N0)
    for cc in range(8, 13):
        put(ws, r, cc, None, F_BIGTOT, NAVY)
    _anchor(ctx, tab, f"G{r}", anchor_name)
    ctx.rng[tab] = dict(first=first_all, last=last_all, fin="H", lbs="G", qty="A")
    _finish_sheet(ws, hdr, nvis)


def _misc_parts(ctx):
    t = ctx.t
    notes = [f"Connection material that is NOT out of a detail kit: column base plates, plate washers, anything not covered by the Detail Register. "
             f"Plates {_grade_note(t.misc_parts) or 'A572 Gr.50'}. TOTAL LBS = QTY x LB/EA; LENGTH is shown for reference (feet-inches).",
             "Shown NET of the Detail Register (gold memo row below, not added). Misc Metals (stairs, rails, ladders, bollards) are on their own tab and "
             "excluded from tonnage. Orange = allowance."]
    defaults = ["Base Plates", "Plate Washers"]
    _parts_tab(ctx, MP, "MISC PARTS", notes, t.misc_parts, defaults, True, True, "GRAND TOTAL — MISC PARTS (net of Detail Register)",
               "MISC_PARTS_TOTAL_LBS")


def _misc_metals(ctx):
    t = ctx.t
    notes = ["Stairs, ladders, rails, bollards, gates and decorative metals — a separate deliverable, EXCLUDED from PROJECT TOTAL "
             "(its own line below the total on the Summary).",
             "Same columns as Misc Parts. Orange = allowance (e.g. roof ladders carried as allowance lines until a detail is issued)."]
    defaults = ["Stairs", "Ladders", "Rails", "Bollards"] if not t.misc_metals else []
    _parts_tab(ctx, MM, "MISC METALS", notes, t.misc_metals, defaults, not t.misc_metals, False,
               "GRAND TOTAL — MISC METALS (not in PROJECT TOTAL)", "MISC_METALS_TOTAL_LBS")


# ----------------------------------------------------------------------------- 8 Detail Register
def _detail_register(ctx):
    t, ws = ctx.t, ctx.ws[DR]
    heads = ["DETAIL REF", "CONDITION", "ITEM", "SIZE / SPEC", "UNIT BASIS", "LB PER UNIT", "QTY APPLIED", "UNIT", "TOTAL LBS",
             "QTY SOURCE", "NOTES", "FINISH", "GRADE", "RFI"]
    widths = [22, 30, 26, 34, 26, 11, 12, 7, 12, 34, 44, 9, 13, 12]
    nvis = 14
    notes = ["Each row is one steel item out of one section cut / detail / schedule, grouped into repeating kits (A, B, C ...). UNIT BASIS says what the "
             "item multiplies against; yellow QTY APPLIED is the input; TOTAL LBS = LB PER UNIT x QTY APPLIED (blank until a quantity is entered).",
             "Kit subtotals and the GRAND TOTAL are formulas; the GRAND TOTAL rolls to the Summary on its own line (Misc Parts is shown net of it)."]
    hdr = _open(ctx, ws, "DETAIL REGISTER", notes, widths, nvis)
    _hdr(ws, hdr, heads)
    r = hdr + 1
    subs = []
    first_all = r
    for k in t.kits:
        gold = k.no_steel
        base = GOLD if gold else KIT
        span(ws, r, 1, 2, f"{k.letter}.  {k.title}", F_GROUP if not gold else BOLD, base, A_LW, height=18)
        span(ws, r, 3, nvis, k.refs or None, NOTE if not gold else BOLD, base, A_LW)
        r += 1
        kf = r
        for i in range(max(len(k.items), 1)):
            it = k.items[i] if i < len(k.items) else None
            z = GOLD if gold else ZEBRA[i % 2]
            if it is None:
                for cc in range(1, nvis + 1):
                    put(ws, r, cc, None, TXT, YELLOW if (cc == 7 and not gold) else z)
                if not gold:
                    put(ws, r, 9, f'=IF(G{r}="","",F{r}*G{r})', BOLD, z, A_R, fmt=N1)
                r += 1
                continue
            put(ws, r, 1, it.detail_ref, TXT, z, A_LW)
            put(ws, r, 2, it.condition, TXT, z, A_LW)
            put(ws, r, 3, it.item, TXT, z, A_LW)
            put(ws, r, 4, it.size_spec, TXT, z, A_LW)
            put(ws, r, 5, it.unit_basis, TXT, z, A_LW)
            if gold:
                for cc in (6, 7, 8, 9, 10):
                    put(ws, r, cc, None, TXT, z)
                put(ws, r, 11, it.notes or None, TXT, z, A_LW)
                put(ws, r, 12, None, TXT, z)
                put(ws, r, 13, None, TXT, z)
            else:
                blank_lb = (not it.lb_per_unit) and it.qty_applied is None
                put(ws, r, 6, None if blank_lb else it.lb_per_unit, TXT, YELLOW if blank_lb else z, A_R, fmt=N2)
                put(ws, r, 7, it.qty_applied, BOLD, YELLOW, A_R)
                put(ws, r, 8, it.unit, TXT, z, A_C)
                put(ws, r, 9, f'=IF(G{r}="","",F{r}*G{r})', BOLD, z, A_R, fmt=N1)
                if it.qty_applied is None:
                    put(ws, r, 10, "NOT YET APPLIED", BOLD, ORANGE, A_LW)
                    nt = " · ".join(x for x in (it.notes, it.qty_source) if x)
                else:
                    put(ws, r, 10, it.qty_source or None, TXT, z, A_LW)
                    nt = it.notes
                put(ws, r, 11, nt or None, TXT, z, A_LW)
                put(ws, r, 12, _fin(it.finish), TXT, z, A_C)
                put(ws, r, 13, it.grade, TXT, z, A_L)
            _rfi_cell(ctx, ws, r, 14, it.rfi, z)
            r += 1
        kl = r - 1
        if not gold:
            _total_row(ws, r, 1, nvis, f"Subtotal — kit {k.letter}")
            put(ws, r, 9, f"=SUM(I{kf}:I{kl})", BOLD, SUBTOT, A_R, fmt=N0)
            subs.append(r)
            r += 1
        r += 1
    last_all = r - 2 if t.kits else r
    span(ws, r, 1, 8, "GRAND TOTAL — DETAIL REGISTER", F_BIGTOT, NAVY, A_L, height=20)
    put(ws, r, 9, ("=SUM(" + ",".join(f"I{x}" for x in subs) + ")") if subs else "=0", F_BIGTOT, NAVY, A_R, fmt=N0)
    for cc in range(10, nvis + 1):
        put(ws, r, cc, None, F_BIGTOT, NAVY)
    _anchor(ctx, DR, f"I{r}", "DETAIL_REGISTER_TOTAL_LBS")
    ctx.rng[DR] = dict(first=first_all, last=last_all, fin="L", lbs="I", qty="G")
    r += 2
    put(ws, r, 1, "HOW TO USE THIS TAB", F_SEC, None, A_L, border=False)
    r += 1
    how = [
        "1.  Yellow cells in QTY APPLIED are the inputs. Type a quantity and TOTAL LBS (LB PER UNIT x QTY APPLIED), the kit Subtotal, the GRAND TOTAL "
        "and the Summary all update. A blank QTY APPLIED carries no weight and reads NOT YET APPLIED in QTY SOURCE.",
        "2.  Each kit (A, B, C ...) is one repeating condition: a title row naming the details it covers, one row per steel item out of those details, "
        "then a Subtotal. Apply a kit to as many locations as the drawings show by changing the quantities, not the structure.",
        "3.  UNIT BASIS says what to multiply (per LF of edge, 1 per column, @ 2'-0\" o.c.). QTY SOURCE records where each quantity came from so it can be "
        "checked; FINISH (Primed / Galv) and GRADE ride with each item into the Finish Summary.",
        "4.  The GRAND TOTAL rolls to the Summary on its own line (Detail Register). Misc Parts is shown net of it — its gold memo row points here and is "
        "not added a second time.",
        "5.  The closing gold kit lists details reviewed that add no new steel (no quantities). Items tied to an RFI show the BSI-xx in the RFI column, "
        "filled by priority (P1 red, P2 orange, P3 yellow, INFO grey).",
    ]
    tot_w = sum(widths[:nvis])
    for ln in how:
        span(ws, r, 1, nvis, ln, TXT, None, A_LW, border=False, height=_height(ln, tot_w))
        r += 1
    _finish_sheet(ws, hdr, nvis)


# ----------------------------------------------------------------------------- 10 Beam Detail
def _beam_detail(ctx):
    t, ws = ctx.t, ctx.ws[BD]
    heads = ["SHEET", "SIZE", "STUDS / TAG", "LENGTH (FT-IN)", "LB/FT", "LBS", "NOTE / FLAG", "PLAN X (pt)", "PLAN Y (pt)", "RFI", "LENGTH (DEC FT)"]
    widths = [10, 14, 20, 14, 8, 12, 56, 11, 11, 12, 10]
    nvis = 10
    notes = ["Backup for the Beam Tonnage rollup: one row per beam callout. LENGTH is feet-inches (nearest 1/8\"); the hidden LENGTH (DEC FT) drives "
             "LBS = LB/FT x LENGTH. PLAN X / Y are the callout position in PDF points when the geometry method read it.",
             "The TOTAL below must tie to Beam Tonnage (check cell). Orange NOTE / FLAG = VERIFY item."]
    hdr = _open(ctx, ws, "BEAM DETAIL — BY MEMBER", notes, widths, nvis, hidden=[11])
    _hdr(ws, hdr, heads)
    r = hdr + 1
    first = r
    for i in range(max(len(t.beams), 1)):
        b = t.beams[i] if i < len(t.beams) else None
        z = ZEBRA[i % 2]
        orange = ORANGE if (b and b.allowance) else None
        put(ws, r, 1, b.sheet if b else None, TXT, z, A_C)
        put(ws, r, 2, b.size if b else None, TXT, orange or z, A_L)
        put(ws, r, 3, b.tag if b else None, TXT, z, A_L)
        put(ws, r, 4, _ft(f"K{r}"), BOLD, orange or z, A_R)
        put(ws, r, 5, b.lb_ft if b else None, TXT, z, A_R, fmt=N2)
        put(ws, r, 6, f'=IF(AND(ISNUMBER(E{r}),ISNUMBER(K{r})),E{r}*K{r},"")', BOLD, z, A_R, fmt=N1)
        nt = " · ".join(x for x in ((f"mark {b.mark}" if b and b.mark else ""), (b.note if b else ""), (b.flag if b else "")) if x)
        put(ws, r, 7, nt or None, TXT, ORANGE if (b and b.flag) else z, A_LW)
        put(ws, r, 8, b.x_pt if b else None, TXT, z, A_R, fmt="0.0")
        put(ws, r, 9, b.y_pt if b else None, TXT, z, A_R, fmt="0.0")
        _rfi_cell(ctx, ws, r, 10, b.rfi if b else [], z)
        put(ws, r, 11, b.length_ft if b else None, TXT, z, A_R, fmt="0.0000")
        r += 1
    last = r - 1
    _total_row(ws, r, 1, 5, "TOTAL", GROUP, F_GROUP)
    put(ws, r, 6, f"=SUM(F{first}:F{last})", F_GROUP, GROUP, A_R, fmt=N0)
    bt = ANCHORS[BT]
    put(ws, r, 7, f'=IF(ROUND(F{r}-{_q(BT)}!{bt},0)=0,"✓ ties to Beam Tonnage","CHECK — does not tie")', F_GROUP, GROUP, A_L)
    for cc in (8, 9, 10):
        put(ws, r, cc, None, F_GROUP, GROUP)
    _anchor(ctx, BD, f"F{r}", "BEAM_DETAIL_TOTAL_LBS")
    KEY_CELLS["Beam Detail check"] = f"G{r}"
    ctx.rng[BD] = dict(first=first, last=last, count_col="B")
    _finish_sheet(ws, hdr, nvis)


# ----------------------------------------------------------------------------- 11 S-Sheet Notes
def _sheet_notes(ctx):
    t, ws = ctx.t, ctx.ws[SN]
    widths = [12, 150]
    hdr = _open(ctx, ws, "S-SHEET NOTES", ["Reference only: the general notes, schedules and keynotes that drive material, finish, bolt and scope calls in this takeoff."],
                widths, 2)
    _hdr(ws, hdr, ["SHEET", "NOTE"], height=22)
    r = hdr + 1
    for i in range(max(len(t.notes), 1)):
        n = t.notes[i] if i < len(t.notes) else None
        z = ZEBRA[i % 2]
        put(ws, r, 1, n.sheet if n else None, BOLD, z, A_C)
        put(ws, r, 2, n.text if n else None, TXT, z, A_LW)
        r += 1
    _finish_sheet(ws, hdr, 2)


# ----------------------------------------------------------------------------- 1 Summary
def _summary(ctx):
    t, ws, h = ctx.t, ctx.ws[SUM], ctx.t.header
    W = [12.5] * 12
    nvis = 12
    scope = h.scope_summary or "Structural steel takeoff."
    info = (f"{h.rev}  ·  {h.date}  ·  Source: {', '.join(h.source_files) or '—'}  ·  {h.estimator}, {h.company}  ·  {h.address}")
    hdr = _open(ctx, ws, "TAKEOFF SUMMARY", [scope, info], W, nvis)
    inc = t.inclusions or t.scope.inclusions
    exc = t.exclusions or t.scope.exclusions
    # (a) inclusions / exclusions at the very top
    span(ws, hdr, 1, 6, "✓  INCLUDED — Bohling furnishes / fabricates", F_GREEN, GREEN, A_L, height=18)
    span(ws, hdr, 7, 12, "✗  EXCLUDED — by others", F_RED, RED, A_L)
    r = hdr + 1
    for i in range(max(len(inc), len(exc), 1)):
        lt = f"✓  {inc[i]}" if i < len(inc) else None
        rt = f"✗  {exc[i]}" if i < len(exc) else None
        ht = max(_height(lt or "", 75), _height(rt or "", 75))
        span(ws, r, 1, 6, lt, TXT, GREEN, A_LW, height=ht)
        span(ws, r, 7, 12, rt, TXT, RED, A_LW)
        r += 1
    r += 1

    # (b) drawings received
    put(ws, r, 1, "DRAWINGS RECEIVED TO DATE", F_SEC, None, A_L, border=False)
    r += 1
    _hdr_spans(ws, r, [(1, 1, "SHEET"), (2, 5, "DESCRIPTION"), (6, 7, "STATUS"), (8, 8, "DATE"), (9, 9, "STEEL"), (10, 12, "NOTES")])
    r += 1
    for i in range(max(len(t.sheets), 1)):
        s = t.sheets[i] if i < len(t.sheets) else None
        z = ZEBRA[i % 2]
        st = s.status if s else None
        late = bool(s and s.status.upper() != "RECEIVED")
        put(ws, r, 1, s.number if s else None, BOLD, z, A_C)
        span(ws, r, 2, 5, s.title if s else None, TXT, z, A_L)
        span(ws, r, 6, 7, st, BOLD if late else TXT, ORANGE if late else z, A_C)
        put(ws, r, 8, (s.date or None) if s else None, TXT, z, A_C)
        put(ws, r, 9, s.steel if s else None, TXT, z, A_C)
        span(ws, r, 10, 12, (s.notes or None) if s else None, TXT, z, A_LW, height=_height(s.notes if s else "", 37.5))
        r += 1
    r += 1

    # (c) tonnage summary
    put(ws, r, 1, "TONNAGE SUMMARY", F_SEC, None, A_L, border=False)
    r += 1
    _hdr_spans(ws, r, [(1, 3, "ITEM"), (4, 4, "LBS"), (5, 5, "TONS"), (6, 12, "NOTES")])
    r += 1
    ct_tot = ctx.rng[CT]["qty_total"]
    bt_pcs = ctx.rng[BT]["pieces_total"]
    lines = [
        ("Columns", CT, f'=IFERROR({_q(CT)}!{ct_tot}&" pieces — columns off the schedule / foundation plan (Column Tonnage).","")'),
        ("Beams", BT, f'=IFERROR({_q(BT)}!{bt_pcs}&" pieces — framing plans rolled up by sheet (Beam Tonnage).","")'),
        ("Detail Register", DR, "Section cuts / details / schedules in repeating kits — its own line (Detail Register)."),
        ("Misc Parts (net)", MP, "+ Misc Parts (base plates + connection material), net of the Detail Register."),
        ("Anchor Bolts", AB, "Anchor rods / anchor bolts (Anchor Bolt Summary) — keyed manually in Fabtrol."),
        ("Field Bolts", FB, "Field bolts and post-installed anchors (Field Bolts & Anchors) — keyed manually in Fabtrol."),
    ]
    first_line = r
    for i, (lab, tab, note) in enumerate(lines):
        z = ZEBRA[i % 2]
        span(ws, r, 1, 3, lab, BOLD, z, A_L)
        put(ws, r, 4, f"=IFERROR({_q(tab)}!{ANCHORS[tab]},0)", TXT, z, A_R, fmt=N0)
        put(ws, r, 5, f"=D{r}/2000", TXT, z, A_R, fmt=N2)
        span(ws, r, 6, 12, note, TXT, z, A_L)
        r += 1
    last_line = r - 1
    proj = r
    span(ws, r, 1, 3, "PROJECT TOTAL (steel)", F_BIGTOT, NAVY, A_L, height=20)
    put(ws, r, 4, f"=SUM(D{first_line}:D{last_line})", F_BIGTOT, NAVY, A_R, fmt=N0)
    put(ws, r, 5, f"=D{r}/2000", F_BIGTOT, NAVY, A_R, fmt=TONS)
    span(ws, r, 6, 12,
         f'=IFERROR("Columns "&{_q(CT)}!{ct_tot}&" pcs + beams "&{_q(BT)}!{bt_pcs}&" pcs = "&TEXT(D{r},"#,##0")&" lb ("&TEXT(E{r},"0.00")&" tons); avg "'
         f'&TEXT(D{r}/({_q(CT)}!{ct_tot}+{_q(BT)}!{bt_pcs}),"#,##0")&" lb per piece"&IF(E{r}>400,"  —  OVER 400 T: Bohling does not bid a single building over 400 T",""),"")',
         F_WHITE, NAVY, A_L)
    ANCHORS[SUM] = f"D{r}"
    KEY_CELLS["Summary PROJECT TOTAL lbs"] = f"D{r}"
    KEY_CELLS["Summary PROJECT TOTAL tons"] = f"E{r}"
    ctx.wb.defined_names["PROJECT_TOTAL_LBS"] = DefinedName("PROJECT_TOTAL_LBS", attr_text=f"{_q(SUM)}!$D${r}")
    r += 1
    # gold memo lines
    bt_q = _q(BT)

    def memo_formula(kind):
        cells = ctx.memo_cells[kind]
        return f"=IFERROR(" + "+".join(f"{bt_q}!{c}" for c in cells) + ",0)" if cells else None

    memos = [
        ("Open-web joists — memo", memo_formula("joist"), "NOT in the total: furnished by the joist supplier; weight shown for the record (Beam Tonnage memo rows)."),
        ("Roof deck — memo", memo_formula("deck"), "NOT in the total: deck by others; weight shown for the record (Beam Tonnage memo rows)."),
    ]
    if ctx.memo_cells["other"]:
        memos.append(("Other memo items", memo_formula("other"), "NOT in the total: Beam Tonnage memo rows."))
    memos.append(("Misc Metals — separate", f"=IFERROR({_q(MM)}!{ANCHORS[MM]},0)", "NOT in the total: stairs / ladders / rails / bollards (Misc Metals) — a separate deliverable."))
    for lab, f, note in memos:
        span(ws, r, 1, 3, lab, BOLD, GOLD, A_L)
        put(ws, r, 4, f, BOLD, GOLD, A_R, fmt=N0)
        put(ws, r, 5, f'=IF(D{r}="","",D{r}/2000)', BOLD, GOLD, A_R, fmt=N2)
        span(ws, r, 6, 12, note, TXT, GOLD, A_L)
        if lab.startswith("Misc Metals"):
            KEY_CELLS["Summary Misc Metals lbs"] = f"D{r}"
        r += 1
    r += 1

    # (d) revision log
    put(ws, r, 1, "REVISION LOG", F_SEC, None, A_L, border=False)
    r += 1
    _hdr_spans(ws, r, [(1, 1, "REV"), (2, 2, "DATE"), (3, 3, "WAS lbs"), (4, 4, "NOW lbs"), (5, 5, "Δ"), (6, 12, "NOTE")])
    r += 1
    revs = t.revisions or []
    for i in range(max(len(revs), 1)):
        v = revs[i] if i < len(revs) else None
        z = ZEBRA[i % 2]
        put(ws, r, 1, v.rev if v else None, BOLD, z, A_C)
        put(ws, r, 2, v.date if v else None, TXT, z, A_C)
        put(ws, r, 3, v.was_lbs if v else None, TXT, z, A_R, fmt=N0)
        now = v.now_lbs if v else None
        if v and now is None and i == len(revs) - 1:
            now = f"=D{proj}"                      # the current revision is the live PROJECT TOTAL
        put(ws, r, 4, now, TXT, z, A_R, fmt=N0)
        put(ws, r, 5, f'=IF(AND(ISNUMBER(C{r}),ISNUMBER(D{r})),D{r}-C{r},"")', TXT, z, A_R, fmt='+#,##0;-#,##0;0')
        span(ws, r, 6, 12, v.note if v else None, TXT, z, A_LW, height=_height(v.note if v else "", 87.5))
        r += 1
    r += 1

    # (e) project notes
    put(ws, r, 1, "PROJECT NOTES", F_SEC, None, A_L, border=False)
    r += 1
    pairs = [("Owner", h.owner), ("Architect", h.architect), ("Structural engineer (SER)", h.ser), ("General contractor", h.gc),
             ("Site", h.site), ("Bid due", h.bid_due), ("Drawing set", h.set_description)]
    for i, (lab, val) in enumerate(pairs):
        z = ZEBRA[i % 2]
        span(ws, r, 1, 3, lab, BOLD, z, A_L)
        span(ws, r, 4, 12, val or None, TXT, z, A_LW, height=_height(val or "", 112.5))
        r += 1
    r += 1

    # (f) assumptions
    put(ws, r, 1, "ASSUMPTIONS", F_SEC, None, A_L, border=False)
    r += 1
    for i, a in enumerate(t.assumptions or [None]):
        z = ZEBRA[i % 2]
        span(ws, r, 1, 12, f"•  {a}" if a else None, TXT, z, A_LW, height=_height(a or "", 150))
        r += 1
    r += 1

    # (g) flags
    put(ws, r, 1, "FLAGS / ITEMS FOR REVIEW (mirrors the RFI log)", F_SEC, None, A_L, border=False)
    r += 1
    _hdr_spans(ws, r, [(1, 1, "RFI"), (2, 2, "PRI"), (3, 3, "TO"), (4, 4, "STATUS"), (5, 7, "SUBJECT"), (8, 11, "WHERE FLAGGED"), (12, 12, "LBS CARRIED")])
    r += 1
    rfis = t.rfis or []
    for i in range(max(len(rfis), 1)):
        x = rfis[i] if i < len(rfis) else None
        f = PRI_FILL.get(x.priority) if x else None
        z = f or ZEBRA[i % 2]
        put(ws, r, 1, x.code if x else None, BOLD, z, A_C)
        put(ws, r, 2, x.priority if x else None, BOLD, z, A_C)
        put(ws, r, 3, x.to if x else None, TXT, z, A_C)
        put(ws, r, 4, x.status if x else None, TXT, z, A_C)
        ht = max(_height(x.subject if x else "", 37.5), _height(x.where_flagged if x else "", 50))
        span(ws, r, 5, 7, x.subject if x else None, TXT, z, A_LW, height=ht)
        span(ws, r, 8, 11, (x.where_flagged or None) if x else None, TXT, z, A_LW)
        put(ws, r, 12, x.lbs_flagged if x else None, TXT, z, A_R, fmt=N0)
        r += 1
    _finish_sheet(ws, hdr, nvis, freeze_row=hdr, titles=False)


# ----------------------------------------------------------------------------- 9 Finish Summary
def _finish_summary(ctx):
    t, ws = ctx.t, ctx.ws[FS]
    widths = [50, 11, 14, 11, 10, 70]
    nvis = 6
    notes = ["ROLLUP BY FINISH — SUMIF over each tab's FINISH column and its TOTAL LBS column, so a change on any tab flows here. Primed = shop primed "
             "(SSPC-SP2); Galv = hot-dip galvanized. HELD OUT = anchor rods and field bolts, keyed manually in Fabtrol rather than the KSS.",
             "RECONCILIATION: fabricated + held out must equal the Summary PROJECT TOTAL — VARIANCE reads 0. Misc Metals, joists and deck are outside the total."]
    hdr = _open(ctx, ws, "FINISH SUMMARY", notes, widths, nvis, label="ROLLUP BY FINISH — SCOPE ENCODED IN THE KSS (weights linked to the other tabs):")
    _hdr(ws, hdr, ["SCOPE / SOURCE", "PIECES", "LBS", "TONS", "FINISH", "BASIS"])
    R = ctx.rng

    def rollup_row(r, label, tab, finish, basis, pieces=True, z=None):
        g = R[tab]
        put(ws, r, 1, label, TXT, z, A_L)
        crit = f"$E{r}"
        fin_rng = _rng(tab, g["fin"], g["first"], g["last"])
        if pieces:
            put(ws, r, 2, f"=SUMIF({fin_rng},{crit},{_rng(tab, g['qty'], g['first'], g['last'])})", TXT, z, A_C, fmt=N0)
        else:
            put(ws, r, 2, None, TXT, z)
        put(ws, r, 3, f"=SUMIF({fin_rng},{crit},{_rng(tab, g['lbs'], g['first'], g['last'])})", TXT, z, A_R, fmt=N0)
        put(ws, r, 4, f"=C{r}/2000", TXT, z, A_R, fmt=N2)
        put(ws, r, 5, finish, BOLD, z, A_C)
        put(ws, r, 6, basis, TXT, z, A_LW)

    sources = [
        ("Columns — Column Tonnage", CT, "Column Tonnage: QTY and TOTAL LBS where FINISH matches.", True),
        ("Beams — Beam Tonnage rollup", BT, "Beam Tonnage rollup rows (joist / deck memo rows are outside).", True),
        ("Detail Register items", DR, "Detail Register items; pieces not totalled (units mix LF / EA / SET).", False),
        ("Misc Parts (net of Detail Register)", MP, "Misc Parts rows; the Detail Register memo row is outside.", True),
    ]
    r = hdr + 1
    sub_cells = {}
    for fin, band in (("Primed", "PRIMED — shop primed SSPC-SP2"), ("Galv", "GALVANIZED — hot-dip, shop galvanized")):
        _band(ws, r, 1, nvis, band)
        r += 1
        f0 = r
        for i, (lab, tab, basis, pcs) in enumerate(sources):
            rollup_row(r, lab, tab, fin, basis, pcs, ZEBRA[i % 2])
            r += 1
        _total_row(ws, r, 1, nvis, f"SUBTOTAL — {fin.upper()}")
        put(ws, r, 2, f"=SUM(B{f0}:B{r - 1})", BOLD, SUBTOT, A_C, fmt=N0)
        put(ws, r, 3, f"=SUM(C{f0}:C{r - 1})", BOLD, SUBTOT, A_R, fmt=N0)
        put(ws, r, 4, f"=C{r}/2000", BOLD, SUBTOT, A_R, fmt=N2)
        put(ws, r, 5, fin, BOLD, SUBTOT, A_C)
        sub_cells[fin] = r
        r += 2
    fab = r
    span(ws, r, 1, 1, "TOTAL FABRICATED", F_BIGTOT, NAVY, A_L, height=20)
    put(ws, r, 2, f"=B{sub_cells['Primed']}+B{sub_cells['Galv']}", F_BIGTOT, NAVY, A_C, fmt=N0)
    put(ws, r, 3, f"=C{sub_cells['Primed']}+C{sub_cells['Galv']}", F_BIGTOT, NAVY, A_R, fmt=N0)
    put(ws, r, 4, f"=C{r}/2000", F_BIGTOT, NAVY, A_R, fmt=TONS)
    put(ws, r, 5, None, F_BIGTOT, NAVY)
    put(ws, r, 6, "Primed + Galv, everything encoded in the KSS (columns, beams, detail kits, misc parts).", F_WHITE, NAVY, A_L)
    KEY_CELLS["Finish Summary TOTAL FABRICATED"] = f"C{r}"
    r += 2

    # HELD OUT
    put(ws, r, 1, "HELD OUT OF THE KSS — MANUAL ENTRY LIST", F_SEC, None, A_L, border=False)
    r += 1
    _hdr(ws, r, ["ITEM", "QTY", "LBS", "TONS", "FINISH", "WHY"], height=22)
    r += 1
    h0 = r
    held = [
        ("Anchor rods / anchor bolts (Anchor Bolt Summary total)", AB,
         "Standing rule: anchor bolts keyed manually. Plate washers on the rods are weighed in Misc Parts — list them with the rods on the manual-entry sheet."),
        ("Field bolts & anchors (Field Bolts total)", FB,
         "Standing rule: all fasteners keyed manually (A325 bolts, screw / Titen-type anchors)."),
    ]
    A_OF = Alignment(horizontal="left", vertical="center", indent=3)
    tot_rows = []
    for i, (lab, tab, why) in enumerate(held):
        g = R[tab]
        put(ws, r, 1, lab, BOLD, ZEBRA[0], A_L)
        put(ws, r, 2, f"={_q(tab)}!{g['total_ea']}", BOLD, ZEBRA[0], A_C, fmt=N0)
        put(ws, r, 3, f"={_q(tab)}!{ANCHORS[tab]}", BOLD, ZEBRA[0], A_R, fmt=N0)
        put(ws, r, 4, f"=C{r}/2000", BOLD, ZEBRA[0], A_R, fmt=N2)
        put(ws, r, 5, None, TXT, ZEBRA[0])
        put(ws, r, 6, why, TXT, ZEBRA[0], A_LW)
        t_row = r
        tot_rows.append(r)
        r += 1
        fin_rng = _rng(tab, g["fin"], g["first"], g["last"])
        for fin in ("Plain", "Galv"):
            put(ws, r, 1, f"of which {fin}", TXT, ZEBRA[1], A_OF)
            put(ws, r, 2, f"=SUMIF({fin_rng},$E{r},{_rng(tab, 'F', g['first'], g['last'])})", TXT, ZEBRA[1], A_C, fmt=N0)
            put(ws, r, 3, f"=SUMIF({fin_rng},$E{r},{_rng(tab, g['lbs'], g['first'], g['last'])})", TXT, ZEBRA[1], A_R, fmt=N0)
            put(ws, r, 4, f"=C{r}/2000", TXT, ZEBRA[1], A_R, fmt=N2)
            put(ws, r, 5, fin, BOLD, ZEBRA[1], A_C)
            if fin == "Plain":
                put(ws, r, 6, "Split by FINISH (SUMIF) — memo, not added again.", NOTE, ZEBRA[1], A_L)
            else:
                put(ws, r, 6, f'=IF(ROUND(C{r - 1}+C{r}-C{t_row},2)=0,"✓ Plain + Galv = total above","CHECK — a FINISH cell is not Plain / Galv")',
                    NOTE, ZEBRA[1], A_L)
            r += 1
    held_tot = r
    _total_row(ws, r, 1, nvis, "SUBTOTAL — HELD OUT")
    put(ws, r, 2, "=" + "+".join(f"B{x}" for x in tot_rows), BOLD, SUBTOT, A_C, fmt=N0)
    put(ws, r, 3, "=" + "+".join(f"C{x}" for x in tot_rows), BOLD, SUBTOT, A_R, fmt=N0)
    put(ws, r, 4, f"=C{r}/2000", BOLD, SUBTOT, A_R, fmt=N2)
    put(ws, r, 6, "Anchor Bolt + Field Bolt grand totals ('of which' lines not added).", BOLD, SUBTOT, A_L)
    r += 2

    # RECONCILIATION
    put(ws, r, 1, "RECONCILIATION AGAINST THE TAKEOFF", F_SEC, None, A_L, border=False)
    r += 1
    rec1 = r
    put(ws, r, 1, "Fabricated (Primed + Galv) + held out", TXT, ZEBRA[0], A_L)
    put(ws, r, 2, None, TXT, ZEBRA[0])
    put(ws, r, 3, f"=C{fab}+C{held_tot}", BOLD, ZEBRA[0], A_R, fmt=N0)
    put(ws, r, 4, f"=C{r}/2000", TXT, ZEBRA[0], A_R, fmt=N2)
    put(ws, r, 5, None, TXT, ZEBRA[0])
    put(ws, r, 6, "Everything this workbook carries in the project tonnage.", TXT, ZEBRA[0], A_L)
    r += 1
    rec2 = r
    put(ws, r, 1, "Summary tab PROJECT TOTAL (steel)", TXT, ZEBRA[1], A_L)
    put(ws, r, 2, None, TXT, ZEBRA[1])
    put(ws, r, 3, f"={_q(SUM)}!{ANCHORS[SUM]}", BOLD, ZEBRA[1], A_R, fmt=N0)
    put(ws, r, 4, f"=C{r}/2000", TXT, ZEBRA[1], A_R, fmt=N2)
    put(ws, r, 5, None, TXT, ZEBRA[1])
    put(ws, r, 6, "Columns + Beams + Detail Register + Misc Parts (net) + Anchor Bolts + Field Bolts.", TXT, ZEBRA[1], A_L)
    r += 1
    put(ws, r, 1, "VARIANCE", BOLD, YELLOW, A_L)
    put(ws, r, 2, None, TXT, YELLOW)
    put(ws, r, 3, f"=ROUND(C{rec1}-C{rec2},2)", BOLD, YELLOW, A_R, fmt='0.00;-0.00;0')
    put(ws, r, 4, f"=C{r}/2000", BOLD, YELLOW, A_R, fmt='0.000;-0.000;0')
    put(ws, r, 5, None, TXT, YELLOW)
    put(ws, r, 6, f'=IF(ABS(C{r})<0.5,"✓ VARIANCE 0 — every pound is either fabricated or held out","CHECK — variance: a FINISH cell is not Primed / Galv (Plain / Galv for hardware) or a total is stale")',
        BOLD, YELLOW, A_L)
    _anchor(ctx, FS, f"C{r}", "FINISH_SUMMARY_VARIANCE")
    KEY_CELLS["Finish Summary VARIANCE"] = f"C{r}"
    r += 2

    # PIECE COUNT CHECK
    put(ws, r, 1, "PIECE COUNT CHECK — TAKEOFF vs FINISH ROLLUP", F_SEC, None, A_L, border=False)
    r += 1
    _hdr(ws, r, ["ITEM", "TAKEOFF", "ROLLUP", "DELTA", "", "SOURCE"], height=22)
    r += 1
    bd = R[BD]
    counts = [
        ("Columns (sum of QTY)", f"={_q(CT)}!{R[CT]['qty_total']}",
         f"=B{sub_cells['Primed'] - 4}+B{sub_cells['Galv'] - 4}", "Column Tonnage TOTAL vs Primed + Galv column lines"),
        ("Beams (callouts on Beam Detail)", f"=COUNTA({_rng(BD, bd['count_col'], bd['first'], bd['last'])})",
         f"=B{sub_cells['Primed'] - 3}+B{sub_cells['Galv'] - 3}", "Beam Detail rows vs Primed + Galv beam lines"),
        ("Beams (Beam Tonnage SUMMARY BY SHEET)", f"={_q(BT)}!{R[BT]['pieces_total']}",
         f"=B{sub_cells['Primed'] - 3}+B{sub_cells['Galv'] - 3}", "Beam Tonnage PIECES total vs Primed + Galv beam lines"),
    ]
    for i, (lab, a, b, src) in enumerate(counts):
        z = ZEBRA[i % 2]
        put(ws, r, 1, lab, TXT, z, A_L)
        put(ws, r, 2, a, TXT, z, A_C, fmt=N0)
        put(ws, r, 3, b, TXT, z, A_C, fmt=N0)
        put(ws, r, 4, f"=C{r}-B{r}", BOLD, z, A_C, fmt='0;-0;0')
        put(ws, r, 5, f'=IF(D{r}=0,"✓","CHECK")', BOLD, z, A_C)
        put(ws, r, 6, src, TXT, z, A_L)
        r += 1
    KEY_CELLS["Finish Summary piece count first row"] = f"D{r - len(counts)}"
    r += 1

    # GALVANIZED BUT UNQUANTIFIED
    put(ws, r, 1, "GALVANIZED BUT UNQUANTIFIED — scope identified, no length / count to weigh yet", F_SEC, None, A_L, border=False)
    r += 1
    items = t.galv_unquantified or ["(none identified)"]
    for it in items:
        span(ws, r, 1, nvis, it, TXT, LBLUE, A_LW, height=_height(it, sum(widths)))
        r += 1
    r += 1
    span(ws, r, 1, nvis, "Every figure on this tab is a formula off the other tabs; the only typed text is labels and the unquantified list.",
         NOTE, None, A_LW, border=False)
    _finish_sheet(ws, hdr, nvis)


# ----------------------------------------------------------------------------- 12 Model Geometry
def _model_geometry(ctx):
    t, h = ctx.t, ctx.t.header
    job = {"job": h.job, "job_code": h.job_code, "building": h.building, "rev": h.rev, "date": h.date,
           "source": ", ".join(h.source_files), "datum": {"description": DEFAULT_DATUM}, "grids": {"X": {}, "Y": {}}, "storeys": []}
    rows = [dataclasses.asdict(g) for g in t.geometry]
    empty = not rows
    if empty:                      # geometry_tab needs one data row to freeze under; scrubbed below so the tab reads 0 pcs
        rows = [{}]
    ws = add_model_geometry_tab(ctx.wb, job, rows, status=h.status)
    if empty:
        hdr = next(c.row for c in ws["A"] if c.value == "MARK")
        for c in ws[hdr + 1]:
            if c.value == "":
                c.value = None
    # locate the TOTAL row written by the shared function
    for row in ws.iter_rows(min_col=1, max_col=1):
        v = row[0].value
        if isinstance(v, str) and v.startswith("TOTAL"):
            tr = row[0].row
            lbs_col = CL(VISIBLE.index("LBS") + 1)
            len_col = CL(VISIBLE.index("LENGTH") + 1)
            _anchor(ctx, MG, f"{lbs_col}{tr}", "MODEL_GEOMETRY_TOTAL_LBS")
            KEY_CELLS["Model Geometry pieces"] = f"{len_col}{tr}"
            break


# ----------------------------------------------------------------------------- entry point
def build_workbook(takeoff: Takeoff, out_path: str) -> str:
    """Write the 12-tab Bohling takeoff workbook for `takeoff` to `out_path` and return the path.

    Side effects: module-level ANCHORS / KEY_CELLS are reset and filled with this build's grand-total cells
    (see the module docstring); the same cells are written into the file as defined names.
    """
    ANCHORS.clear()
    KEY_CELLS.clear()
    wb = Workbook()
    ctx = _Ctx(takeoff, wb)
    # dependency order: leaf tabs first, then the tabs that point at them
    _column_tonnage(ctx)
    _beam_tonnage(ctx)
    _anchor_bolts(ctx)
    _field_bolts(ctx)
    _detail_register(ctx)
    _misc_parts(ctx)          # memo row points at the Detail Register total
    _misc_metals(ctx)
    _beam_detail(ctx)         # check cell points at the Beam Tonnage total
    _summary(ctx)
    _finish_summary(ctx)      # reconciles against the Summary PROJECT TOTAL
    _sheet_notes(ctx)
    _model_geometry(ctx)
    assert wb.sheetnames == TABS, wb.sheetnames
    d = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(d, exist_ok=True)
    wb.save(out_path)
    return out_path

