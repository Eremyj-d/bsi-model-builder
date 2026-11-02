"""
AISC shape lookup for the BSI takeoff -> IFC pipeline.

Resolves a designation as written in a Bohling takeoff workbook
("W14x38", "HSS5x5x5/16", "HSS9.625x.500", "L6x6x5/16", "C12x20.7",
"PIPE 6 SCH 80", "WT5x11", "PL 3/4x10x10") to:
    family   W / HP / M / S / C / MC / L / WT / MT / ST / HSS_RECT / HSS_ROUND / PIPE / PL
    label    AISC Manual label, e.g. "W14X38", "HSS5X5X5/16", "HSS9.625X0.500"
    dims     dict of section dimensions in inches (keys depend on family)
    plf      nominal weight (lb/ft) from the AISC database (None for plates)

Data source: AISC Shapes Database v16.0 CSVs vendored in bsi_model_builder/data/aisc (from the Apache-2.0 `steelpy` package).
"""
from __future__ import annotations
import csv, os, re
from functools import lru_cache
from fractions import Fraction

# AISC Shapes Database v16.0 CSVs, vendored from the Apache-2.0 `steelpy` package (see data/aisc/LICENSE-steelpy.txt)
_SHAPE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "aisc")

_FAMILY_FILES = {
    "W": "W_shapes.csv", "HP": "HP_shapes.csv", "M": "M_shapes.csv", "S": "S_shapes.csv",
    "C": "C_shapes.csv", "MC": "MC_shapes.csv", "L": "L_shapes.csv",
    "WT": "WT_shapes.csv", "MT": "MT_shapes.csv", "ST": "ST_shapes.csv",
    "HSS_RECT": "HSS_shapes.csv", "HSS_ROUND": "HSS_R_shapes.csv", "PIPE": "PIPE_shapes.csv",
}
_FRACTION_DENOMS = {2, 4, 8, 16, 32}


def _num_from_parts(parts: list[str]) -> float:
    """Decode an AISC csv name segment: '3_4' -> 0.75, '1_3_8' -> 1.375, '9_625' -> 9.625, '20_7' -> 20.7."""
    ints = [int(p) for p in parts]
    if len(ints) == 1:
        return float(ints[0])
    if len(ints) == 3:  # mixed number a-b/c
        return ints[0] + ints[1] / ints[2]
    a, b = ints
    if a < b and b in _FRACTION_DENOMS:
        return a / b
    # decimal: the second part keeps its printed digits ('625' -> .625, '500' -> .500, '7' -> .7)
    return float(f"{a}.{parts[1]}")


def _parse_csv_key(key: str) -> tuple[str, tuple[float, ...]]:
    k = key.strip().upper()
    m = re.match(r"^(HSS|PIPE|WT|MT|ST|MC|HP|W|M|S|C|L)(.*)$", k)
    if not m:
        return "", ()
    fam, rest = m.group(1), m.group(2)
    if fam == "PIPE":
        return fam, ()  # handled by name
    nums = []
    for seg in rest.split("X"):
        if not seg:
            continue
        nums.append(_num_from_parts(seg.split("_")))
    if fam == "HSS":
        fam = "HSS_RECT" if len(nums) == 3 else "HSS_ROUND"
    return fam, tuple(nums)


def _parse_user_number(s: str) -> float:
    """'5/16' -> 0.3125, '3-1/2' -> 3.5, '.500' -> 0.5, '9.625' -> 9.625, '1 3/8' -> 1.375"""
    s = s.strip().replace('"', "").replace("''", "")
    s = s.replace(" ", "-")
    if "/" in s:
        if "-" in s:
            whole, frac = s.split("-", 1)
            return float(whole) + float(Fraction(frac))
        return float(Fraction(s))
    if s.startswith("."):
        s = "0" + s
    return float(s)


@lru_cache(maxsize=None)
def _table(family: str) -> dict:
    """family -> {key: row-dict}"""
    out = {}
    if not _SHAPE_DIR:
        return out
    path = os.path.join(_SHAPE_DIR, _FAMILY_FILES[family])
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            out[row["shape"].strip()] = row
    return out


