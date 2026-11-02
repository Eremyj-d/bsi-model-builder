"""
The extraction engine — drawings in, Takeoff out.

    res = run_takeoff(pdf_paths, header, provider, out_dir, progress=print)
    # res.takeoff (Takeoff), res.takeoff_json, res.log (list of stage records), res.cost

Stages (each one forced-tool call per page or per group, cached on disk by content):
    index      page listing (+ title-block text)            → sheets, parties, set description
    notes      general-notes / spec pages (text)            → grades, finish rules, key notes
    columns    column schedule + foundation plans (images)  → columns, base plates, anchor rods, column geometry
    framing    each framing / elevation sheet (image + the app's geometry pass) → beams, memo, openings, connection counts
    details    each details / schedule / arch / MEP / civil sheet (tiled images) → kits, bolts, misc parts, misc metals
    synthesis  the whole model (JSON)                        → RFI log, scope, Summary blocks, assumptions

Between the stages the app does the deterministic work itself: AISC weights, plate weights, slope correction
check, bolt counts from the framing connection counts, RFI draft keys → BSI-xx codes, Model Geometry rows.
The takeoff JSON is saved after every stage, so a run can resume.
"""
from __future__ import annotations
import json, os, re, time, traceback
from dataclasses import dataclass, field
from . import schemas
from .model import *
from ..core.aisc_profiles import resolve

_PROMPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")

# A "spec book" = a PDF with many text-only pages (a project manual). It is not listed page by page: the app
# scans it locally for the steel-relevant sections and feeds only those pages to the notes stage.
SPEC_BOOK_MIN_PAGES = 60
SPEC_KEYWORDS = ("SECTION 05", "DIVISION 05", "DIVISION 5", "STRUCTURAL STEEL", "METAL FABRICATION", "STEEL JOIST", "STEEL DECK",
                 "ARCHITECTURAL METAL", "GALVANIZ", "051200", "052100", "053100", "055000", "055100", "055119", "051213", "ANCHOR ROD", "AISC")
# Steel-relevant words for architectural / MEP / civil pages: a page whose text has none of these is logged as
# reviewed (no steel) without an API call. Raster pages (no text) always go to the model.
STEEL_WORDS = re.compile(r"\b(STEEL|LINTEL|ANGLE|HSS|W\d{1,2}X\d+|C\d{1,2}X\d+|L\d{1,2}X\d+|PL\s?\d+|PLATE|LADDER|RAIL(ING)?|GUARD|BOLLARD|STAIR|STRINGER|SHELF|EMBED|ANCHOR|"
                         r"CURB|RTU|FRAME|CANOPY|GATE|GRATING|CHANNEL|TUBE|PIPE\s?\d|BENT PL|KICKER|POUR STOP|GALV|WELD|BRACKET|SUPPORT)\b", re.I)
PLAN_KINDS = {"foundation_plan", "column_schedule", "framing_plan", "elevation"}
DETAIL_KINDS = {"sections_details", "schedules", "arch_plan", "arch_elevation", "arch_section_detail", "mechanical", "civil", "plumbing", "electrical", "other"}
NOTE_KINDS = {"general_notes", "specs", "cover_index"}


def prompt(name: str) -> str:
    with open(os.path.join(_PROMPTS, f"{name}.md"), encoding="utf-8") as fh:
        return fh.read()


def system_prompt(extra: str = "") -> str:
    return prompt("system") + ("\n\nJOB-SPECIFIC NOTES:\n" + extra if extra else "")


@dataclass
class StageRecord:
    stage: str
    label: str
    model: str
    input_tokens: int
    output_tokens: int
    cost: float
    cached: bool
    elapsed: float


