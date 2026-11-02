"""
Tests for the 12-tab takeoff workbook builder (bsi_model_builder/takeoff/workbook.py, spec docs/BSI_STANDARDS.md §2).

Structure / style / formula checks run on the file as written; the numeric checks run on a LibreOffice-recalculated
copy (/mnt/skills/public/xlsx/scripts/recalc.py) and are skipped when that script is not on the machine.
"""
import copy
import dataclasses
import json
import math
import os
import re
import shutil
import subprocess
import sys

import openpyxl
import pytest
from openpyxl.utils import column_index_from_string

from bsi_model_builder.takeoff import workbook as W
from bsi_model_builder.takeoff.model import Takeoff
from bsi_model_builder.takeoff.sample import sample_takeoff
from bsi_model_builder.takeoff.workbook import build_workbook

RECALC = "/mnt/skills/public/xlsx/scripts/recalc.py"
DATA = os.path.join(os.path.dirname(__file__), "data")
FTIN = re.compile(r"^-?\d+'-\d+( [1-7]/[248])?\"$")

TABS = ["Summary", "Column Tonnage", "Beam Tonnage", "Anchor Bolt Summary", "Field Bolts & Anchors", "Misc Parts", "Misc Metals",
        "Detail Register", "Finish Summary", "Beam Detail — by Member", "S-Sheet Notes", "Model Geometry"]
STEEL_FINISH_TABS = ["Column Tonnage", "Beam Tonnage", "Misc Parts", "Misc Metals", "Detail Register"]
HARDWARE_FINISH_TABS = ["Anchor Bolt Summary", "Field Bolts & Anchors"]


# ----------------------------------------------------------------------------- fixtures / helpers
@pytest.fixture(scope="module")
def built(tmp_path_factory):
    t = sample_takeoff()
    d = tmp_path_factory.mktemp("wb")
    path = build_workbook(t, str(d / "Sample_Takeoff.xlsx"))
    assert path == str(d / "Sample_Takeoff.xlsx")
    return t, path, dict(W.ANCHORS), dict(W.KEY_CELLS)


def _recalc(path):
    if not os.path.exists(RECALC):
        pytest.skip("recalc.py not available on this machine")
    r = subprocess.run([sys.executable, RECALC, path, "120"], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout[r.stdout.index("{"):])
    assert '"total_errors": 0' in json.dumps(out, indent=2), out
    return out


@pytest.fixture(scope="module")
def recalced(built, tmp_path_factory):
    t, path, anchors, keys = built
    if not os.path.exists(RECALC):
        pytest.skip("recalc.py not available on this machine")
    q = str(tmp_path_factory.mktemp("rc") / "Sample_Takeoff_recalc.xlsx")
    shutil.copy(path, q)
    out = _recalc(q)
    return q, out


def _find(ws, text, col=None, startswith=False):
    """first cell whose text equals (or starts with) `text`"""
    for row in ws.iter_rows(min_col=col or 1, max_col=col or ws.max_column):
        for c in row:
            if isinstance(c.value, str) and (c.value.startswith(text) if startswith else c.value == text):
                return c
    raise AssertionError(f"{text!r} not found on {ws.title}")


def _header_row(ws, first_header):
    """row number of the blue header row that contains `first_header` in col A"""
    for row in ws.iter_rows(min_col=1, max_col=1):
        c = row[0]
        if c.value == first_header and c.fill.fgColor.rgb[-6:] == "2E75B6":
            return c.row
    raise AssertionError(first_header)


def _cols(ws, hdr_row):
    return {c.value: c.column for c in ws[hdr_row] if c.value}


def _hidden(ws):
    out = set()
    for k, d in ws.column_dimensions.items():
        if d.hidden:
            lo = d.min or column_index_from_string(k)
            out.update(range(lo, (d.max or lo) + 1))
    return out


def _fill(c):
    return c.fill.fgColor.rgb[-6:] if c.fill and c.fill.fill_type == "solid" else None


def _headers(ws):
    """every blue header cell on the sheet as (cell)"""
    return [c for row in ws.iter_rows() for c in row if c.value and _fill(c) == "2E75B6"]


# ----------------------------------------------------------------------------- structure
def test_tabs_in_order(built):
    t, path, anchors, keys = built
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == TABS


def test_anchor_map_complete(built):
    t, path, anchors, keys = built
    assert set(anchors) == set(TABS) - {"S-Sheet Notes"}
    wb = openpyxl.load_workbook(path)
    for tab, cell in anchors.items():
        v = wb[tab][cell].value
        assert isinstance(v, str) and v.startswith("="), (tab, cell, v)
    # also exposed as defined names
    assert "PROJECT_TOTAL_LBS" in wb.defined_names and "COLUMN_TONNAGE_TOTAL_LBS" in wb.defined_names


def test_house_style_on_every_tab(built):
    t, path, anchors, keys = built
    wb = openpyxl.load_workbook(path)
    for ws in wb:
        assert ws.sheet_view.showGridLines is False, ws.title
        assert ws.freeze_panes, ws.title
        a1 = ws["A1"]
        assert a1.value and " | " in a1.value and a1.value.startswith(t.header.job.upper()), (ws.title, a1.value)
        assert t.header.status in a1.value
        assert _fill(a1) == "1F3864" and a1.font.bold and a1.font.color.rgb[-6:] == "FFFFFF" and a1.font.name == "Arial", ws.title
        hdrs = _headers(ws)
        assert hdrs, ws.title
        for h in hdrs:
            assert h.font.bold and h.font.color.rgb[-6:] == "FFFFFF", (ws.title, h.coordinate)
        for row in ws.iter_rows():
            for c in row:
                if c.value not in (None, ""):
                    assert c.font.name == "Arial", (ws.title, c.coordinate, c.font.name)
    assert wb["Column Tonnage"]["A1"].value == "SAMPLE SHELL BUILDING | COLUMN TONNAGE | DRAFT — SAMPLE"


