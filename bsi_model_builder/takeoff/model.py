"""
The takeoff data model — everything a Bohling takeoff carries, as plain dataclasses that round-trip to JSON
(`<Job>_takeoff.json`). The API extraction stages fill it in; the workbook, document and IFC builders read it.

Units: lengths in DECIMAL FEET (display code turns them into ft-in), weights in lb, lb/ft as on the workbook.
Every list row carries `rfi` (list of BSI-xx codes) so the RFI column on each tab can be filled by priority.
"""
from __future__ import annotations
import dataclasses, json, datetime
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any

PRIORITIES = ("P1", "P2", "P3", "INFO")
FINISH_STEEL = ("Primed", "Galv")
FINISH_HARDWARE = ("Plain", "Galv")


# ----------------------------------------------------------------------------- header / sheets
@dataclass
class Header:
    job: str = ""
    job_code: str = ""
    building: str = ""
    rev: str = "REV 0"
    status: str = "IN PROGRESS"
    date: str = field(default_factory=lambda: datetime.date.today().isoformat())
    owner: str = ""
    architect: str = ""
    ser: str = ""                   # structural engineer of record
    gc: str = ""
    site: str = ""
    bid_due: str = ""
    set_description: str = ""       # "Bid set 10/09/2026, Addenda 1-3, Project Manual"
    source_files: list[str] = field(default_factory=list)
    scope_summary: str = ""         # one paragraph under SCOPE OF WORK on the Summary
    estimator: str = "Jeremy Davis, Estimator"
    company: str = "Bohling Steel, Inc."
    address: str = "3410 Forest Brook Road, Lynchburg, VA 24501"


@dataclass
class Sheet:
    number: str
    title: str = ""
    status: str = "RECEIVED"        # RECEIVED / PENDING / NOT RECEIVED
    date: str = ""
    steel: str = "?"                # Y / N / ? — does the sheet carry steel scope
    reviewed: bool = False
    notes: str = ""
    page: int | None = None         # page index in the source PDF
    file: str = ""


# ----------------------------------------------------------------------------- material rows
@dataclass
class ColumnRow:
    mark: str
    size: str
    qty: int = 1
    height_ft: float | None = None          # T/FTG → T/STL, decimal feet
    lb_ft: float | None = None
    base_plate: str = ""
    bp_elev: str = ""                        # 'T/FTG -2'-0" → T/STL 14'-10"'
    anchors: str = ""                        # '(4) 3/4" dia'
    finish: str = "Primed"
    grade: str = "A992"
    location: str = ""
    notes: str = ""
    sheet: str = ""
    rfi: list[str] = field(default_factory=list)
    allowance: bool = False

    @property
    def lbs(self) -> float:
        return (self.lb_ft or 0) * (self.height_ft or 0) * self.qty


@dataclass
class BeamRow:
    """one row per beam callout (Beam Detail — by Member); Beam Tonnage rolls these up"""
    sheet: str
    size: str
    length_ft: float
    lb_ft: float | None = None
    tag: str = ""                            # studs / camber / plan tag as printed
    mark: str = ""                           # optional piece mark for the model
    finish: str = "Primed"
    grade: str = "A992"
    level: str = ""                          # 'T/STL 14'-10"'
    note: str = ""
    flag: str = ""                           # VERIFY … text
    x_pt: float | None = None                # plan position (PDF points) when read by the geometry method
    y_pt: float | None = None
    rfi: list[str] = field(default_factory=list)
    allowance: bool = False

    @property
    def lbs(self) -> float:
        return (self.lb_ft or 0) * self.length_ft


@dataclass
class MemoRow:
    """joists, deck, other memo-only quantities (excluded from tonnage)"""
    sheet: str
    item: str
    qty: float
    unit: str                                # EA / SF / LF
    lb_per_unit: float | None = None
    length_ft: float | None = None
    note: str = ""
    rfi: list[str] = field(default_factory=list)

    @property
    def lbs(self) -> float:
        if self.lb_per_unit is None:
            return 0.0
        return self.lb_per_unit * (self.length_ft if self.length_ft else 1.0) * self.qty