def _f(row, key):
    v = row.get(key)
    try:
        return float(v)
    except Exception:
        return None


def _match_numeric(family: str, nums: tuple[float, ...], allow_swap=False):
    rows = _table(family)
    best = None
    for key, row in rows.items():
        fam, knums = _parse_csv_key(key)
        if fam != family or len(knums) != len(nums):
            continue
        cands = [knums]
        if allow_swap and len(knums) == 3:
            cands.append((knums[1], knums[0], knums[2]))
        for kn in cands:
            if all(abs(a - b) <= max(0.003, 0.002 * max(abs(a), abs(b))) for a, b in zip(nums, kn)):
                return key, row
    return best


def _label_from_key(family: str, key: str, nums: tuple[float, ...]) -> str:
    """AISC Manual label: W14X38, HSS5X5X5/16, HSS9.625X0.500, L6X6X5/16, C12X20.7, WT5X11"""
    def frac(v: float) -> str:
        fr = Fraction(v).limit_denominator(16)
        whole, rem = divmod(fr.numerator, fr.denominator)
        if rem == 0:
            return str(whole)
        if whole:
            return f"{whole}-{rem}/{fr.denominator}"
        return f"{rem}/{fr.denominator}"
    def dec(v: float) -> str:
        return (f"{v:.1f}" if abs(v - round(v, 1)) < 1e-9 else f"{v:g}") if v != int(v) else str(int(v))
    if family == "HSS_RECT":
        return f"HSS{frac(nums[0])}X{frac(nums[1])}X{frac(nums[2])}"
    if family == "HSS_ROUND":
        return f"HSS{nums[0]:.3f}X{nums[1]:.3f}"
    if family == "L":
        return f"L{frac(nums[0])}X{frac(nums[1])}X{frac(nums[2])}"
    if family in ("W", "HP", "M", "S", "C", "MC", "WT", "MT", "ST"):
        return f"{family}{dec(nums[0])}X{dec(nums[1])}"
    return key


def _pipe_lookup(text: str):
    """'PIPE 6 SCH 80', '6" SCH 80 PIPE', 'PIPE6XS', 'PIPE 4 STD', 'PIPE6SCH80' -> csv key."""
    t = text.upper().replace('"', "").replace("Ø", "").replace("DIA", "")
    nominal = None
    m = re.search(r"(\d+(?:\.\d+)?(?:-\d/\d)?|\d/\d)", t)
    if m:
        nominal = m.group(1)
    sched = "STD"
    if re.search(r"XXS|SCH\s*160|DOUBLE\s*EXTRA", t):
        sched = "XXS"
    elif re.search(r"\bXS\b|SCH\s*80|EXTRA\s*STRONG", t):
        sched = "XS"
    elif re.search(r"\bSTD\b|SCH\s*40|STANDARD", t):
        sched = "STD"
    if nominal is None:
        return None
    nom = nominal.replace("-1/2", "_1_2").replace("1/2", "1_2").replace(".5", "_1_2")
    key = f"Pipe{nom}{sched}"
    rows = _table("PIPE")
    for k, row in rows.items():
        if k.upper() == key.upper():
            return k, row
    return None