def test_totals_are_formulas_not_numbers(built):
    """every row labelled TOTAL / Subtotal / GRAND TOTAL / CHECK TOTAL carries formulas, never typed numbers"""
    t, path, anchors, keys = built
    wb = openpyxl.load_workbook(path)
    pat = re.compile(r"^(TOTAL|Subtotal|SUBTOTAL|GRAND TOTAL|COLUMN GRAND TOTAL|PROJECT TOTAL|CHECK TOTAL)\b")
    seen = 0
    for ws in wb:
        if ws.title == "Model Geometry":
            continue
        for row in ws.iter_rows():
            first = row[0]
            if isinstance(first.value, str) and pat.match(first.value):
                seen += 1
                for c in row[1:]:
                    assert not isinstance(c.value, (int, float)), (ws.title, c.coordinate, c.value)
    assert seen >= 20


def test_summary_rollups_point_at_fixed_cells(built):
    t, path, anchors, keys = built
    ws = openpyxl.load_workbook(path)["Summary"]
    pat = re.compile(r"^=IFERROR\('([^']+)'!([A-Z]+\d+),0\)$")
    want = {"Columns": "Column Tonnage", "Beams": "Beam Tonnage", "Detail Register": "Detail Register", "Misc Parts (net)": "Misc Parts",
            "Anchor Bolts": "Anchor Bolt Summary", "Field Bolts": "Field Bolts & Anchors"}
    first = None
    for label, tab in want.items():
        c = _find(ws, label, col=1)
        first = first or c.row
        m = pat.match(ws.cell(row=c.row, column=4).value)
        assert m and m.group(1) == tab and m.group(2) == anchors[tab], (label, ws.cell(row=c.row, column=4).value)
        assert ws.cell(row=c.row, column=5).value == f"=D{c.row}/2000"
    proj = _find(ws, "PROJECT TOTAL", col=1, startswith=True)
    assert anchors["Summary"] == f"D{proj.row}" and keys["Summary PROJECT TOTAL tons"] == f"E{proj.row}"
    assert ws.cell(row=proj.row, column=4).value == f"=SUM(D{first}:D{proj.row - 1})"
    assert ws.cell(row=proj.row, column=5).value == f"=D{proj.row}/2000"
    # gold memo lines sit below the total and are not inside the SUM
    for label in ("Open-web joists", "Roof deck", "Misc Metals"):
        c = _find(ws, label, col=1, startswith=True)
        assert c.row > proj.row and _fill(c) == "FFE699"
        assert "IFERROR(" in ws.cell(row=c.row, column=4).value
    # block order: inclusions at the very top, then drawings, tonnage, revision log, notes, assumptions, flags
    order = ["✓  INCLUDED", "DRAWINGS RECEIVED TO DATE", "TONNAGE SUMMARY", "REVISION LOG", "PROJECT NOTES", "ASSUMPTIONS", "FLAGS"]
    rows = [_find(ws, o, startswith=True).row for o in order]
    assert rows == sorted(rows) and rows[0] <= 6


def test_summary_inclusions_flags_and_priority_fills(built):
    t, path, anchors, keys = built
    ws = openpyxl.load_workbook(path)["Summary"]
    inc = _find(ws, "✓  INCLUDED", startswith=True)
    exc = _find(ws, "✗  EXCLUDED", startswith=True)
    assert inc.row == exc.row and _fill(inc) == "E2EFDA" and _fill(exc) == "FBE2E2"
    assert _fill(ws.cell(row=inc.row + 1, column=1)) == "E2EFDA" and _fill(ws.cell(row=inc.row + 1, column=7)) == "FBE2E2"
    hdr = _find(ws, "RFI", col=1)
    heads = [c.value for c in ws[hdr.row] if c.value]
    assert heads == ["RFI", "PRI", "TO", "STATUS", "SUBJECT", "WHERE FLAGGED", "LBS CARRIED"]
    pri = {"P1": "F4CCCC", "P2": "FCE4D6", "P3": "FFF2CC", "INFO": "E7E6E6"}
    for i, r in enumerate(t.rfis, start=1):
        row = hdr.row + i
        assert ws.cell(row=row, column=1).value == r.code
        assert _fill(ws.cell(row=row, column=1)) == pri[r.priority]
        assert ws.cell(row=row, column=12).value == pytest.approx(r.lbs_flagged)


