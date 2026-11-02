"""
geometry_tab.py — the "Model Geometry" tab for Bohling takeoff workbooks (BSI house style).

    from geometry_tab import add_model_geometry_tab, read_model_geometry_tab
    add_model_geometry_tab(wb, job, rows)        # rows = list of dicts in the Model Geometry CSV column set
    rows = read_model_geometry_tab("Job_Takeoff.xlsx")   # back to CSV rows (hidden decimal columns drive it)

Visible cells show coordinates and lengths in FEET-INCHES; hidden decimal-feet helper columns carry the
numbers (same convention as the other tabs). LENGTH and LBS are formulas off the helpers.
"""
from __future__ import annotations
import math
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

NAVY, BLUE, LIGHT, LIGHT2, YELLOW, GOLD = "1F3864", "2E75B6", "EAF1F8", "DEEAF1", "FFF2CC", "FFE699"
TITLE = Font(name="Arial", bold=True, color="FFFFFF", size=12)
HDR = Font(name="Arial", bold=True, color="FFFFFF", size=9)
TXT = Font(name="Arial", size=9)
BOLD = Font(name="Arial", size=9, bold=True)
NOTE = Font(name="Arial", size=8, italic=True, color="404040")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

VISIBLE = ["MARK", "PIECE", "TYPE", "SIZE", "GRADE", "FINISH", "SHEET", "GRID", "LEVEL",
           "X1", "Y1", "Z1", "X2", "Y2", "Z2", "LENGTH", "ROT", "CP", "LB/FT", "LBS", "RFI", "NOTES"]
HELPERS = ["X1_ft", "Y1_ft", "Z1_ft", "X2_ft", "Y2_ft", "Z2_ft", "LEN_ft"]
WIDTHS = {"MARK": 8, "PIECE": 6, "TYPE": 9, "SIZE": 16, "GRADE": 11, "FINISH": 8, "SHEET": 8, "GRID": 12, "LEVEL": 24,
          "X1": 11, "Y1": 11, "Z1": 11, "X2": 11, "Y2": 11, "Z2": 11, "LENGTH": 12, "ROT": 6, "CP": 5, "LB/FT": 8,
          "LBS": 9, "RFI": 8, "NOTES": 40}


def ftin_formula(ref: str) -> str:
    """Excel formula turning a decimal-feet cell into 13'-6 5/8\" (nearest 1/8\" — stations are dimensioned to 1/8\"),
    blank when the cell is blank. Carries into the next foot when the inches round to 12."""
    a = f"ABS({ref})"
    e = f"ROUND({a}*96,0)"            # eighths of an inch, rounded
    return (f'=IF({ref}="","",IF({ref}<0,"-","")&INT({e}/96)&"\'-"&INT(MOD({e},96)/8)'
            f'&CHOOSE(MOD({e},8)+1,""," 1/8"," 1/4"," 3/8"," 1/2"," 5/8"," 3/4"," 7/8")&"""")')


FRAC8 = {0: "", 1: " 1/8", 2: " 1/4", 3: " 3/8", 4: " 1/2", 5: " 5/8", 6: " 3/4", 7: " 7/8"}


def ft_in(x) -> str:
    """decimal feet -> 13'-6 5/8\" (nearest 1/8\")"""
    if x is None or x == "":
        return ""
    x = float(x); neg = x < 0; x = abs(x)
    q = int(round(x * 96)); ft, rem = divmod(q, 96); inch, eighth = divmod(rem, 8)
    return ("-" if neg else "") + f"{ft}'-{inch}{FRAC8[eighth]}\""


def _f(v):
    try:
        return None if v in (None, "") else float(v)
    except Exception:
        return None