@dataclass
class AnchorRow:
    group: str                               # 'Column ABs' / 'Additional AB Groups' / 'Lintel ABs'
    location: str
    member: str
    diameter: str                            # '3/4"'
    per_item: int
    item_qty: int
    length: str                              # '1'-6"' or '12"' as called out
    lb_ea: float
    finish: str = "Galv"                     # Plain / Galv
    grade: str = "F1554 Gr.55"
    notes: str = ""
    rfi: list[str] = field(default_factory=list)
    allowance: bool = False

    @property
    def total_ea(self) -> int:
        return self.per_item * self.item_qty

    @property
    def lbs(self) -> float:
        return self.total_ea * self.lb_ea


@dataclass
class BoltRow:
    group: str                               # 'Beam-to-Beam Shear' / 'Beam-on-Column Cap Plate' / 'Moment' / 'Brace' / 'Post-installed'
    connection_type: str
    location: str
    spec: str                                # '3/4" x 2 1/2" A325-N'
    per_conn: int
    conn_qty: int
    lb_ea: float
    finish: str = "Plain"
    notes: str = ""
    rfi: list[str] = field(default_factory=list)
    allowance: bool = False

    @property
    def total_ea(self) -> int:
        return self.per_conn * self.conn_qty

    @property
    def lbs(self) -> float:
        return self.total_ea * self.lb_ea


@dataclass
class PartRow:
    """Misc Parts (net of the Detail Register) and Misc Metals rows — QTY | SHAPE | THICKNESS | SIZE | LENGTH | LB/EA | TOTAL"""
    group: str                               # 'Base Plates' / 'Plate Washers' / 'Stairs' / 'Ladders' / 'Rails' / 'Bollards' …
    qty: int
    shape: str                               # PL / L / C / HSS / PIPE / BAR …
    size: str                                # '3/4 x 12 x 12' / 'L4x4x1/4'
    lb_ea: float
    thickness: str = ""
    length_ft: float | None = None
    finish: str = "Primed"
    grade: str = "A572 Gr.50"
    source: str = ""
    mark: str = ""
    rfi: list[str] = field(default_factory=list)
    allowance: bool = False

    @property
    def lbs(self) -> float:
        return self.qty * self.lb_ea


@dataclass
class DetailItem:
    detail_ref: str                          # '1,5,8/S-5010'
    condition: str
    item: str
    size_spec: str
    unit_basis: str                          # 'per LF of edge' / '1 per column' / '@ 2'-0" o.c.'
    lb_per_unit: float
    qty_applied: float | None                # None = NOT YET APPLIED (yellow input left blank)
    unit: str                                # LF / EA / SET / PR
    qty_source: str = ""
    notes: str = ""
    finish: str = "Primed"
    grade: str = "A572 Gr.50"
    rfi: list[str] = field(default_factory=list)

    @property
    def lbs(self) -> float:
        return 0.0 if self.qty_applied is None else self.lb_per_unit * self.qty_applied


@dataclass
class Kit:
    letter: str                              # A, B, C … ; the closing no-steel kit uses 'Z'
    title: str
    refs: str = ""                           # 'S-5010 details 1,2,3,4,5,7'
    items: list[DetailItem] = field(default_factory=list)
    no_steel: bool = False                   # closing section: details reviewed that add no new steel

    @property
    def lbs(self) -> float:
        return sum(i.lbs for i in self.items)


@dataclass
class NoteLine:
    sheet: str
    text: str


@dataclass
class RFIItem:
    code: str                                # BSI-01
    priority: str                            # P1 / P2 / P3 / INFO
    to: str                                  # SER / ARCH / GC / SER/GC
    subject: str
    question: str                            # 'confirm or correct' wording
    carried: str = ""                        # what is in the bid
    status: str = "OPEN"
    lbs_flagged: float = 0.0
    where_flagged: str = ""                  # 'Column Tonnage: C1-C6; Misc Parts: BP-A'
    exposure_lbs: float = 0.0                # INTERNAL — swing if answered the other way
    answer: str = ""


@dataclass
class ScopeItem:
    item: str
    quantity: str
    unit: str


@dataclass
class Scope:
    inclusions: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    clarifications: list[str] = field(default_factory=list)
    quantities: list[ScopeItem] = field(default_factory=list)
    tonnage_statement: str = ""
    preliminary: bool = True