# ----------------------------------------------------------------------------- RFI colours / allowances / FINISH
def test_rfi_cells_filled_by_priority(built):
    t, path, anchors, keys = built
    wb = openpyxl.load_workbook(path)
    # P1 on the three C2 columns
    ws = wb["Column Tonnage"]
    h = _header_row(ws, "MARK / LOCATION"); col = _cols(ws, h)
    assert col["RFI"] == max(col[k] for k in col if k not in ("HEIGHT (DEC FT)",))          # trailing visible column
    hits = [r for r in range(h + 1, ws.max_row) if ws.cell(row=r, column=col["RFI"]).value == "BSI-01"]
    assert len(hits) == 3 and all(_fill(ws.cell(row=r, column=col["RFI"])) == "F4CCCC" for r in hits)
    # P2 on the sloped girders (Beam Tonnage rollup) and Beam Detail
    ws = wb["Beam Tonnage"]
    h = _header_row(ws, "SIZE"); col = _cols(ws, h)
    c = [ws.cell(row=r, column=col["RFI"]) for r in range(h + 1, ws.max_row) if ws.cell(row=r, column=col["RFI"]).value == "BSI-02"]
    assert len(c) == 1 and _fill(c[0]) == "FCE4D6"
    ws = wb["Beam Detail — by Member"]
    h = _header_row(ws, "SHEET"); col = _cols(ws, h)
    c = [ws.cell(row=r, column=col["RFI"]) for r in range(h + 1, ws.max_row) if ws.cell(row=r, column=col["RFI"]).value == "BSI-02"]
    assert len(c) == 3 and all(_fill(x) == "FCE4D6" for x in c)
    # P3 anchor rods, INFO ladder, P2 detail kit
    ws = wb["Anchor Bolt Summary"]; h = _header_row(ws, "LOCATION"); col = _cols(ws, h)
    c = [ws.cell(row=r, column=col["RFI"]) for r in range(h + 1, ws.max_row) if ws.cell(row=r, column=col["RFI"]).value == "BSI-03"]
    assert len(c) == 1 and _fill(c[0]) == "FFF2CC"
    ws = wb["Misc Metals"]; h = _header_row(ws, "QTY"); col = _cols(ws, h)
    r = [r for r in range(h + 1, ws.max_row) if ws.cell(row=r, column=col["RFI"]).value == "BSI-04"]
    assert len(r) == 1 and _fill(ws.cell(row=r[0], column=col["RFI"])) == "E7E6E6"
    # allowance row: ORANGE on its QTY / size cells
    assert _fill(ws.cell(row=r[0], column=col["QTY"])) == "FCE4D6" and _fill(ws.cell(row=r[0], column=col["SIZE / DIMENSIONS"])) == "FCE4D6"
    ws = wb["Detail Register"]; h = _header_row(ws, "DETAIL REF"); col = _cols(ws, h)
    c = [ws.cell(row=r, column=col["RFI"]) for r in range(h + 1, ws.max_row) if ws.cell(row=r, column=col["RFI"]).value == "BSI-05"]
    assert len(c) == 1 and _fill(c[0]) == "FCE4D6"


def test_multiple_codes_take_highest_priority(tmp_path):
    t = sample_takeoff()
    t.columns[0].rfi = ["BSI-03", "BSI-01", "BSI-02"]          # P3, P1, P2  -> P1 colour
    t.columns[1].rfi = ["BSI-03", "BSI-04"]                    # P3, INFO     -> P3 colour
    t.columns[2].allowance = True
    ws = openpyxl.load_workbook(build_workbook(t, str(tmp_path / "m.xlsx")))["Column Tonnage"]
    h = _header_row(ws, "MARK / LOCATION"); col = _cols(ws, h)
    r0 = h + 2
    assert ws.cell(row=r0, column=col["RFI"]).value == "BSI-03, BSI-01, BSI-02"
    assert _fill(ws.cell(row=r0, column=col["RFI"])) == "F4CCCC"
    assert _fill(ws.cell(row=r0 + 1, column=col["RFI"])) == "FFF2CC"
    assert _fill(ws.cell(row=r0 + 2, column=col["QTY"])) == "FCE4D6" and _fill(ws.cell(row=r0 + 2, column=col["SIZE"])) == "FCE4D6"


def test_finish_header_and_values(built):
    t, path, anchors, keys = built
    wb = openpyxl.load_workbook(path)
    for ws in wb:
        for c in _headers(ws):
            up = str(c.value).upper()
            if up.startswith("FINISH") or up.startswith("GALV"):
                assert c.value == "FINISH", (ws.title, c.coordinate, c.value)
    for tab, allowed in [(x, {"Primed", "Galv"}) for x in STEEL_FINISH_TABS] + [(x, {"Plain", "Galv"}) for x in HARDWARE_FINISH_TABS]:
        ws = wb[tab]
        fins = [c for c in _headers(ws) if c.value == "FINISH"]
        assert len(fins) == 1, tab
        vals = {ws.cell(row=r, column=fins[0].column).value for r in range(fins[0].row + 1, ws.max_row + 1)} - {None}
        assert vals and vals <= allowed, (tab, vals)
    # Model Geometry (shared function) also uses the exact header
    assert any(c.value == "FINISH" for c in _headers(wb["Model Geometry"]))


# ----------------------------------------------------------------------------- hidden decimal helpers / ft-in
def test_visible_lengths_are_formulas_over_hidden_helpers(built):
    t, path, anchors, keys = built
    wb = openpyxl.load_workbook(path)
    checked = 0
    for tab in ("Column Tonnage", "Beam Tonnage", "Anchor Bolt Summary", "Misc Parts", "Misc Metals", "Beam Detail — by Member"):
        ws = wb[tab]
        hidden = _hidden(ws)
        assert hidden, tab
        for c in _headers(ws):
            txt = str(c.value)
            if "DEC FT" in txt:
                assert c.column in hidden, (tab, txt)
            elif ("HEIGHT" in txt or "LENGTH" in txt or "TOTAL LF" in txt):
                assert c.column not in hidden, (tab, txt)
                for r in range(c.row + 1, ws.max_row + 1):
                    if _fill(ws.cell(row=r, column=c.column)) == "2E75B6":          # next table's header in the same column
                        break
                    v = ws.cell(row=r, column=c.column).value
                    if isinstance(v, str) and v.startswith("="):
                        checked += 1
                        assert "CHOOSE(MOD(ROUND(" in v and '"\'-"' in v.replace("&amp;", "&"), (tab, r, v)
                        ref = re.search(r'IF\(([A-Z]+)\d+=""', v).group(1)
                        assert column_index_from_string(ref) in hidden, (tab, r, v)
    assert checked >= 30
    # weights are driven by the hidden helper, not by the displayed text
    ws = wb["Column Tonnage"]
    h = _header_row(ws, "MARK / LOCATION"); col = _cols(ws, h)
    r = h + 2
    assert ws.cell(row=r, column=col["COL LBS"]).value == f'=IF(AND(ISNUMBER(O{r}),ISNUMBER(F{r})),O{r}*F{r},"")'
    assert col["HEIGHT (DEC FT)"] == 15 and ws.cell(row=r, column=15).value == 16.0