@dataclass
class RunResult:
    takeoff: Takeoff
    takeoff_json: str = ""
    log: list[StageRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def cost(self) -> float:
        return sum(r.cost for r in self.log)

    @property
    def tokens(self) -> tuple[int, int]:
        return sum(r.input_tokens for r in self.log), sum(r.output_tokens for r in self.log)


# ----------------------------------------------------------------------------- weights (deterministic)
def plf(size: str) -> float | None:
    r = resolve(size)
    return r["plf"] if r else None


def plate_lbs(size: str) -> float | None:
    r = resolve(size)
    if r and r["family"] == "PL" and all(r["dims"].get(k) for k in ("t", "w", "l")):
        d = r["dims"]; return round(d["t"] * d["w"] * d["l"] * 0.2836, 2)
    return None


def unit_weight(size_spec: str, unit: str) -> float | None:
    """lb per LF for rolled shapes, lb each for plates with t x W x L"""
    if unit == "LF":
        return plf(size_spec)
    if unit in ("EA", "SET", "PR"):
        w = plate_lbs(size_spec)
        if w is not None:
            return w
        p = plf(size_spec)                     # 'L6x4x3/8 (LLV) x 0'-8"' style: length after ' x '
        m = re.search(r"x\s*(\d+)'-(\d+(?:\s\d/\d+)?)\"?\s*$", size_spec)
        if p and m:
            return round(p * parse_ft_in(m.group(1) + "'-" + m.group(2) + '"'), 2)
    return None


# ----------------------------------------------------------------------------- the engine
class Engine:
    def __init__(self, provider, out_dir: str, progress=None, dpi: int = 100, detail_dpi: int = 150, job_notes: str = ""):
        self.p = provider
        self.out_dir = out_dir
        self.say = progress or (lambda *_: None)
        self.dpi, self.detail_dpi = dpi, detail_dpi
        self.system = system_prompt(job_notes)
        self.log: list[StageRecord] = []
        self.errors: list[str] = []
        self.rfi_drafts: dict[str, dict] = {}
        os.makedirs(out_dir, exist_ok=True)

    # ------------------------------------------------------------------ plumbing
    def _call(self, stage: str, blocks: list[dict], label: str = "") -> dict:
        tool = schemas.STAGES[stage]
        t0 = time.time()
        r = self.p.call(stage, self.system, blocks, tool, label=label)
        rec = StageRecord(stage, label, r.model, r.usage.get("input_tokens", 0), r.usage.get("output_tokens", 0), r.cost(), r.cached, time.time() - t0)
        self.log.append(rec)
        self.say(f"  {stage:9s} {label:10s} {'cache' if r.cached else f'{rec.input_tokens:,} in / {rec.output_tokens:,} out  ${rec.cost:.2f}'}")
        return r.data

    def _save(self, t: Takeoff, path: str):
        t.extraction_log = [r.__dict__ for r in self.log]
        t.to_json(path)

    def _draft(self, drafts: list[dict] | None, sheet: str = ""):
        for d in drafts or []:
            key = d.get("key") or re.sub(r"[^a-z0-9]+", "-", d.get("subject", "rfi").lower())[:40]
            if key in self.rfi_drafts:
                continue
            d = dict(d); d["key"] = key; d.setdefault("sheet", sheet)
            self.rfi_drafts[key] = d

    @staticmethod
    def _img(ds, i, dpi, clip=None):
        from .providers import image_block
        return image_block(ds.render_page(i, dpi=dpi, clip=clip))

    @staticmethod
    def _txt(s: str):
        from .providers import text_block
        return text_block(s)

    def _page_text(self, ds, i, cap: int = 40000) -> str:
        try:
            spans = ds.page_text(i)
        except Exception:
            return ""
        lines = []
        for s in spans:
            bb = s.get("bbox", [0, 0, 0, 0])
            lines.append(f"[{bb[0]:.0f},{bb[1]:.0f}] {s['text']}")
        out = "\n".join(lines)
        return out[:cap] + ("\n… (truncated)" if len(out) > cap else "")

    def _tiles(self, ds, i):
        pg = ds.pages[i]
        w, h = pg.width_pt, pg.height_pt
        blocks = []
        for r, (x0, y0, x1, y1) in enumerate([(0, 0, w / 2, h / 2), (w / 2, 0, w, h / 2), (0, h / 2, w / 2, h), (w / 2, h / 2, w, h)]):
            blocks.append(self._txt(f"tile {r+1} of 4 ({'top' if y0 == 0 else 'bottom'}-{'left' if x0 == 0 else 'right'} quarter) at {self.detail_dpi} dpi:"))
            blocks.append(self._img(ds, i, self.detail_dpi, clip=(x0, y0, x1, y1)))
        return blocks

    # ------------------------------------------------------------------ stages
    def _find_spec_books(self, ds) -> dict[str, list[int]]:
        """file -> page indexes, for PDFs that look like a project manual (many pages, text, no vector drawings)"""
        by_file: dict[str, list] = {}
        for pg in ds.pages:
            by_file.setdefault(pg.file, []).append(pg)
        books = {}
        for f, pgs in by_file.items():
            if len(pgs) >= SPEC_BOOK_MIN_PAGES and sum(1 for p in pgs if p.has_vector) < 0.1 * len(pgs) and sum(1 for p in pgs if p.text_chars > 200) > 0.6 * len(pgs):
                books[f] = [p.page_index for p in pgs]
        return books

    def _spec_pages(self, ds, pages: list[int]) -> list[int]:
        """pages of a spec book that mention the steel sections (local keyword scan, no API)"""
        hits = []
        for i in pages:
            try:
                txt = " ".join(sp["text"] for sp in ds.page_text(i)).upper()
            except Exception:
                continue
            if any(k in txt for k in SPEC_KEYWORDS):
                hits.append(i)
        return hits

    def stage_index(self, ds, t: Takeoff):
        books = self._find_spec_books(ds)
        self.spec_pages: list[int] = []
        for f, pgs in books.items():
            hits = self._spec_pages(ds, pgs)
            self.spec_pages += hits
            self.say(f"  spec book {os.path.basename(f)}: {len(pgs)} pages, {len(hits)} with steel sections (scanned locally)")
        book_pages = {i for pgs in books.values() for i in pgs}
        listing = ["IDX | FILE | DETECTED SHEET | TITLE | VECTOR | TEXT CHARS"]
        for f, pgs in books.items():
            listing.append(f"{pgs[0]}-{pgs[-1]} | {os.path.basename(f)} | SPEC BOOK | project manual, {len(pgs)} pages — steel sections scanned locally, do not list page by page | N | -")
        for pg in ds.pages:
            if pg.page_index in book_pages:
                continue
            listing.append(f"{pg.page_index} | {os.path.basename(pg.file)} | {pg.sheet_number or '?'} | {pg.sheet_title or ''} | {'Y' if pg.has_vector else 'N'} | {pg.text_chars}")
        blocks = [self._txt(prompt("index")), self._txt("\n".join(listing))]
        for pg in ds.pages:
            if pg.page_index in book_pages:
                continue
            txt = self._page_text(ds, pg.page_index, cap=1200)
            if txt:
                blocks.append(self._txt(f"--- page {pg.page_index} text (head) ---\n{txt}"))
        d = self._call("index", blocks, "set")
        t.header.set_description = t.header.set_description or d.get("set_description", "")
        for k, v in (d.get("parties") or {}).items():
            if v and not getattr(t.header, k, ""):
                setattr(t.header, k, v)
        t.sheets = []
        self.kinds: dict[int, str] = {}
        for s in d["sheets"]:
            page = s.get("page")
            t.sheets.append(Sheet(number=s["number"], title=s.get("title", ""), status="RECEIVED", date=t.header.date, steel=s.get("steel", "?"),
                                  reviewed=False, notes=s.get("why", ""), page=page, file=ds.pages[page].file if page is not None and page < len(ds.pages) else ""))
            if page is not None:
                self.kinds[page] = s["kind"]
                if page < len(ds.pages) and s.get("number"):
                    ds.pages[page].sheet_number = s["number"]
        return d

    def stage_notes(self, ds, t: Takeoff):
        pages = [i for i, k in self.kinds.items() if k in NOTE_KINDS] + [i for i in getattr(self, "spec_pages", []) if i not in self.kinds]
        if not pages:
            return None
        blocks = [self._txt(prompt("notes"))]
        budget = 160000                       # chars of page text per notes call (~40k tokens); spec pages are the long tail
        for i in pages:
            txt = self._page_text(ds, i, cap=min(40000, max(4000, budget)))
            budget -= len(txt)
            if budget < 0:
                blocks.append(self._txt("… remaining spec pages omitted for length — raise an RFI if a section seems missing")); break
            label = f"spec page {i}" if i in getattr(self, "spec_pages", []) else f"{ds.pages[i].sheet_number} {ds.pages[i].sheet_title}"
            blocks.append(self._txt(f"--- {label} ---\n{txt}"))
        d = self._call("notes", blocks, "notes")
        self.grades = d.get("grades") or {}
        self.finish = d.get("finish") or {}
        for n in d.get("notes", []):
            t.notes.append(NoteLine(n.get("sheet", ""), n["text"]))
        for k in ("connection_design", "deck", "joists"):
            if d.get(k):
                t.notes.append(NoteLine("S001", f"{k.replace('_', ' ').title()}: {d[k]}"))
        self._draft(d.get("rfis"), "notes")
        for i in pages:
            self._mark_reviewed(t, i)
        return d

    def _calibrations(self, ds):
        """per-page grid calibration for plan pages; the richest one is the set default"""
        self.cal: dict[int, dict] = {}
        best = None
        for i, k in self.kinds.items():
            if k not in PLAN_KINDS:
                continue
            try:
                b = ds.grid_bubbles(i)
                c = ds.calibrate(b)
                if c and c.get("pt_per_ft"):
                    self.cal[i] = c
                    if best is None or len(c.get("x_ft", {})) + len(c.get("y_ft", {})) > len(best.get("x_ft", {})) + len(best.get("y_ft", {})):
                        best = c
            except Exception as ex:
                self.errors.append(f"calibration page {i}: {ex}")
        self.cal_default = best
        if best:
            self.say(f"  grid: {best.get('pt_per_ft', 0):.2f} pt/ft, X {list(best.get('x_ft', {}).keys())}, Y {list(best.get('y_ft', {}).keys())} ({best.get('method')})")
        else:
            self.say("  grid: no bubble calibration found — positions will come from the model's reading")

    def _cal_text(self, i) -> str:
        c = self.cal.get(i) or self.cal_default
        if not c:
            return "GRID CALIBRATION: none found on this page (no bubbles detected); read grids from the image and dimension strings."
        return ("GRID CALIBRATION (feet from the datum = first numbered grid / first lettered grid; +X along numbered grids, +Y north along lettered grids): "
                f"{c.get('pt_per_ft', 0):.3f} pt/ft, method {c.get('method')}; X grids {json.dumps(c.get('x_ft', {}))}; Y grids {json.dumps(c.get('y_ft', {}))}")

    def stage_columns(self, ds, t: Takeoff):
        pages = [i for i, k in self.kinds.items() if k in ("column_schedule", "foundation_plan")]
        if not pages:
            return None
        blocks = [self._txt(prompt("columns")), self._txt(self._cal_text(pages[0]))]
        for i in pages:
            pg = ds.pages[i]
            blocks.append(self._txt(f"--- {pg.sheet_number} {pg.sheet_title} (page {i}) ---"))
            blocks.append(self._img(ds, i, self.dpi))
            try:
                rep = ds.page_report(i, self.cal.get(i) or self.cal_default)
                syms = rep.get("column_symbols_ft") or rep.get("column_symbols") or []
                if syms:
                    blocks.append(self._txt(f"column symbol centres (grid feet) on {pg.sheet_number}: {json.dumps(syms)[:6000]}"))
            except Exception as ex:
                self.errors.append(f"page report {i}: {ex}")
            blocks.append(self._txt(f"page text:\n{self._page_text(ds, i, cap=20000)}"))
        d = self._call("columns", blocks, "columns")
        datum = d.get("datum", "")
        for c in d["columns"]:
            size = c["size"]; w = plf(size)
            h = c.get("height_ft")
            if h is None and c.get("tstl_ft") is not None and c.get("tftg_ft") is not None:
                h = c["tstl_ft"] - c["tftg_ft"]
            bp = c.get("base_plate", "")
            lvl = ""
            if c.get("tftg_ft") is not None and c.get("tstl_ft") is not None:
                lvl = f"T/FTG {ft_in(c['tftg_ft'])} → T/STL {ft_in(c['tstl_ft'])}"
            t.columns.append(ColumnRow(mark=c["mark"], size=size, qty=1, height_ft=h, lb_ft=w, base_plate=bp, bp_elev=lvl, anchors=c.get("anchors", ""),
                                       finish=c.get("finish", "Primed"), grade=c.get("grade") or self._grade_for(size), location=f"grid {c.get('grid', '')}",
                                       notes=c.get("notes", "") + ("" if w else " — WEIGHT NOT RESOLVED (size?)"), sheet=c.get("sheet", ""),
                                       rfi=list(c.get("rfi", [])), allowance=bool(c.get("allowance"))))
            if c.get("x_ft") is not None and c.get("y_ft") is not None and c.get("tftg_ft") is not None and c.get("tstl_ft") is not None:
                t.geometry.append(GeometryRow(MARK=c["mark"], TYPE="COLUMN", SIZE=size, X1=c["x_ft"], Y1=c["y_ft"], Z1=c["tftg_ft"], X2=c["x_ft"], Y2=c["y_ft"], Z2=c["tstl_ft"],
                                              GRADE=c.get("grade") or self._grade_for(size), FINISH=c.get("finish", "Primed"), SHEET=c.get("sheet", ""), GRID=c.get("grid", ""),
                                              LEVEL=lvl, ROT=c.get("rotation_deg", 0) or 0, CP=5, LB_FT=w, RFI=", ".join(c.get("rfi", []))))
                r = resolve(bp)
                if r and r["family"] == "PL" and plate_lbs(bp):
                    t.geometry.append(GeometryRow(MARK="BP", PIECE=c["mark"], TYPE="PLATE", SIZE=bp, X1=c["x_ft"], Y1=c["y_ft"], Z1=c["tftg_ft"],
                                                  GRADE=self._grade_for("PL"), FINISH=c.get("finish", "Primed"), SHEET=c.get("sheet", ""), GRID=c.get("grid", ""),
                                                  LEVEL=f"T/FTG {ft_in(c['tftg_ft'])}", ROT=c.get("rotation_deg", 0) or 0, CP=5))
        for b in d.get("base_plates", []):
            w = plate_lbs(b["size"]) or 0.0
            r = resolve(b["size"]); th = f'{r["dims"]["t"]:g}"' if r and r["family"] == "PL" and r["dims"].get("t") else ""
            t.misc_parts.append(PartRow("Base Plates", b["qty"], "PL", b["size"].upper().replace("PL", "").strip(), w, th, None, b.get("finish", "Primed"),
                                        b.get("grade") or self._grade_for("PL"), b.get("source", ""), b.get("mark", ""), list(b.get("rfi", []))))
        for pw in d.get("plate_washers", []):
            w = plate_lbs(pw["size"]) or 0.0
            t.misc_parts.append(PartRow("Plate Washers", pw["qty"], "PL", pw["size"].upper().replace("PL", "").strip(), w, "", None, pw.get("finish", "Galv"),
                                        self._grade_for("PL"), pw.get("source", ""), "PW", []))
        for a in d.get("anchor_groups", []):
            lb = anchor_rod_lbs(a["diameter"], a["length"])
            t.anchors.append(AnchorRow(a.get("group", "Column ABs"), a["location"], a["member"], a["diameter"], a["per_item"], a["item_qty"], a["length"], lb,
                                       a.get("finish") or self.finish.get("anchor_rods", "Galv"), a.get("grade") or self.grades.get("anchor_rods") or "F1554 Gr.55",
                                       a.get("notes", ""), list(a.get("rfi", [])), bool(a.get("allowance"))))
        if datum:
            t.assumptions.append(f"Datum: {datum}")
        self._draft(d.get("rfis"), "columns")
        for i in pages:
            self._mark_reviewed(t, i)
        return d

    def stage_framing(self, ds, t: Takeoff):
        pages = [i for i, k in self.kinds.items() if k in ("framing_plan", "elevation")]
        self.conn_counts: list[dict] = []
        for i in pages:
            pg = ds.pages[i]
            blocks = [self._txt(prompt("framing")), self._txt(self._cal_text(i)), self._txt(f"--- {pg.sheet_number} {pg.sheet_title} (page {i}) ---"), self._img(ds, i, self.dpi)]
            geo = []
            try:
                geo = ds.members(i, self.cal.get(i) or self.cal_default)
            except Exception as ex:
                self.errors.append(f"geometry pass {pg.sheet_number}: {ex}")
            if geo:
                blocks.append(self._txt("GEOMETRY PASS (label → matched line, grid feet, length):\n" + json.dumps(geo, default=float)[:60000]))
            else:
                blocks.append(self._txt("GEOMETRY PASS: none (raster page or no labelled lines) — read members from the image and dimension strings."))
            blocks.append(self._txt(f"page text:\n{self._page_text(ds, i, cap=30000)}"))
            d = self._call("framing", blocks, pg.sheet_number or f"p{i}")
            levels = {l["name"]: l["elev_ft"] for l in d.get("levels", [])}
            n0 = len(t.beams)
            for m in d["members"]:
                size = m["size"]; w = plf(size)
                L = m["length_ft"]
                if all(m.get(k) is not None for k in ("x1_ft", "y1_ft", "z1_ft", "x2_ft", "y2_ft", "z2_ft")):
                    Lg = ((m["x2_ft"] - m["x1_ft"]) ** 2 + (m["y2_ft"] - m["y1_ft"]) ** 2 + (m["z2_ft"] - m["z1_ft"]) ** 2) ** 0.5
                    if abs(Lg - L) > 0.05:
                        m["flag"] = (m.get("flag", "") + f" LENGTH {L:.3f} vs end points {Lg:.3f} ft").strip()
                mark = f"B{len(t.beams)+1}" if m.get("type", "BEAM") in ("BEAM", "GIRDER", "LINTEL") else f"{m.get('type','M')[:2]}{len(t.beams)+1}"
                note = m.get("note", "")
                ends = " / ".join(x for x in (m.get("end1", ""), m.get("end2", "")) if x)
                if ends:
                    note = (note + f" [{ends}]").strip()
                t.beams.append(BeamRow(sheet=pg.sheet_number or "", size=size, length_ft=L, lb_ft=w, tag=m.get("tag", "") or m.get("grid", ""), mark=mark,
                                       finish=m.get("finish") or self._finish_default(), grade=m.get("grade") or self._grade_for(size), level=m.get("level", ""),
                                       note=note, flag=(m.get("flag", "") + ("" if w else " WEIGHT NOT RESOLVED")).strip(), x_pt=m.get("x_pt"), y_pt=m.get("y_pt"),
                                       rfi=list(m.get("rfi", [])), allowance=bool(m.get("allowance"))))
                if all(m.get(k) is not None for k in ("x1_ft", "y1_ft", "z1_ft", "x2_ft", "y2_ft", "z2_ft")):
                    typ = m.get("type", "BEAM")
                    t.geometry.append(GeometryRow(MARK=mark, TYPE=typ, SIZE=size, X1=m["x1_ft"], Y1=m["y1_ft"], Z1=m["z1_ft"], X2=m["x2_ft"], Y2=m["y2_ft"], Z2=m["z2_ft"],
                                                  GRADE=m.get("grade") or self._grade_for(size), FINISH=m.get("finish") or self._finish_default(), SHEET=pg.sheet_number or "",
                                                  GRID=m.get("grid", ""), LEVEL=m.get("level", ""), CP=8 if typ in ("BEAM", "GIRDER", "LINTEL") else 5, LB_FT=w,
                                                  RFI=", ".join(m.get("rfi", [])), NOTES=m.get("flag", "")))
            for mm in d.get("memo", []):
                t.memo.append(MemoRow(pg.sheet_number or "", mm["item"], mm["qty"], mm["unit"], mm.get("lb_per_unit"), mm.get("length_ft"), mm.get("note", "")))
            for op in d.get("openings", []):
                t.notes.append(NoteLine(pg.sheet_number or "", f"Opening: {op['qty']} x {op['kind']} {op['size']} ({op.get('detail', 'detail?')}) {op.get('note', '')}".strip()))
            for c in d.get("connections", []):
                c = dict(c); c["sheet"] = pg.sheet_number; self.conn_counts.append(c)
            for n in d.get("sheet_notes", []):
                t.notes.append(NoteLine(pg.sheet_number or "", n["text"]))
            self._draft(d.get("rfis"), pg.sheet_number or "")
            self._mark_reviewed(t, i)
            self.say(f"    {pg.sheet_number}: {len(t.beams) - n0} members")

    def stage_details(self, ds, t: Takeoff):
        pages = [i for i, k in self.kinds.items() if k in DETAIL_KINDS]
        ctx = (f"CONTEXT FROM THE OTHER STAGES: {sum(c.qty for c in t.columns)} columns ({', '.join(sorted({c.size for c in t.columns}))}); "
               f"{len(t.beams)} beams ({', '.join(sorted({b.size for b in t.beams}))}); connection counts {json.dumps(getattr(self, 'conn_counts', []))[:3000]}; "
               f"kits so far: {[k.title for k in t.kits]}; finish rules {json.dumps(self.finish)}; grades {json.dumps(self.grades)}")
        skipped = 0
        for i in pages:
            pg = ds.pages[i]
            sheet = pg.sheet_number or f"p{i}"
            if any(s.page == i and s.steel == "N" for s in t.sheets):
                self._mark_reviewed(t, i); continue
            if self.kinds.get(i) not in ("sections_details", "schedules") and pg.text_chars > 200:
                try:
                    txt = " ".join(sp["text"] for sp in ds.page_text(i))
                except Exception:
                    txt = ""
                if txt and not STEEL_WORDS.search(txt):
                    for sh in t.sheets:
                        if sh.page == i:
                            sh.steel = "N"; sh.notes = (sh.notes + " — no steel words in the page text (local scan, no API call)").strip(" —")
                    self._mark_reviewed(t, i); skipped += 1; continue
            blocks = [self._txt(prompt("details")), self._txt(ctx), self._txt(f"--- {sheet} {pg.sheet_title} (page {i}) — full page then 4 tiles ---"), self._img(ds, i, self.dpi)]
            blocks += self._tiles(ds, i)
            blocks.append(self._txt(f"page text:\n{self._page_text(ds, i, cap=30000)}"))
            d = self._call("details", blocks, sheet)
            for k in d.get("kits", []):
                kit = Kit(letter="", title=k["title"], refs=k.get("refs", ""), no_steel=bool(k.get("no_steel")))
                for it in k.get("items", []):
                    w = it.get("lb_per_unit") or 0.0
                    if not w and not kit.no_steel:
                        w = unit_weight(it["size_spec"], it["unit"]) or 0.0
                    notes = it.get("notes", "")
                    if not w and not kit.no_steel:
                        notes = (notes + " WEIGHT NOT RESOLVED — enter LB PER UNIT").strip()
                    kit.items.append(DetailItem(it["detail_ref"], it["condition"], it["item"], it["size_spec"], it["unit_basis"], w, it.get("qty_applied"),
                                                it["unit"], it.get("qty_source", "") or ("NOT YET APPLIED" if it.get("qty_applied") is None and not kit.no_steel else ""),
                                                notes, it.get("finish") or self._finish_default(), it.get("grade") or self._grade_for(it["size_spec"]), list(it.get("rfi", []))))
                t.kits.append(kit)
            for b in d.get("bolts", []):
                cq = b.get("conn_qty")
                if cq is None:
                    cq = sum(c["count"] for c in getattr(self, "conn_counts", []) if c["group"] == b["group"]) or 0
                t.bolts.append(BoltRow(b["group"], b["connection_type"], b.get("location", sheet), b["spec"], b["per_conn"], cq, b.get("lb_ea") or bolt_lbs(b["spec"]),
                                       b.get("finish", "Plain"), b.get("notes", "") + ("" if b.get("conn_qty") is not None else " (count from framing stage)"),
                                       list(b.get("rfi", [])), bool(b.get("allowance"))))
            for p in d.get("misc_parts", []):
                t.misc_parts.append(self._part(p, sheet))
            for p in d.get("misc_metals", []):
                t.misc_metals.append(self._part(p, sheet))
            for n in d.get("sheet_notes", []):
                t.notes.append(NoteLine(sheet, n["text"]))
            self._draft(d.get("rfis"), sheet)
            self._mark_reviewed(t, i)
        if skipped:
            self.say(f"    {skipped} arch / MEP / civil page(s) skipped — no steel words in their text")
        # letter the kits: steel kits A, B, … ; no-steel kits collapse into one closing kit Z
        steel = [k for k in t.kits if not k.no_steel]; nos = [k for k in t.kits if k.no_steel]
        for n, k in enumerate(steel):
            k.letter = chr(ord("A") + n) if n < 25 else f"K{n+1}"
        if nos:
            z = Kit("Z", "DETAILS REVIEWED — NO NEW STEEL", "; ".join(k.refs for k in nos if k.refs), [], True)
            for k in nos:
                z.items.extend(k.items)
            t.kits = steel + [z]
        else:
            t.kits = steel

    def _part(self, p: dict, sheet: str) -> PartRow:
        lb = p.get("lb_ea") or 0.0
        if not lb:
            lb = plate_lbs(f"PL {p['size']}" if p.get("shape", "").upper() == "PL" and not p["size"].upper().startswith("PL") else p["size"]) or 0.0
            if not lb and p.get("length_ft") and plf(p["size"]):
                lb = round(plf(p["size"]) * p["length_ft"], 2)
        return PartRow(p["group"], p["qty"], p["shape"], p["size"], lb, p.get("thickness", ""), p.get("length_ft"), p.get("finish") or self._finish_default(),
                       p.get("grade") or self._grade_for(p["size"]), p.get("source", sheet), p.get("mark", ""), list(p.get("rfi", [])), bool(p.get("allowance")))

    def stage_synthesis(self, ds, t: Takeoff):
        compact = t.to_dict()
        compact.pop("extraction_log", None); compact.pop("geometry", None)
        compact["totals"] = t.totals(); compact["finish_totals"] = t.finish_totals()
        compact["rfi_drafts"] = list(self.rfi_drafts.values())
        blocks = [self._txt(prompt("synthesis")), self._txt(json.dumps(compact, default=float)[:180000])]
        d = self._call("synthesis", blocks, "synthesis")
        keymap = {}
        t.rfis = []
        for r in d["rfis"]:
            t.rfis.append(RFIItem(r["code"], r["priority"], r["to"], r["subject"], r["question"], r.get("carried", ""), r.get("status", "OPEN"),
                                  0.0, r.get("where_flagged", ""), r.get("exposure_lbs", 0.0) or 0.0))
            if r.get("key"):
                keymap[r["key"]] = r["code"]
        # draft keys on the rows → codes
        def remap(lst):
            return sorted({keymap.get(x, x) for x in lst})
        for coll in (t.columns, t.beams, t.anchors, t.bolts, t.misc_parts, t.misc_metals):
            for row in coll:
                row.rfi = remap(row.rfi)
        for k in t.kits:
            for it in k.items:
                it.rfi = remap(it.rfi)
        for g in t.geometry:
            g.RFI = ", ".join(remap([x.strip() for x in g.RFI.split(",") if x.strip()]))
        # lbs flagged per RFI
        for r in t.rfis:
            r.lbs_flagged = (sum(c.lbs for c in t.columns if r.code in c.rfi) + sum(b.lbs for b in t.beams if r.code in b.rfi) + sum(a.lbs for a in t.anchors if r.code in a.rfi)
                             + sum(b.lbs for b in t.bolts if r.code in b.rfi) + sum(p.lbs for p in t.misc_parts if r.code in p.rfi)
                             + sum(i.lbs for k in t.kits for i in k.items if r.code in i.rfi))
        t.inclusions = d.get("inclusions", []); t.exclusions = d.get("exclusions", [])
        t.assumptions = t.assumptions + d.get("assumptions", [])
        t.galv_unquantified = d.get("galv_unquantified", [])
        t.header.scope_summary = d.get("scope_summary", "")
        sc = d["scope"]
        t.scope = Scope(sc.get("inclusions", []), sc.get("exclusions", []), sc.get("clarifications", []),
                        [ScopeItem(q["item"], str(q["quantity"]), q.get("unit") or "each") for q in sc.get("quantities", [])],
                        sc.get("tonnage_statement", ""), True)
        if not t.revisions:
            t.revisions.append(Revision(t.header.rev, t.header.date, f"Initial takeoff from {t.header.set_description or 'the drawing set'}", None, t.totals()["project"]))

    # ------------------------------------------------------------------ helpers
    def _grade_for(self, size: str) -> str:
        s = (size or "").upper().replace(" ", "")
        g = getattr(self, "grades", {}) or {}
        if s.startswith("HSS"):
            return g.get("HSS") or "A500 Gr.C"
        if s.startswith("PIPE") or "SCH" in s:
            return g.get("pipe") or "A53 Gr.B"
        if s.startswith("PL"):
            return g.get("plates") or "A572 Gr.50"
        if s.startswith("L"):
            return g.get("angles") or "A572 Gr.50"
        if s.startswith("C") or s.startswith("MC"):
            return g.get("channels") or "A36"
        return g.get("W") or "A992"

    def _finish_default(self) -> str:
        return (getattr(self, "finish", {}) or {}).get("interior") or "Primed"

    def _mark_reviewed(self, t: Takeoff, page: int):
        for s in t.sheets:
            if s.page == page:
                s.reviewed = True


def anchor_rod_lbs(diameter: str, length: str) -> float:
    """rod weight ≈ steel bar: 2.67 lb/ft per in² × area; plus ~25 % for nuts/washers"""
    d = parse_dia(diameter)
    L = parse_ft_in(length) or 0.0
    if not d:
        return 0.0
    area = 3.14159 * (d / 2) ** 2
    return round(area * 3.4 * L * 1.25, 2)      # 3.4 lb/ft per in² of steel; +25 % nuts / washers


def bolt_lbs(spec: str) -> float:
    d = parse_dia(spec) or 0.75
    L = 2.5
    m = re.search(r"x\s*(\d+(?:\s?\d/\d)?)\"", spec)
    if m:
        try:
            L = float(sum(float(x) if "/" not in x else float(x.split("/")[0]) / float(x.split("/")[1]) for x in m.group(1).split()))
        except Exception:
            pass
    area = 3.14159 * (d / 2) ** 2
    return round(area * 0.2836 * L + 0.6 * d ** 3 * 1.6, 2)       # shank + nut/washer allowance


def parse_dia(s: str) -> float | None:
    m = re.search(r"(\d+\s\d+/\d+|\d+/\d+|\d+\.\d+|\d+)\s*\"?", s or "")
    if not m:
        return None
    txt = m.group(1)
    try:
        if " " in txt:
            a, b = txt.split(); return float(a) + float(b.split("/")[0]) / float(b.split("/")[1])
        if "/" in txt:
            return float(txt.split("/")[0]) / float(txt.split("/")[1])
        return float(txt)
    except Exception:
        return None


# ----------------------------------------------------------------------------- entry point
def run_takeoff(pdf_paths: list[str], header: Header, provider, out_dir: str, progress=None, stem: str | None = None,
                dpi: int = 100, job_notes: str = "", stages: tuple = ("index", "notes", "columns", "framing", "details", "synthesis")) -> RunResult:
    from .pdfset import DrawingSet
    say = progress or (lambda *_: None)
    eng = Engine(provider, out_dir, progress, dpi=dpi, job_notes=job_notes)
    t = Takeoff(header=header)
    t.header.source_files = [os.path.basename(p) for p in pdf_paths]
    stem = stem or header.job_code or "JOB"
    jpath = os.path.join(out_dir, f"{stem}_takeoff.json")
    res = RunResult(takeoff=t, takeoff_json=jpath, log=eng.log, errors=eng.errors)
    say(f"opening {len(pdf_paths)} file(s) …")
    ds = DrawingSet(pdf_paths)
    say(f"{len(ds.pages)} pages")
    try:
        for stage in stages:
            say(f"stage {stage} …")
            if stage == "index":
                eng.stage_index(ds, t)
                eng._calibrations(ds)
            elif stage == "notes":
                eng.stage_notes(ds, t)
            elif stage == "columns":
                eng.stage_columns(ds, t)
            elif stage == "framing":
                eng.stage_framing(ds, t)
            elif stage == "details":
                eng.stage_details(ds, t)
            elif stage == "synthesis":
                eng.stage_synthesis(ds, t)
            eng._save(t, jpath)
    except Exception as ex:
        eng.errors.append(f"{type(ex).__name__}: {ex}\n{traceback.format_exc()}")
        eng._save(t, jpath)
        say("ERROR " + str(ex))
    tot = t.totals()
    say(f"takeoff: {tot['pieces']['columns']} columns, {tot['pieces']['beams']} beams, {tot['project']:,.0f} lb = {tot['tons']:.2f} T; "
        f"{len(t.rfis)} RFIs; API cost ≈ ${res.cost:.2f} ({res.tokens[0]:,} in / {res.tokens[1]:,} out tokens)")
    return res