@dataclass
class GeometryRow:
    MARK: str
    TYPE: str
    SIZE: str
    X1: float
    Y1: float
    Z1: float
    X2: float | None = None
    Y2: float | None = None
    Z2: float | None = None
    PIECE: str = "1"
    GRADE: str = "A992"
    FINISH: str = "Primed"
    SHEET: str = ""
    GRID: str = ""
    LEVEL: str = ""
    ROT: float = 0.0
    CP: int | None = None
    LB_FT: float | None = None
    LBS: float | None = None
    RFI: str = ""
    NOTES: str = ""


@dataclass
class Revision:
    rev: str
    date: str
    note: str
    was_lbs: float | None = None
    now_lbs: float | None = None


@dataclass
class Takeoff:
    header: Header = field(default_factory=Header)
    sheets: list[Sheet] = field(default_factory=list)
    columns: list[ColumnRow] = field(default_factory=list)
    beams: list[BeamRow] = field(default_factory=list)
    memo: list[MemoRow] = field(default_factory=list)
    anchors: list[AnchorRow] = field(default_factory=list)
    bolts: list[BoltRow] = field(default_factory=list)
    misc_parts: list[PartRow] = field(default_factory=list)
    misc_metals: list[PartRow] = field(default_factory=list)
    kits: list[Kit] = field(default_factory=list)
    notes: list[NoteLine] = field(default_factory=list)
    rfis: list[RFIItem] = field(default_factory=list)
    scope: Scope = field(default_factory=Scope)
    geometry: list[GeometryRow] = field(default_factory=list)
    revisions: list[Revision] = field(default_factory=list)
    inclusions: list[str] = field(default_factory=list)      # Summary green block
    exclusions: list[str] = field(default_factory=list)      # Summary red block
    assumptions: list[str] = field(default_factory=list)
    galv_unquantified: list[str] = field(default_factory=list)  # Finish Summary: galvanized-but-unquantified
    extraction_log: list[dict] = field(default_factory=list)    # stage / model / tokens / cost / cache

    # ------------------------------------------------------------------ totals (mirror the workbook formulas)
    def totals(self) -> dict:
        cols = sum(c.lbs for c in self.columns)
        beams = sum(b.lbs for b in self.beams)
        kits = sum(k.lbs for k in self.kits)
        parts = sum(p.lbs for p in self.misc_parts)
        ab = sum(a.lbs for a in self.anchors)
        fb = sum(b.lbs for b in self.bolts)
        project = cols + beams + kits + parts + ab + fb
        return {"columns": cols, "beams": beams, "detail_register": kits, "misc_parts": parts,
                "anchor_bolts": ab, "field_bolts": fb, "project": project, "tons": project / 2000.0,
                "misc_metals": sum(p.lbs for p in self.misc_metals), "memo": sum(m.lbs for m in self.memo),
                "pieces": {"columns": sum(c.qty for c in self.columns), "beams": len(self.beams)}}

    def finish_totals(self) -> dict:
        """fabricated steel by finish (columns + beams + kits + misc parts); held out = anchors + bolts"""
        out = {"Primed": 0.0, "Galv": 0.0}
        for c in self.columns:
            out[c.finish if c.finish in out else "Primed"] += c.lbs
        for b in self.beams:
            out[b.finish if b.finish in out else "Primed"] += b.lbs
        for k in self.kits:
            for i in k.items:
                out[i.finish if i.finish in out else "Primed"] += i.lbs
        for p in self.misc_parts:
            out[p.finish if p.finish in out else "Primed"] += p.lbs
        held = sum(a.lbs for a in self.anchors) + sum(b.lbs for b in self.bolts)
        return {"Primed": out["Primed"], "Galv": out["Galv"], "held_out": held,
                "fabricated": out["Primed"] + out["Galv"], "total": out["Primed"] + out["Galv"] + held}

    def rfi_priority(self, code: str) -> str | None:
        for r in self.rfis:
            if r.code == code:
                return r.priority
        return None

    def beam_rollup(self) -> list[dict]:
        """Beam Tonnage rows: one per (sheet, size, length to 1/8\", finish, grade)"""
        groups: dict[tuple, dict] = {}
        for b in self.beams:
            key = (b.sheet, b.size.upper(), round(b.length_ft * 96) / 96, b.finish, b.grade)   # group to 1/8"
            g = groups.setdefault(key, {"sheet": b.sheet, "size": b.size, "length_ft": b.length_ft, "lb_ft": b.lb_ft or 0,
                                        "finish": b.finish, "grade": b.grade, "qty": 0, "lbs": 0.0, "len_sum": 0.0, "notes": set(), "rfi": set(), "allowance": False})
            g["qty"] += 1; g["lbs"] += b.lbs; g["len_sum"] += b.length_ft; g["allowance"] |= b.allowance
            g["length_ft"] = g["len_sum"] / g["qty"]            # exact mean length, so qty × lb/ft × length ties to Beam Detail
            if b.note:
                g["notes"].add(b.note)
            g["rfi"].update(b.rfi)
        rows = []
        for g in groups.values():
            g["notes"] = "; ".join(sorted(g["notes"])); g["rfi"] = sorted(g["rfi"]); rows.append(g)
        rows.sort(key=lambda r: (r["sheet"], r["size"], r["length_ft"]))
        return rows

    # ------------------------------------------------------------------ JSON
    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    def to_json(self, path: str) -> str:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=1, ensure_ascii=False)
        return path

    @classmethod
    def from_dict(cls, d: dict) -> "Takeoff":
        return _from_dict(cls, d)

    @classmethod
    def from_json(cls, path: str) -> "Takeoff":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))