# ----------------------------------------------------------------------------- per-tab layout
def test_column_tonnage_layout(built):
    t, path, anchors, keys = built
    ws = openpyxl.load_workbook(path)["Column Tonnage"]
    h = _header_row(ws, "MARK / LOCATION")
    assert [c.value for c in ws[h] if c.value] == ["MARK / LOCATION", "QTY", "SIZE", "BASE PLATE", "HEIGHT (FT-IN)", "LB/FT", "COL LBS", "TOTAL LBS",
                                                   "BP ELEV (T/FTG → T/STL)", "ANCHORS", "FINISH", "GRADE", "NOTES / SOURCE", "RFI", "HEIGHT (DEC FT)"]
    tot = _find(ws, "TOTAL — COLUMNS", col=1)
    assert ws.cell(row=tot.row, column=8).value.startswith("=SUM(H") and ws.cell(row=tot.row, column=2).value.startswith("=SUM(B")
    _find(ws, "▶  BY SIZE SUMMARY", col=1)
    sizes = [ws.cell(row=r, column=1).value for r in range(1, ws.max_row + 1)]
    for sz in ("HSS6x6x3/8", "HSS6x6x1/2"):
        r = sizes.index(sz) + 1
        assert ws.cell(row=r, column=2).value.startswith("=SUMIF(") and ws.cell(row=r, column=5).value.startswith("=SUMIF(")
    g = _find(ws, "COLUMN GRAND TOTAL", col=1, startswith=True)
    assert anchors["Column Tonnage"] == f"H{g.row}" and ws.cell(row=g.row, column=9).value == f"=H{g.row}/2000"


def test_beam_tonnage_layout(built):
    t, path, anchors, keys = built
    ws = openpyxl.load_workbook(path)["Beam Tonnage"]
    _find(ws, "SUMMARY BY SHEET:", col=1)
    h0 = _header_row(ws, "SHEET")
    assert [c.value for c in ws[h0] if c.value] == ["SHEET", "DESCRIPTION", "PIECES", "LBS", "TONS"]
    tot = _find(ws, "TOTAL — BEAMS", col=1, startswith=True)
    assert anchors["Beam Tonnage"] == f"G{tot.row}"
    assert "SUMIF(" in ws.cell(row=h0 + 1, column=7).value and "$B$" in ws.cell(row=h0 + 1, column=7).value      # SUMIF on the SHEET column
    h = _header_row(ws, "SIZE")
    assert [c.value for c in ws[h] if c.value][:10] == ["SIZE", "SHEET", "QTY", "LB/FT", "LENGTH (FT-IN)", "TOTAL LBS", "FINISH", "GRADE", "NOTES", "RFI"]
    rollup = [r for r in range(h + 1, ws.max_row) if ws.cell(row=r, column=2).value == "S102" and ws.cell(row=r, column=3).value
              and _fill(ws.cell(row=r, column=1)) != "FFE699"]
    assert len(rollup) == len(sample_takeoff().beam_rollup()) == 3
    # memo rows: gold, shown, and not referenced by any total
    memo_rows = [r for r in range(h, ws.max_row) if _fill(ws.cell(row=r, column=1)) == "FFE699" and ws.cell(row=r, column=3).value]
    assert len(memo_rows) == len(t.memo) == 2
    for r in memo_rows:
        assert str(ws.cell(row=r, column=6).value).startswith("=IF(")
        for rr in range(1, ws.max_row + 1):
            for c in ws[rr]:
                if isinstance(c.value, str) and c.value.startswith("=") and rr not in memo_rows:
                    assert f"F{r}" not in re.findall(r"[A-Z]+\d+", c.value), (c.coordinate, c.value)
    # BY SIZE SUMMARY via SUMIF
    r = [r for r in range(1, ws.max_row + 1) if ws.cell(row=r, column=1).value == "W16x31" and ws.cell(row=r, column=3).value and str(ws.cell(row=r, column=3).value).startswith("=SUMIF")]
    assert r