def add_model_geometry_tab(wb, job: dict, rows: list[dict], status: str = "IN PROGRESS", title: str = "Model Geometry"):
    ws = wb.create_sheet(title)
    ws.sheet_view.showGridLines = False
    ncol = len(VISIBLE) + len(HELPERS)

    def put(r, c, v, font=TXT, fill=None, align=None, border=True, fmt=None):
        cell = ws.cell(row=r, column=c, value=v)
        cell.font = font
        if fill:
            cell.fill = PatternFill("solid", fgColor=fill)
        if align:
            cell.alignment = align
        if border:
            cell.border = BORDER
        if fmt:
            cell.number_format = fmt
        return cell

    # --- header block
    bld = f" | {job['building']}" if job.get("building") else ""
    put(1, 1, f"{job['job'].upper()}{bld} | MODEL GEOMETRY | {status}", TITLE, NAVY, border=False)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(VISIBLE))
    for c in range(1, len(VISIBLE) + 1):
        ws.cell(row=1, column=c).fill = PatternFill("solid", fgColor=NAVY)
    lines = [
        "One row per PIECE. This tab is the source for <Job>_Model.ifc (IFC2x3 Coordination View 2.0, mm/kg in the file) — "
        "the 3D model that goes to Tekla PowerFab Estimating / Advance Bill (IFC import, PRELIM_MARK → Reference #) and to the detailer as the reference model.",
        "DATUM: " + job.get("datum", {}).get("description", "Origin = first numbered grid / first lettered grid at T/SLAB 0'-0\"; +X along numbered grids, +Y along lettered grids, +Z up."),
        "COLUMNS: X1 Y1 Z1 = base plate centre at the base elevation, X2 Y2 Z2 = same X/Y at T/STL; CP 5 (centre); ROT 0 = flanges parallel to +X (web along Y), degrees CCW in plan.",
        "BEAMS / MEMBERS: X1→X2 = work line at TOP OF STEEL end to end (grid to grid or as measured); CP 8 = top centre (top flange at Z); ROT 0 = web vertical, right-hand rule end 1 → end 2.",
        "PLATES: X1 Y1 Z1 = centre of the plate's bottom face, SIZE = PL t x W x L, extruded +Z by t. Visible coordinates are ft-in; hidden decimal-feet columns to the right drive LENGTH and LBS.",
    ]
    gx = job.get("grids", {}).get("X", {}); gy = job.get("grids", {}).get("Y", {})
    if gx or gy:
        lines.append("GRIDS: X — " + ", ".join(f"{k}={ft_in(v)}" for k, v in sorted(gx.items(), key=lambda kv: float(kv[1]))) +
                     "   |   Y — " + ", ".join(f"{k}={ft_in(v)}" for k, v in sorted(gy.items(), key=lambda kv: float(kv[1]))))
    r = 2
    for ln in lines:
        put(r, 1, ln, NOTE, border=False)
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=len(VISIBLE))
        ws.cell(row=r, column=1).alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[r].height = 24
        r += 1
    r += 1
    hdr_row = r
    for c, h in enumerate(VISIBLE + HELPERS, start=1):
        put(r, c, h, HDR, BLUE, Alignment(horizontal="center", vertical="center", wrap_text=True))
    ws.row_dimensions[r].height = 28
    r += 1
    first = r
    col = {h: i + 1 for i, h in enumerate(VISIBLE + HELPERS)}
    L = lambda h: get_column_letter(col[h])

    for i, row in enumerate(rows):
        fill = LIGHT if i % 2 == 0 else None
        is_plate = str(row.get("TYPE", "")).strip().upper() in ("PLATE", "BASEPLATE", "BP", "EMBED", "CAP")
        for h in ("MARK", "PIECE", "TYPE", "SIZE", "GRADE", "FINISH", "SHEET", "GRID", "LEVEL", "NOTES"):
            put(r, col[h], row.get(h, "") or "", TXT, fill)
        rfi = (row.get("RFI") or "").strip()
        put(r, col["RFI"], rfi, BOLD if rfi else TXT, YELLOW if rfi else fill)
        # helpers (decimal feet)
        for h, src in zip(HELPERS[:6], ["X1", "Y1", "Z1", "X2", "Y2", "Z2"]):
            v = _f(row.get(src))
            put(r, col[h], v, TXT, fill, fmt="0.0000")
        # visible ft-in as formulas off the helpers
        for h, hp in zip(["X1", "Y1", "Z1", "X2", "Y2", "Z2"], HELPERS[:6]):
            put(r, col[h], ftin_formula(f"{L(hp)}{r}"), TXT, fill, Alignment(horizontal="right"))
        if is_plate:
            put(r, col["LEN_ft"], None, TXT, fill)
            put(r, col["LENGTH"], "", TXT, fill)
            put(r, col["LB/FT"], None, TXT, fill)
            lbs = _f(row.get("LBS"))
            if lbs is None:  # plate weight from the size: t x W x L x 0.2836 lb/in^3
                try:
                    from .aisc_profiles import resolve
                    d = resolve(row.get("SIZE"))["dims"]; lbs = round(d["t"] * d["w"] * d["l"] * 0.2836, 2)
                except Exception:
                    lbs = None
            put(r, col["LBS"], lbs, TXT, fill, fmt="#,##0.0")
        else:
            put(r, col["LEN_ft"], f"=IF({L('X2_ft')}{r}=\"\",\"\",SQRT(({L('X2_ft')}{r}-{L('X1_ft')}{r})^2+({L('Y2_ft')}{r}-{L('Y1_ft')}{r})^2+({L('Z2_ft')}{r}-{L('Z1_ft')}{r})^2))",
                TXT, fill, fmt="0.0000")
            put(r, col["LENGTH"], ftin_formula(f"{L('LEN_ft')}{r}"), BOLD, fill, Alignment(horizontal="right"))
            put(r, col["LB/FT"], _f(row.get("LB_FT")), TXT, fill, fmt="0.00")
            put(r, col["LBS"], f"=IF({L('LB/FT')}{r}=\"\",\"\",{L('LB/FT')}{r}*{L('LEN_ft')}{r})", TXT, fill, fmt="#,##0.0")
        put(r, col["ROT"], _f(row.get("ROT")) or 0, TXT, fill, Alignment(horizontal="center"), fmt="0")
        put(r, col["CP"], int(_f(row.get("CP")) or (5 if is_plate or str(row.get("TYPE","")).upper() in ("COLUMN","POST") else 8)),
            TXT, fill, Alignment(horizontal="center"))
        r += 1
    last = r - 1
    # totals
    put(r, col["MARK"], "TOTAL — modelled pieces", BOLD, LIGHT2)
    ws.merge_cells(start_row=r, start_column=col["MARK"], end_row=r, end_column=col["LEVEL"])
    put(r, col["PIECE"], None, BOLD, LIGHT2)
    put(r, col["LENGTH"], f'=COUNTA({L("MARK")}{first}:{L("MARK")}{last})&" pcs"', BOLD, LIGHT2, Alignment(horizontal="right"))
    put(r, col["LBS"], f"=SUM({L('LBS')}{first}:{L('LBS')}{last})", BOLD, LIGHT2, fmt="#,##0")
    put(r, col["RFI"], f"=TEXT({L('LBS')}{r}/2000,\"0.00\")&\" T\"", BOLD, LIGHT2)
    ws.merge_cells(start_row=r, start_column=col["RFI"], end_row=r, end_column=col["NOTES"])
    r += 2
    put(r, 1, "This total is the MODELLED steel (main members + base plates). It is a cross-check against Column Tonnage + Beam Tonnage + base plates, "
              "not a tonnage line — connection material in the Detail Register is not modelled.", NOTE, border=False)
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=len(VISIBLE))

    # widths / hidden helpers / freeze
    for h, w in WIDTHS.items():
        ws.column_dimensions[L(h)].width = w
    for h in HELPERS:
        ws.column_dimensions[L(h)].hidden = True
        ws.column_dimensions[L(h)].width = 10
    ws.freeze_panes = ws.cell(row=hdr_row + 1, column=col["SIZE"] + 1)
    return ws


