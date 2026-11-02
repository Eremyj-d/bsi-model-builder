"""
Synthetic structural drawing set for the pdfset tests — "SAMPLE SHELL BUILDING", four sheets on 36x24 in
landscape (2592 x 1728 pt) at 1/8" = 1'-0" (9.0 pt/ft), drawn with reportlab so every number is known:

    S001  General Notes
    S101  Foundation Plan & Column Schedule   grid 1-2-3 @ 25'-0", A-B @ 30'-0", 6 columns (filled 8-pt squares)
    S102  Roof Framing Plan                   4 x W12x26 @ 25', 3 x W16x31 @ 30' (vertical, rotated labels),
                                             7 x W12x19 @ 30' infill (3 @ 6'-3" in bay 1-2, 4 @ 5'-0" in bay 2-3)
    S501  Typical Details                     three labelled detail boxes with plate / anchor-rod callouts

`make_set(out_dir)` writes SAMPLE_Structural.pdf (4 pages), the same pages as SAMPLE_S001.pdf … SAMPLE_S501.pdf,
and SAMPLE_Structural_rot90.pdf (the 4-page file with /Rotate 90 set on every page through PyMuPDF, since
reportlab cannot set /Rotate) and returns the paths in that order.

Reportlab's origin is bottom-left (y up); PyMuPDF's displayed frame is top-left (y down): pdf_y = 1728 - rl_y.
Grid A sits BELOW grid B on the page so that +Y north = up the page gives A = 0 ft, B = 30 ft.
"""
from __future__ import annotations

import os

from reportlab.pdfgen import canvas

PAGE_W, PAGE_H = 2592.0, 1728.0          # 36 x 24 in
PT_PER_FT = 9.0                          # 1/8" = 1'-0"

# plan geometry (reportlab coordinates, y up)
X0 = 500.0                                # grid 1
GRID_X = {"1": X0, "2": X0 + 25 * PT_PER_FT, "3": X0 + 50 * PT_PER_FT}       # 500, 725, 950
Y_A = 600.0                               # grid A (lower on the page)
GRID_Y = {"A": Y_A, "B": Y_A + 30 * PT_PER_FT}                               # 600, 870
BUBBLE_R = 12.0
BUBBLE_ROW_Y = GRID_Y["B"] + 180.0        # 1-2-3 bubbles across the top of the plan
BUBBLE_COL_X = X0 - 150.0                 # A-B bubbles down the left
DIM_ROW_Y = BUBBLE_ROW_Y - 60.0           # horizontal dimension string row
DIM_COL_X = BUBBLE_COL_X + 70.0           # vertical dimension string column
COLUMN_SQ = 8.0                           # filled column symbol size, pt
BEAM_W = 1.2                              # thick structural line width
GRID_W = 0.3                              # thin grid line width

SHEETS = [
    ("S001", "General Notes"),
    ("S101", "Foundation Plan & Column Schedule"),
    ("S102", "Roof Framing Plan"),
    ("S501", "Typical Details"),
]
DATE = "11/01/2026"
PROJECT = "SAMPLE SHELL BUILDING"


# ------------------------------------------------------------------------------------------------ helpers
def _text(c: canvas.Canvas, x: float, y: float, s: str, size: float = 8.0, bold: bool = False,
          angle: float = 0.0, centred: bool = False):
    """Draw a single-span string; `angle` rotates about (x, y) (90 = reading upward)."""
    c.saveState()
    c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    c.translate(x, y)
    if angle:
        c.rotate(angle)
    if centred:
        c.drawCentredString(0, 0, s)
    else:
        c.drawString(0, 0, s)
    c.restoreState()


def _line(c: canvas.Canvas, x1, y1, x2, y2, width: float, dash=None):
    c.saveState()
    c.setLineWidth(width)
    if dash:
        c.setDash(*dash)
    c.line(x1, y1, x2, y2)
    c.restoreState()