def test_anchor_and_bolt_groups(built):
    t, path, anchors, keys = built
    wb = openpyxl.load_workbook(path)
    ws = wb["Anchor Bolt Summary"]
    h = _header_row(ws, "LOCATION")
    assert [c.value for c in ws[h] if c.value][:13] == ["LOCATION", "MEMBER", "AB DIAMETER", "AB PER ITEM", "ITEM QTY", "TOTAL ABs", "AB LENGTH", "LB/EA",
                                                         "TOTAL LBS", "FINISH", "GRADE", "NOTES / SOURCE", "RFI"]
    for g in ("COLUMN ABS", "ADDITIONAL AB GROUPS", "LINTEL ABS"):
        assert any(str(ws.cell(row=r, column=1).value or "").upper().endswith(g) for r in range(h, ws.max_row)), g
    gt = _find(ws, "GRAND TOTAL — ANCHOR BOLTS", col=1)
    assert anchors["Anchor Bolt Summary"] == f"I{gt.row}" and ws.cell(row=gt.row, column=9).value.startswith("=I")
    r = h + 2
    assert ws.cell(row=r, column=6).value == f'=IF(AND(ISNUMBER(D{r}),ISNUMBER(E{r})),D{r}*E{r},"")'
    assert ws.cell(row=r, column=9).value == f'=IF(AND(ISNUMBER(F{r}),ISNUMBER(H{r})),F{r}*H{r},"")'
    ws = wb["Field Bolts & Anchors"]
    h = _header_row(ws, "CONNECTION TYPE")
    assert [c.value for c in ws[h] if c.value] == ["CONNECTION TYPE", "LOCATION", "BOLT / ANCHOR SPEC", "PER CONN.", "CONN. QTY", "TOTAL EA", "LB/EA",
                                                   "TOTAL LBS", "FINISH", "NOTES / SOURCE", "RFI"]
    for g in ("BEAM-TO-BEAM SHEAR", "BEAM-ON-COLUMN CAP PLATE", "MOMENT", "BRACE", "POST-INSTALLED"):
        assert any(str(ws.cell(row=r, column=1).value or "").upper().endswith(g) for r in range(h, ws.max_row)), g
    gt = _find(ws, "GRAND TOTAL", col=1, startswith=True)
    assert anchors["Field Bolts & Anchors"] == f"H{gt.row}"
    r = h + 2
    assert ws.cell(row=r, column=6).value == f'=IF(AND(ISNUMBER(D{r}),ISNUMBER(E{r})),D{r}*E{r},"")'
    assert ws.cell(row=r, column=8).value == f'=IF(AND(ISNUMBER(F{r}),ISNUMBER(G{r})),F{r}*G{r},"")'


def test_misc_parts_memo_and_misc_metals(built):
    t, path, anchors, keys = built
    wb = openpyxl.load_workbook(path)
    ws = wb["Misc Parts"]
    h = _header_row(ws, "QTY")
    assert [c.value for c in ws[h] if c.value][:12] == ["QTY", "SHAPE", "THICKNESS", "SIZE / DIMENSIONS", "LENGTH (FT-IN)", "LB/EA", "TOTAL LBS", "FINISH",
                                                         "GRADE", "SOURCE / NOTES", "MARK", "RFI"]
    memo = _find(ws, "Detail Register total (see tab) — not added", col=1)
    assert _fill(memo) == "FFE699"
    assert ws.cell(row=memo.row, column=7).value == f"=IFERROR('Detail Register'!{anchors['Detail Register']},0)"
    gt = _find(ws, "GRAND TOTAL — MISC PARTS", col=1, startswith=True)
    assert anchors["Misc Parts"] == f"G{gt.row}" and gt.row > memo.row
    assert f"G{memo.row}" not in ws.cell(row=gt.row, column=7).value                    # memo is shown, not added
    assert "Base Plates".upper() in [str(ws.cell(row=r, column=1).value or "").upper().replace("▶", "").strip() for r in range(h, ws.max_row)]
    mm = wb["Misc Metals"]
    gtm = _find(mm, "GRAND TOTAL — MISC METALS", col=1, startswith=True)
    assert anchors["Misc Metals"] == f"G{gtm.row}"
    # Misc Metals is outside PROJECT TOTAL: its Summary line is below the total and not in the SUM
    s = wb["Summary"]
    proj = _find(s, "PROJECT TOTAL", col=1, startswith=True)
    assert "'Misc Metals'" not in "".join(str(s.cell(row=r, column=4).value) for r in range(proj.row - 6, proj.row + 1))


def test_detail_register_layout(built):
    t, path, anchors, keys = built
    ws = openpyxl.load_workbook(path)["Detail Register"]
    h = _header_row(ws, "DETAIL REF")
    heads = [c.value for c in ws[h] if c.value]
    assert heads[:11] == ["DETAIL REF", "CONDITION", "ITEM", "SIZE / SPEC", "UNIT BASIS", "LB PER UNIT", "QTY APPLIED", "UNIT", "TOTAL LBS", "QTY SOURCE", "NOTES"]
    assert heads[-1] == "RFI"
    col = _cols(ws, h)
    kit_rows = {}
    for r in range(h + 1, ws.max_row + 1):
        v = ws.cell(row=r, column=1).value
        if isinstance(v, str) and re.match(r"^[A-Z]\.  ", v):
            kit_rows[v[0]] = r
    assert list(kit_rows) == [k.letter for k in t.kits]
    # steel kits: yellow inputs, formula pattern, NOT YET APPLIED, subtotal
    subtotals = []
    for k in t.kits:
        r0 = kit_rows[k.letter]
        if k.no_steel:
            assert _fill(ws.cell(row=r0, column=1)) == "FFE699"
            for i in range(len(k.items)):
                r = r0 + 1 + i
                assert _fill(ws.cell(row=r, column=1)) == "FFE699"
                assert ws.cell(row=r, column=col["QTY APPLIED"]).value is None and ws.cell(row=r, column=col["TOTAL LBS"]).value is None
                assert _fill(ws.cell(row=r, column=col["QTY APPLIED"])) == "FFE699"
            continue
        assert _fill(ws.cell(row=r0, column=1)) not in ("FFE699", "FFF2CC")
        for i, it in enumerate(k.items):
            r = r0 + 1 + i
            q = ws.cell(row=r, column=col["QTY APPLIED"])
            assert _fill(q) == "FFF2CC"
            assert q.value == it.qty_applied
            assert ws.cell(row=r, column=col["TOTAL LBS"]).value == f'=IF(G{r}="","",F{r}*G{r})'
            if it.qty_applied is None:
                assert ws.cell(row=r, column=col["QTY SOURCE"]).value == "NOT YET APPLIED"
            else:
                assert ws.cell(row=r, column=col["QTY SOURCE"]).value != "NOT YET APPLIED"
        sub = r0 + 1 + len(k.items)
        assert ws.cell(row=sub, column=1).value.startswith("Subtotal")
        assert ws.cell(row=sub, column=9).value == f"=SUM(I{r0 + 1}:I{sub - 1})"
        subtotals.append(sub)
    gt = _find(ws, "GRAND TOTAL — DETAIL REGISTER", col=1)
    assert anchors["Detail Register"] == f"I{gt.row}"
    assert ws.cell(row=gt.row, column=9).value == "=SUM(" + ",".join(f"I{s}" for s in subtotals) + ")"
    how = _find(ws, "HOW TO USE THIS TAB", col=1)
    lines = [ws.cell(row=r, column=1).value for r in range(how.row + 1, ws.max_row + 1) if ws.cell(row=r, column=1).value]
    assert 4 <= len(lines) <= 6 and "yellow" in lines[0].lower()
    assert how.row > gt.row