def read_model_geometry_tab(path: str, sheet: str = "Model Geometry") -> list[dict]:
    """Read rows back out of a workbook tab (uses the hidden decimal helpers). Formulas are not evaluated here, so
    LB/FT is read as typed and LBS is left blank for members (build_ifc recomputes lb/ft x length)."""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=False)
    ws = wb[sheet]
    hdr = None
    for row in ws.iter_rows(min_row=1, max_row=30):
        vals = [c.value for c in row]
        if vals and vals[0] == "MARK":
            hdr = {v: i for i, v in enumerate(vals) if v}; hdr_row = row[0].row
            break
    if not hdr:
        raise ValueError("MARK header row not found")
    out = []
    for row in ws.iter_rows(min_row=hdr_row + 1, values_only=True):
        if not row or row[0] in (None, "") or str(row[0]).startswith("TOTAL") or row[hdr["TYPE"]] in (None, ""):
            continue
        rec = {h: (row[hdr[h]] if h in hdr else "") for h in ("MARK", "PIECE", "TYPE", "SIZE", "GRADE", "FINISH", "SHEET", "GRID", "LEVEL", "ROT", "CP", "RFI", "NOTES")}
        for k, h in zip(["X1", "Y1", "Z1", "X2", "Y2", "Z2"], HELPERS[:6]):
            rec[k] = row[hdr[h]]
        rec["LB_FT"] = row[hdr["LB/FT"]] if isinstance(row[hdr["LB/FT"]], (int, float)) else ""
        rec["LBS"] = row[hdr["LBS"]] if isinstance(row[hdr["LBS"]], (int, float)) else ""
        rec = {k: ("" if v is None else v) for k, v in rec.items()}
        out.append(rec)
    return out