def _frame_and_title_block(c: canvas.Canvas, number: str, title: str):
    # sheet border (thin so it is not a "structural" line)
    c.saveState(); c.setLineWidth(0.5); c.rect(30, 30, PAGE_W - 60, PAGE_H - 60, stroke=1, fill=0); c.restoreState()
    # title block in the lower right: outer box 1.0 pt (a thick non-member line on every sheet)
    bx, by, bw, bh = PAGE_W - 440, 40, 400, 270
    c.saveState(); c.setLineWidth(1.0); c.rect(bx, by, bw, bh, stroke=1, fill=0); c.restoreState()
    for yy in (by + 60, by + 130, by + 200):
        _line(c, bx, yy, bx + bw, yy, 0.5)
    # project cell (top)
    _text(c, bx + 15, by + 245, PROJECT, 14, bold=True)
    _text(c, bx + 15, by + 225, "100 Example Rd, Lynchburg, VA", 9)
    _text(c, bx + 15, by + 208, "Sample Structural Engineers (SER)", 9)
    # date / scale cell
    _text(c, bx + 15, by + 180, f"DATE: {DATE}", 9)
    _text(c, bx + 15, by + 162, "SCALE: AS NOTED", 9)
    _text(c, bx + 15, by + 144, "DRAWN: JD    CHECKED: SER", 9)
    # title cell
    _text(c, bx + 15, by + 100, title, 12, bold=True)
    _text(c, bx + 15, by + 78, "REV 0 - PERMIT SET", 8)
    # number cell (bottom)
    _text(c, bx + 15, by + 45, "SHEET", 8)
    _text(c, bx + 15, by + 12, number, 36, bold=True)


def _grid(c: canvas.Canvas, with_columns: bool, column_labels: bool):
    """Bubbles 1-2-3 across the top, A-B down the left, dimension strings, thin grid lines, column squares."""
    x_tags = sorted(GRID_X.items(), key=lambda kv: kv[1])
    y_tags = sorted(GRID_Y.items(), key=lambda kv: kv[1])
    # thin grid lines through the bubbles
    for tag, x in x_tags:
        _line(c, x, BUBBLE_ROW_Y - BUBBLE_R, x, Y_A - 120, GRID_W)
    for tag, y in y_tags:
        _line(c, BUBBLE_COL_X + BUBBLE_R, y, GRID_X["3"] + 120, y, GRID_W)
    # bubbles (stroked circles, 4 beziers) with centred tags
    c.saveState(); c.setLineWidth(0.6)
    for tag, x in x_tags:
        c.circle(x, BUBBLE_ROW_Y, BUBBLE_R, stroke=1, fill=0)
        _text(c, x, BUBBLE_ROW_Y - 3.5, tag, 10, centred=True)
    for tag, y in y_tags:
        c.circle(BUBBLE_COL_X, y, BUBBLE_R, stroke=1, fill=0)
        _text(c, BUBBLE_COL_X, y - 3.5, tag, 10, centred=True)
    c.restoreState()
    # horizontal dimension row between the 1-2-3 bubbles
    _line(c, GRID_X["1"], DIM_ROW_Y, GRID_X["3"], DIM_ROW_Y, GRID_W)
    for (ta, xa), (tb, xb) in zip(x_tags, x_tags[1:]):
        for x in (xa, xb):
            _line(c, x - 4, DIM_ROW_Y - 4, x + 4, DIM_ROW_Y + 4, GRID_W)
        _text(c, (xa + xb) / 2, DIM_ROW_Y + 4, "25'-0\"", 8, centred=True)
    # vertical dimension column between the A-B bubbles (rotated 90°, reading upward)
    _line(c, DIM_COL_X, GRID_Y["A"], DIM_COL_X, GRID_Y["B"], GRID_W)
    for y in (GRID_Y["A"], GRID_Y["B"]):
        _line(c, DIM_COL_X - 4, y - 4, DIM_COL_X + 4, y + 4, GRID_W)
    _text(c, DIM_COL_X - 4, (GRID_Y["A"] + GRID_Y["B"]) / 2, "30'-0\"", 8, angle=90, centred=True)
    # perimeter CMU wall: double thin lines 1'-0" outside the grid (keeps the plans above 50 vector paths, like a
    # real sheet, and gives the matcher thin parallel lines near the beams that it must ignore)
    off, cmu = 1.0 * PT_PER_FT, 8.0 / 12.0 * PT_PER_FT
    wx0, wx1 = GRID_X["1"] - off, GRID_X["3"] + off
    wy0, wy1 = GRID_Y["A"] - off, GRID_Y["B"] + off
    for d in (0.0, cmu):
        _line(c, wx0 - d, wy0 - d, wx1 + d, wy0 - d, 0.5)
        _line(c, wx0 - d, wy1 + d, wx1 + d, wy1 + d, 0.5)
        _line(c, wx0 - d, wy0 - d, wx0 - d, wy1 + d, 0.5)
        _line(c, wx1 + d, wy0 - d, wx1 + d, wy1 + d, 0.5)
    # north arrow (circle + arrow + N) off to the right of the plan
    nx, ny = GRID_X["3"] + 260.0, GRID_Y["B"] + 120.0
    c.saveState(); c.setLineWidth(0.6); c.circle(nx, ny, 24, stroke=1, fill=0); c.restoreState()
    _line(c, nx, ny - 18, nx, ny + 14, 0.8)
    _line(c, nx - 6, ny + 6, nx, ny + 14, 0.8)
    _line(c, nx + 6, ny + 6, nx, ny + 14, 0.8)
    _text(c, nx, ny + 30, "N", 9, bold=True, centred=True)
    # columns: filled 8-pt squares at the six intersections
    if with_columns:
        c.saveState(); c.setFillGray(0)
        for xt, x in x_tags:
            for yt, y in y_tags:
                c.rect(x - COLUMN_SQ / 2, y - COLUMN_SQ / 2, COLUMN_SQ, COLUMN_SQ, stroke=0, fill=1)
                if column_labels:
                    _text(c, x + 7, y + 7, "C1" if yt == "A" else "C2", 7)
        c.restoreState()