def test_beam_detail_and_notes_tabs(built):
    t, path, anchors, keys = built
    wb = openpyxl.load_workbook(path)
    ws = wb["Beam Detail — by Member"]
    h = _header_row(ws, "SHEET")
    assert [c.value for c in ws[h] if c.value] == ["SHEET", "SIZE", "STUDS / TAG", "LENGTH (FT-IN)", "LB/FT", "LBS", "NOTE / FLAG", "PLAN X (pt)", "PLAN Y (pt)",
                                                   "RFI", "LENGTH (DEC FT)"]
    for i, b in enumerate(t.beams):
        r = h + 1 + i
        assert ws.cell(row=r, column=2).value == b.size and ws.cell(row=r, column=11).value == pytest.approx(b.length_ft)
        assert ws.cell(row=r, column=6).value == f'=IF(AND(ISNUMBER(E{r}),ISNUMBER(K{r})),E{r}*K{r},"")'
    tot = h + 1 + len(t.beams)
    assert ws.cell(row=tot, column=1).value == "TOTAL" and ws.cell(row=tot, column=6).value == f"=SUM(F{h + 1}:F{tot - 1})"
    chk = ws.cell(row=tot, column=7).value
    assert chk == f"""=IF(ROUND(F{tot}-'Beam Tonnage'!{anchors['Beam Tonnage']},0)=0,"✓ ties to Beam Tonnage","CHECK — does not tie")"""
    assert keys["Beam Detail check"] == f"G{tot}" and anchors["Beam Detail — by Member"] == f"F{tot}"
    sn = wb["S-Sheet Notes"]
    h = _header_row(sn, "SHEET")
    assert [c.value for c in sn[h] if c.value] == ["SHEET", "NOTE"]
    assert [sn.cell(row=h + 1 + i, column=2).value for i in range(len(t.notes))] == [n.text for n in t.notes]


def test_finish_summary_layout(built):
    t, path, anchors, keys = built
    ws = openpyxl.load_workbook(path)["Finish Summary"]
    h = _header_row(ws, "SCOPE / SOURCE")
    assert [c.value for c in ws[h] if c.value] == ["SCOPE / SOURCE", "PIECES", "LBS", "TONS", "FINISH", "BASIS"]
    texts = [str(ws.cell(row=r, column=1).value) for r in range(1, ws.max_row + 1)]
    for needle in ("ROLLUP BY FINISH", "SUBTOTAL — PRIMED", "SUBTOTAL — GALV", "TOTAL FABRICATED", "HELD OUT", "RECONCILIATION", "VARIANCE",
                   "PIECE COUNT", "GALVANIZED BUT UNQUANTIFIED"):
        assert any(x.startswith(needle) for x in texts), needle
    # SUMIF over each tab's FINISH and TOTAL LBS columns
    for r in range(1, ws.max_row + 1):
        lab = str(ws.cell(row=r, column=1).value)
        if lab.startswith(("Columns — ", "Beams — ", "Detail Register items", "Misc Parts (net")):
            f = ws.cell(row=r, column=3).value
            assert f.startswith("=SUMIF(") and "$E%d" % r in f, (r, f)
    assert ws.cell(row=int(keys["Finish Summary VARIANCE"][1:]), column=3).value.startswith("=ROUND(C")
    held = [r for r in range(1, ws.max_row + 1) if str(ws.cell(row=r, column=1).value).startswith(("Anchor rods", "Field bolts"))]
    assert len(held) == 2
    assert ws.cell(row=held[0], column=3).value == f"='Anchor Bolt Summary'!{anchors['Anchor Bolt Summary']}"
    assert ws.cell(row=held[1], column=3).value == f"='Field Bolts & Anchors'!{anchors['Field Bolts & Anchors']}"
    split = [r for r in range(1, ws.max_row + 1) if str(ws.cell(row=r, column=1).value).startswith("of which")]
    assert len(split) == 4 and all("SUMIF(" in ws.cell(row=r, column=3).value for r in split)
    sub = _find(ws, "SUBTOTAL — HELD OUT", col=1)
    assert ws.cell(row=sub.row, column=3).value == f"=C{held[0]}+C{held[1]}"
    r = [r for r in range(1, ws.max_row) if str(ws.cell(row=r, column=1).value).startswith("Summary tab PROJECT TOTAL")][0]
    assert ws.cell(row=r, column=3).value in (f"=Summary!{anchors['Summary']}", f"='Summary'!{anchors['Summary']}")
    gal = [ws.cell(row=r, column=1).value for r in range(1, ws.max_row + 1) if _fill(ws.cell(row=r, column=1)) == "DDEBF7"]
    assert gal == t.galv_unquantified