def resolve(designation: str) -> dict | None:
    """Resolve a workbook designation. Returns None when it cannot be matched."""
    if designation is None:
        return None
    raw = str(designation).strip()
    t = raw.upper().replace(" X ", "X").replace("×", "X")
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"(\d) (\d+/\d+)", r"\1-\2", t)  # "1 3/4" -> "1-3/4" (mixed number)

    # plates: PL 3/4x10x10 / PL3/4 x 10 x 1'-8" -> thickness, width, length (inches)
    m = re.match(r"^(?:PL|PLATE|BAR|FB)\s*(.+)$", t)
    if m:
        segs = [s for s in re.split(r"X", m.group(1).replace(" ", "")) if s]
        nums = []
        for s in segs:
            fm = re.match(r"^(\d+)'-?(\d+(?:[ -]\d/\d+)?)?\"?$", s)
            if fm and "'" in s:
                nums.append(float(fm.group(1)) * 12 + (_parse_user_number(fm.group(2)) if fm.group(2) else 0))
            else:
                try:
                    nums.append(_parse_user_number(s))
                except Exception:
                    pass
        return {"family": "PL", "label": "PL " + "X".join(segs), "dims": {"t": nums[0] if nums else None,
                "w": nums[1] if len(nums) > 1 else None, "l": nums[2] if len(nums) > 2 else None}, "plf": None, "raw": raw}

    if "PIPE" in t or re.search(r"SCH\s*\d+", t):
        hit = _pipe_lookup(t)
        if not hit:
            return None
        key, row = hit
        return {"family": "PIPE", "label": key.upper(), "dims": {"OD": _f(row, "OD"), "t": _f(row, "tnom"), "tdes": _f(row, "tdes")},
                "plf": _f(row, "weight"), "raw": raw}

    m = re.match(r"^(HSS|WT|MT|ST|MC|HP|W|M|S|C|L)\s*(.+)$", t.replace(" ", ""))
    if not m:
        return None
    fam, rest = m.group(1), m.group(2)
    segs = [s for s in rest.split("X") if s]
    try:
        nums = tuple(_parse_user_number(s) for s in segs)
    except Exception:
        return None
    if fam == "HSS":
        fam = "HSS_RECT" if len(nums) == 3 else "HSS_ROUND"
    hit = _match_numeric(fam, nums, allow_swap=(fam == "HSS_RECT"))
    if not hit:
        return None
    key, row = hit
    label = _label_from_key(fam, key, nums)
    dims = {}
    if fam in ("W", "HP", "M", "S"):
        dims = {"d": _f(row, "d"), "bf": _f(row, "bf"), "tw": _f(row, "tw"), "tf": _f(row, "tf"), "k": _f(row, "k")}
    elif fam in ("C", "MC"):
        dims = {"d": _f(row, "d"), "bf": _f(row, "bf"), "tw": _f(row, "tw"), "tf": _f(row, "tf"), "k": _f(row, "k"), "x": _f(row, "x")}
    elif fam in ("WT", "MT", "ST"):
        dims = {"d": _f(row, "d"), "bf": _f(row, "bf"), "tw": _f(row, "tw"), "tf": _f(row, "tf"), "k": _f(row, "k"), "y": _f(row, "y")}
    elif fam == "L":
        dims = {"d": nums[0], "b": nums[1], "t": _f(row, "t"), "k": _f(row, "k"), "x": _f(row, "x"), "y": _f(row, "y")}
    elif fam == "HSS_RECT":
        dims = {"Ht": nums[0], "B": nums[1], "t": _f(row, "tnom"), "tdes": _f(row, "tdes")}
    elif fam == "HSS_ROUND":
        dims = {"OD": _f(row, "OD"), "t": _f(row, "tnom"), "tdes": _f(row, "tdes")}
    return {"family": fam, "label": label, "dims": dims, "plf": _f(row, "weight"), "raw": raw}


if __name__ == "__main__":
    for s in ["W14x38", "W8x35", "HSS5x5x5/16", "HSS12x10x1/2", "HSS10x5x5/16", "HSS6x4x1/2", "HSS9.625x.500",
              "HSS4.000x.313", "HSS3.500x.250", "L6x6x5/16", "L3-1/2x3-1/2x1/4", "L8x4x1/2", "C12x20.7", "C6x8.2",
              "WT5x11", "MC8x8.5", "PIPE 6 SCH 80", "6\" SCH 40 PIPE", "PL 3/4x10x10", "PL 1 3/4 x 20 x 1'-8\"",
              "HSS6x6x3/8", "HSS4x4x3/8", "W24x117", "L4x4x3/4", "S8x18.4", "HP12x53"]:
        r = resolve(s)
        print(f"{s:28s} -> {r['family']:9s} {r['label']:18s} plf={r['plf']} {r['dims']}" if r else f"{s:28s} -> NO MATCH")