# ------------------------------------------------------------------------------------------------ sheets
def draw_S001(c: canvas.Canvas):
    _frame_and_title_block(c, "S001", "General Notes")
    _text(c, 120, PAGE_H - 120, "GENERAL STRUCTURAL NOTES", 16, bold=True)
    notes = [
        "1. DESIGN CODES: VIRGINIA USBC 2021 / IBC 2021, ASCE 7-16, AISC 360-16, AISC 303-16.",
        "2. STRUCTURAL STEEL: W-SHAPES ASTM A992 (FY = 50 KSI). HSS ASTM A500 GR. C (FY = 50 KSI).",
        "   PLATES, BARS AND ANGLES ASTM A572 GR. 50. CHANNELS ASTM A36. PIPE ASTM A53 GR. B.",
        "3. ANCHOR RODS: ASTM F1554 GR. 55 WELDABLE, HOT-DIP GALVANIZED, WITH HEAVY HEX NUTS AND PLATE WASHERS.",
        "4. BOLTS: ASTM F3125 GR. A325-N, 3/4\" DIA U.N.O., BEARING TYPE, SNUG TIGHT. TWIST-OFF TYPE PERMITTED.",
        "5. WELDING: AWS D1.1, E70XX ELECTRODES. SHOP WELDS PER AISC; FIELD WELDS AS SHOWN.",
        "6. FINISH: ALL INTERIOR STEEL SHOP PRIMED SSPC-SP2 ONE COAT. EXTERIOR AND EXPOSED STEEL HOT-DIP",
        "   GALVANIZED PER ASTM A123 / A153. TOUCH UP FIELD WELDS AND ABRASIONS WITH ZINC-RICH PAINT.",
        "7. FABRICATOR: AISC CERTIFIED (BU). SUBMIT SHOP DRAWINGS FOR REVIEW PRIOR TO FABRICATION.",
        "8. TOP OF STEEL ELEVATIONS ARE NOTED ON THE FRAMING PLANS. COORDINATE WITH ARCHITECTURAL.",
        "9. CONNECTIONS: SINGLE PLATE SHEAR TABS U.N.O.; DESIGN FOR 50% OF THE UNIFORM LOAD CAPACITY OF THE BEAM.",
        "10. DECK: 1 1/2\" x 22 GA TYPE B GALVANIZED ROOF DECK, 3-SPAN CONDITION, BY OTHERS.",
    ]
    y = PAGE_H - 170
    for n in notes:
        _text(c, 120, y, n, 11)
        y -= 26