def _from_dict(cls, d: Any):
    if d is None:
        return None
    if is_dataclass(cls):
        kwargs = {}
        for f in fields(cls):
            if f.name not in d:
                continue
            kwargs[f.name] = _coerce(f.type, d[f.name])
        return cls(**kwargs)
    return d


_TYPES: dict = {}


def _coerce(t, v):
    """t is the annotation as a string (from __future__ annotations): 'Header', 'list[Sheet]', 'float | None' …"""
    name = t if isinstance(t, str) else getattr(t, "__name__", str(t))
    if name.startswith("list[") and name.endswith("]"):
        cls = _TYPES.get(name[5:-1])
        if cls is not None and isinstance(v, list):
            return [_from_dict(cls, x) if isinstance(x, dict) else x for x in v]
        return list(v or [])
    cls = _TYPES.get(name.split(" | ")[0].strip())
    if cls is not None and isinstance(v, dict):
        return _from_dict(cls, v)
    return v


for _c in (Header, Sheet, ColumnRow, BeamRow, MemoRow, AnchorRow, BoltRow, PartRow, DetailItem, Kit, NoteLine,
           RFIItem, ScopeItem, Scope, GeometryRow, Revision, Takeoff):
    _TYPES[_c.__name__] = _c


# ----------------------------------------------------------------------------- display helpers
FRAC8 = {0: "", 1: " 1/8", 2: " 1/4", 3: " 3/8", 4: " 1/2", 5: " 5/8", 6: " 3/4", 7: " 7/8"}


def ft_in(x: float | None) -> str:
    if x is None:
        return ""
    neg = x < 0; x = abs(x)
    q = int(round(x * 96)); ft, rem = divmod(q, 96); inch, e8 = divmod(rem, 8)
    return ("-" if neg else "") + f"{ft}'-{inch}{FRAC8[e8]}\""


def parse_ft_in(s: str) -> float | None:
    """'14'-10\"' | '14'-10 1/2\"' | '14.8333' | '10\"' -> decimal feet (None if blank / unreadable)"""
    import re
    if s is None:
        return None
    t = str(s).strip().replace("”", '"').replace("’", "'").replace("′", "'").replace("″", '"')
    if not t:
        return None
    neg = t.startswith("-"); t = t.lstrip("-").strip()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)", t)
    if m:
        v = float(m.group(1)); return -v if neg else v
    m = re.fullmatch(r"(?:(\d+)')?\s*-?\s*(?:(\d+)(?:\s+(\d+)/(\d+)|-(\d+)/(\d+))?\"?)?", t)
    if not m or not (m.group(1) or m.group(2)):
        return None
    ft = float(m.group(1) or 0); inch = float(m.group(2) or 0)
    if m.group(3):
        inch += float(m.group(3)) / float(m.group(4))
    elif m.group(5):
        inch += float(m.group(5)) / float(m.group(6))
    v = ft + inch / 12.0
    return -v if neg else v