def test_model_geometry_tab_is_the_shared_function(built):
    t, path, anchors, keys = built
    ws = openpyxl.load_workbook(path)["Model Geometry"]
    mark = _find(ws, "MARK", col=1)
    heads = [c.value for c in ws[mark.row] if c.value]
    assert heads[:22] == ["MARK", "PIECE", "TYPE", "SIZE", "GRADE", "FINISH", "SHEET", "GRID", "LEVEL", "X1", "Y1", "Z1", "X2", "Y2", "Z2", "LENGTH", "ROT", "CP",
                          "LB/FT", "LBS", "RFI", "NOTES"]
    assert ws.max_row >= mark.row + len(t.geometry)
    assert ws[keys["Model Geometry pieces"]].value.startswith("=COUNTA(")
    assert ws[anchors["Model Geometry"]].value.startswith("=SUM(")


# ----------------------------------------------------------------------------- recalculated numbers
def test_recalc_zero_errors(recalced):
    q, out = recalced
    assert out["status"] == "success" and out["total_errors"] == 0 and out["total_formulas"] > 300


def test_recalc_totals_tie_to_the_model(built, recalced):
    t, path, anchors, keys = built
    q, out = recalced
    wb = openpyxl.load_workbook(q, data_only=True)
    tot = t.totals()
    s = wb["Summary"]
    assert s[anchors["Summary"]].value == pytest.approx(tot["project"], abs=0.5)
    assert s[keys["Summary PROJECT TOTAL tons"]].value == pytest.approx(tot["tons"], abs=0.001)
    per_tab = {"Column Tonnage": "columns", "Beam Tonnage": "beams", "Detail Register": "detail_register", "Misc Parts": "misc_parts",
               "Anchor Bolt Summary": "anchor_bolts", "Field Bolts & Anchors": "field_bolts", "Misc Metals": "misc_metals"}
    for tab, key in per_tab.items():
        assert wb[tab][anchors[tab]].value == pytest.approx(tot[key], abs=0.5), tab
    assert wb["Beam Detail — by Member"][anchors["Beam Detail — by Member"]].value == pytest.approx(tot["beams"], abs=0.5)
    assert s[keys["Summary Misc Metals lbs"]].value == pytest.approx(tot["misc_metals"], abs=0.5)
    # memo lines (joists + deck) = takeoff.memo total, not in PROJECT TOTAL
    j = _find(s, "Open-web joists", col=1, startswith=True); d = _find(s, "Roof deck", col=1, startswith=True)
    assert s.cell(row=j.row, column=4).value + s.cell(row=d.row, column=4).value == pytest.approx(tot["memo"], abs=0.5)
    # project total is the sum of the six lines only
    assert tot["project"] == pytest.approx(sum(tot[k] for k in ("columns", "beams", "detail_register", "misc_parts", "anchor_bolts", "field_bolts")))
    # Detail Register total = sum of kit weights; Misc Parts memo row shows it but the Misc Parts total stays net
    mp = wb["Misc Parts"]
    memo = _find(mp, "Detail Register total (see tab) — not added", col=1)
    assert mp.cell(row=memo.row, column=7).value == pytest.approx(tot["detail_register"], abs=0.5)
    assert mp[anchors["Misc Parts"]].value == pytest.approx(tot["misc_parts"], abs=0.5)
    # revision log picks up the live total for the current revision
    rv = _find(s, "REV 0", col=1)
    assert s.cell(row=rv.row, column=4).value == pytest.approx(tot["project"], abs=0.5)


def test_recalc_finish_summary_reconciles(built, recalced):
    t, path, anchors, keys = built
    q, out = recalced
    ws = openpyxl.load_workbook(q, data_only=True)["Finish Summary"]
    assert abs(ws[keys["Finish Summary VARIANCE"]].value) < 0.01
    assert ws[anchors["Finish Summary"]].value == 0
    ft = t.finish_totals()
    prim = _find(ws, "SUBTOTAL — PRIMED", col=1); galv = _find(ws, "SUBTOTAL — GALV", col=1); held = _find(ws, "SUBTOTAL — HELD OUT", col=1)
    assert ws.cell(row=prim.row, column=3).value == pytest.approx(ft["Primed"], abs=0.5)
    assert ws.cell(row=galv.row, column=3).value == pytest.approx(ft["Galv"], abs=0.5)
    assert ws[keys["Finish Summary TOTAL FABRICATED"]].value == pytest.approx(ft["fabricated"], abs=0.5)
    assert ws.cell(row=held.row, column=3).value == pytest.approx(ft["held_out"], abs=0.5)
    assert "VARIANCE 0" in ws.cell(row=int(keys["Finish Summary VARIANCE"][1:]), column=6).value
    # piece-count deltas are all zero
    first = int(keys["Finish Summary piece count first row"][1:])
    assert [ws.cell(row=first + i, column=4).value for i in range(3)] == [0, 0, 0]
    assert [ws.cell(row=first + i, column=2).value for i in range(2)] == [t.totals()["pieces"]["columns"], t.totals()["pieces"]["beams"]]