def draw_S101(c: canvas.Canvas):
    _frame_and_title_block(c, "S101", "Foundation Plan & Column Schedule")
    _grid(c, with_columns=True, column_labels=True)
    # footings: dashed thin squares around each column
    c.saveState(); c.setLineWidth(0.5); c.setDash(6, 3)
    for x in GRID_X.values():
        for y in GRID_Y.values():
            c.rect(x - 27, y - 27, 54, 54, stroke=1, fill=0)
    c.restoreState()
    _text(c, (GRID_X["1"] + GRID_X["3"]) / 2, Y_A - 160, "FOUNDATION PLAN", 14, bold=True, centred=True)
    _text(c, (GRID_X["1"] + GRID_X["3"]) / 2, Y_A - 180, "SCALE: 1/8\" = 1'-0\"", 9, centred=True)
    # column schedule (text table, thin 0.5 rules)
    tx, ty = 1400.0, 1000.0
    cols = [0, 90, 260, 520, 660, 800]
    _text(c, tx, ty + 30, "COLUMN SCHEDULE", 12, bold=True)
    rows = [("MARK", "SIZE", "BASE PLATE", "T/FTG", "T/STL"),
            ("C1", "HSS6x6x3/8", "PL 3/4 x 12 x 1'-0\"", "-2'-0\"", "14'-0\""),
            ("C2", "HSS6x6x1/2", "PL 1 x 14 x 1'-2\"", "-2'-0\"", "15'-6\"")]
    for ri, row in enumerate(rows):
        yy = ty - ri * 24
        for ci, cell in enumerate(row):
            _text(c, tx + cols[ci] + 6, yy - 16, cell, 9, bold=(ri == 0))
        _line(c, tx, yy, tx + cols[-1], yy, 0.5)
    _line(c, tx, ty - len(rows) * 24, tx + cols[-1], ty - len(rows) * 24, 0.5)
    for cx in cols:
        _line(c, tx + cx, ty, tx + cx, ty - len(rows) * 24, 0.5)
    _text(c, tx, ty - 100, "NOTES: (4) 3/4\" DIA F1554 GR.55 ANCHOR RODS PER COLUMN, SEE 1/S501.", 9)


def draw_S102(c: canvas.Canvas):
    _frame_and_title_block(c, "S102", "Roof Framing Plan")
    _grid(c, with_columns=True, column_labels=False)
    x1, x2, x3 = GRID_X["1"], GRID_X["2"], GRID_X["3"]
    ya, yb = GRID_Y["A"], GRID_Y["B"]
    # W12x26 along A and B, one segment per bay, labels parallel just above the line
    for y in (ya, yb):
        for xa, xb in ((x1, x2), (x2, x3)):
            _line(c, xa, y, xb, y, BEAM_W)
            _text(c, (xa + xb) / 2, y + 4, "W12x26", 7, centred=True)
    # W16x31 along 1, 2, 3 between A and B, drawn vertical, label rotated 90° (reading upward) left of the line
    for x in (x1, x2, x3):
        _line(c, x, ya, x, yb, BEAM_W)
        _text(c, x - 4, (ya + yb) / 2, "W16x31", 7, angle=90, centred=True)
    # infill W12x19: 3 @ 6'-3" in bay 1-2, 4 @ 5'-0" in bay 2-3 (7 total)
    infill = [x1 + 6.25 * PT_PER_FT * i for i in (1, 2, 3)] + [x2 + 5.0 * PT_PER_FT * i for i in (1, 2, 3, 4)]
    for x in infill:
        _line(c, x, ya, x, yb, BEAM_W)
        _text(c, x - 3, (ya + yb) / 2, "W12x19", 6, angle=90, centred=True)
    _text(c, x3 + 160, (ya + yb) / 2 + 40, "T/STL 14'-0\" at A, 15'-6\" at B", 9)
    _text(c, x3 + 160, (ya + yb) / 2 + 20, "ROOF DECK 1 1/2\" x 22 GA TYPE B, BY OTHERS", 9)
    _text(c, (x1 + x3) / 2, ya - 160, "ROOF FRAMING PLAN", 14, bold=True, centred=True)
    _text(c, (x1 + x3) / 2, ya - 180, "SCALE: 1/8\" = 1'-0\"", 9, centred=True)


def draw_S501(c: canvas.Canvas):
    _frame_and_title_block(c, "S501", "Typical Details")
    boxes = [
        (200, "1", "BASE PLATE DETAIL", ["HSS6x6x3/8 COLUMN", "PL 3/4 x 12 x 1'-0\"",
                                         "(4) 3/4\" DIA F1554 GR.55 ANCHOR RODS", "1\" NON-SHRINK GROUT"]),
        (1000, "2", "CAP PLATE", ["CAP PL 1/2 x 8 x 0'-8\"", "(2) 3/4\" DIA A325-N BOLTS", "W12x26 BEAM OVER"]),
        (1800, "3", "SHEAR TAB", ["PL 3/8 x 4 x 0'-9\" SHEAR TAB", "(2) 3/4\" DIA A325-N BOLTS", "3/16 FILLET WELD BOTH SIDES"]),
    ]
    for bx, num, title, callouts in boxes:
        by, bw, bh = 900, 600, 500
        c.saveState(); c.setLineWidth(0.75); c.rect(bx, by, bw, bh, stroke=1, fill=0); c.restoreState()
        # a simple sketch: column stick, plate outline, anchor-rod ticks (all thin)
        _line(c, bx + 300, by + 150, bx + 300, by + 420, 0.75)
        c.saveState(); c.setLineWidth(0.75); c.rect(bx + 200, by + 140, 200, 12, stroke=1, fill=0); c.restoreState()
        for dx in (-70, 70):
            _line(c, bx + 300 + dx, by + 60, bx + 300 + dx, by + 150, 0.75, dash=(4, 2))
        for i, s in enumerate(callouts):
            _text(c, bx + 20, by + bh - 40 - i * 18, s, 9)
        c.saveState(); c.setLineWidth(0.6); c.circle(bx + 30, by - 30, 14, stroke=1, fill=0); c.restoreState()
        _text(c, bx + 30, by - 34, num, 11, bold=True, centred=True)
        _text(c, bx + 55, by - 34, title, 11, bold=True)
        _text(c, bx + 55, by - 50, "SCALE: 1\" = 1'-0\"", 8)


DRAWERS = {"S001": draw_S001, "S101": draw_S101, "S102": draw_S102, "S501": draw_S501}


# ------------------------------------------------------------------------------------------------ entry point
def make_set(out_dir: str) -> list[str]:
    """Write the synthetic set into `out_dir`; returns
    [SAMPLE_Structural.pdf, SAMPLE_S001.pdf, SAMPLE_S101.pdf, SAMPLE_S102.pdf, SAMPLE_S501.pdf, SAMPLE_Structural_rot90.pdf]."""
    os.makedirs(out_dir, exist_ok=True)
    combined = os.path.join(out_dir, "SAMPLE_Structural.pdf")
    c = canvas.Canvas(combined, pagesize=(PAGE_W, PAGE_H))
    c.setTitle("SAMPLE SHELL BUILDING - Structural")
    for number, _title in SHEETS:
        DRAWERS[number](c)
        c.showPage()
    c.save()
    paths = [combined]
    for number, _title in SHEETS:
        p = os.path.join(out_dir, f"SAMPLE_{number}.pdf")
        cc = canvas.Canvas(p, pagesize=(PAGE_W, PAGE_H))
        DRAWERS[number](cc)
        cc.showPage()
        cc.save()
        paths.append(p)
    # /Rotate 90 copy of the 4-page file through PyMuPDF (reportlab cannot set the page rotation)
    import pymupdf
    rot = os.path.join(out_dir, "SAMPLE_Structural_rot90.pdf")
    doc = pymupdf.open(combined)
    for page in doc:
        page.set_rotation(90)
    doc.save(rot)
    doc.close()
    paths.append(rot)
    return paths


if __name__ == "__main__":      # pragma: no cover
    import sys
    for p in make_set(sys.argv[1] if len(sys.argv) > 1 else "out_synth"):
        print(p)