def test_recalc_beam_detail_ties_to_beam_tonnage(built, recalced):
    t, path, anchors, keys = built
    q, out = recalced
    wb = openpyxl.load_workbook(q, data_only=True)
    assert "✓" in wb["Beam Detail — by Member"][keys["Beam Detail check"]].value
    bt = wb["Beam Tonnage"]
    assert any("✓" in str(c.value) for row in bt.iter_rows() for c in row if isinstance(c.value, str))
    assert not [c.coordinate for ws in wb for row in ws.iter_rows() for c in row if isinstance(c.value, str) and c.value.startswith("CHECK —")]
    # the rollup lengths still display as the beam's own length to 1/8"
    h = _header_row(bt, "SIZE")
    lens = {bt.cell(row=r, column=1).value: bt.cell(row=r, column=5).value for r in range(h + 1, h + 12) if bt.cell(row=r, column=3).value}
    assert lens["W12x26"] == "25'-0\"" and lens["W16x31"] == "30'-0 1/2\""


def test_recalc_model_geometry_total(built, recalced):
    t, path, anchors, keys = built
    q, out = recalced
    ws = openpyxl.load_workbook(q, data_only=True)["Model Geometry"]
    assert ws[keys["Model Geometry pieces"]].value == f"{len(t.geometry)} pcs"
    total = ws[anchors["Model Geometry"]].value
    assert total and total > 0
    expect = 0.0
    for g in t.geometry:
        if g.TYPE.upper() == "PLATE":
            expect += 0.75 * 12 * 12 * 0.2836                       # PL 3/4x12x12, 0.2836 lb/in^3
        else:
            expect += g.LB_FT * math.sqrt((g.X2 - g.X1) ** 2 + (g.Y2 - g.Y1) ** 2 + (g.Z2 - g.Z1) ** 2)
    assert total == pytest.approx(expect, abs=1.0)


def test_recalc_every_visible_length_is_ft_in(built, recalced):
    t, path, anchors, keys = built
    q, out = recalced
    wb = openpyxl.load_workbook(q, data_only=True)
    raw = openpyxl.load_workbook(path)                      # column visibility from the file as written
    n = 0
    for ws in wb:
        hidden = _hidden(raw[ws.title])
        for c in [c for row in raw[ws.title].iter_rows() for c in row if c.value and _fill(c) == "2E75B6"]:
            txt = str(c.value)
            if c.column in hidden or "DEC FT" in txt or not any(k in txt for k in ("HEIGHT", "LENGTH", "TOTAL LF")):
                continue
            for r in range(c.row + 1, ws.max_row + 1):
                if _fill(raw[ws.title].cell(row=r, column=c.column)) == "2E75B6":      # next table's header in the same column
                    break
                v = ws.cell(row=r, column=c.column).value
                if v in (None, "") or (isinstance(v, str) and v.endswith(" pcs")):       # blanks, Model Geometry piece-count cell
                    continue
                n += 1
                assert isinstance(v, str) and FTIN.match(v), (ws.title, ws.cell(row=r, column=c.column).coordinate, v)
    assert n >= 40
    # Model Geometry visible coordinates are ft-in too
    mg = wb["Model Geometry"]
    mark = _find(mg, "MARK", col=1)
    for hdr in ("X1", "Y1", "Z1", "X2", "Y2", "Z2"):
        col = [c.column for c in mg[mark.row] if c.value == hdr][0]
        for r in range(mark.row + 1, mark.row + 1 + len(t.geometry)):
            v = mg.cell(row=r, column=col).value
            assert v in (None, "") or FTIN.match(v), (hdr, r, v)


# ----------------------------------------------------------------------------- robustness
def test_json_fixture_builds_same_totals(tmp_path):
    t = Takeoff.from_json(os.path.join(DATA, "sample_takeoff.json"))
    assert t.totals()["project"] == pytest.approx(sample_takeoff().totals()["project"], abs=0.5)
    p = build_workbook(t, str(tmp_path / "from_json.xlsx"))
    assert openpyxl.load_workbook(p).sheetnames == TABS


def test_empty_takeoff_builds_and_recalcs(tmp_path):
    t = Takeoff()
    t.header.job = "Empty Job"
    p = build_workbook(t, str(tmp_path / "empty.xlsx"))
    assert openpyxl.load_workbook(p).sheetnames == TABS
    if os.path.exists(RECALC):
        out = _recalc(p)
        ws = openpyxl.load_workbook(p, data_only=True)
        assert ws["Summary"][W.ANCHORS["Summary"]].value == 0
        assert ws["Finish Summary"][W.ANCHORS["Finish Summary"]].value == 0


def test_finish_vocabulary_is_normalised(tmp_path):
    """free-text finishes from the extraction map to Primed / Galv (steel) and Plain / Galv (hardware) so the SUMIF rollups still reconcile"""
    t = sample_takeoff()
    t.columns[0].finish = "Galvanized"
    t.beams[0].finish = "HDG"
    t.anchors[1].finish = "hot-dip galvanized"
    t.bolts[0].finish = "Black"
    p = build_workbook(t, str(tmp_path / "fin.xlsx"))
    wb = openpyxl.load_workbook(p)
    ws = wb["Column Tonnage"]
    h = _header_row(ws, "MARK / LOCATION"); col = _cols(ws, h)
    assert ws.cell(row=h + 2, column=col["FINISH"]).value == "Galv"
    ws = wb["Field Bolts & Anchors"]
    h = _header_row(ws, "CONNECTION TYPE"); col = _cols(ws, h)
    assert ws.cell(row=h + 2, column=col["FINISH"]).value == "Plain"
    if os.path.exists(RECALC):
        _recalc(p)
        fs = openpyxl.load_workbook(p, data_only=True)["Finish Summary"]
        assert fs[W.ANCHORS["Finish Summary"]].value == 0
