"""
pipeline — one call that does what the UI and the CLI both need.

    res = run(job=<dict or path>, geometry=<csv path | xlsx path | list[dict]>, out_dir=None, stem=None,
              strict=True, write_tab=False, progress=print)

Writes into out_dir (default: next to the geometry file):
    <stem>_Model.ifc, <stem>_Model_manifest.csv, <stem>_Model_views.png, <stem>_Model_check.txt,
    <stem>_ModelGeometry.csv (when the input was a workbook), and with write_tab=True a copy of the workbook
    carrying the Model Geometry tab (<stem>_Takeoff+Model.xlsx) — the original workbook is never modified.

Returns a RunResult: paths, build totals, check result, problems, elapsed.
"""
from __future__ import annotations
import csv, os, time
from dataclasses import dataclass, field
from .jobfile import load_job, validate_job
from .build_ifc import build
from .check_ifc import check, CheckResult
from .geometry_tab import read_model_geometry_tab, add_model_geometry_tab

GEOM_COLUMNS = ["MARK", "PIECE", "TYPE", "SIZE", "GRADE", "FINISH", "SHEET", "GRID", "LEVEL",
                "X1", "Y1", "Z1", "X2", "Y2", "Z2", "ROT", "CP", "LB_FT", "LBS", "RFI", "NOTES"]


@dataclass
class RunResult:
    ok: bool = False
    ifc: str | None = None
    manifest: str | None = None
    png: str | None = None
    check_txt: str | None = None
    geometry_csv: str | None = None
    workbook_out: str | None = None
    out_dir: str | None = None
    pieces: int = 0
    totals: dict = field(default_factory=dict)      # class -> [n, lbs]
    storeys: list = field(default_factory=list)
    build_problems: list = field(default_factory=list)
    job_problems: list = field(default_factory=list)
    check: CheckResult | None = None
    error: str | None = None
    elapsed: float = 0.0

    @property
    def grand_lbs(self) -> float:
        return sum(v[1] for v in self.totals.values())

    def summary(self) -> str:
        if self.error:
            return "ERROR: " + self.error
        s = [f"{self.pieces} pieces, {self.grand_lbs:,.0f} lb = {self.grand_lbs/2000:.2f} T modelled"]
        for cls, (n, lbs) in self.totals.items():
            if n:
                s.append(f"  {cls[3:]:7s} {n:4d} pcs {lbs:10,.0f} lb")
        if self.check:
            s.append("check: " + ("PASS" if self.check.ok else f"FAIL ({len(self.check.fails)})"))
        if self.build_problems:
            s.append(f"skipped rows: {len(self.build_problems)}")
        return "\n".join(s)


def load_geometry(src) -> tuple[list[dict], str | None]:
    """csv path | xlsx path | list[dict]  ->  (rows, source_path_or_None)"""
    if isinstance(src, list):
        return src, None
    p = str(src)
    ext = os.path.splitext(p)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        return read_model_geometry_tab(p), p
    with open(p, newline="", encoding="utf-8-sig") as fh:
        rows = [r for r in csv.DictReader(fh) if any((str(v) if v is not None else "").strip() for v in r.values())]
    return rows, p


def write_geometry_csv(rows: list[dict], path: str) -> str:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=GEOM_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in GEOM_COLUMNS})
    return path


def run(job, geometry, out_dir: str | None = None, stem: str | None = None, strict: bool = True,
        write_tab: bool = False, progress=None) -> RunResult:
    t0 = time.time()
    say = progress or (lambda *_: None)
    res = RunResult()
    try:
        job_d = load_job(job) if isinstance(job, str) else dict(job)
        res.job_problems = validate_job(job_d)
        if res.job_problems:
            res.error = "job file: " + "; ".join(res.job_problems); return res
        rows, src = load_geometry(geometry)
        if not rows:
            res.error = "no geometry rows found"; return res
        if out_dir is None:
            out_dir = os.path.dirname(os.path.abspath(src)) if src else os.getcwd()
        os.makedirs(out_dir, exist_ok=True)
        res.out_dir = out_dir
        if stem is None:
            if src:
                base = os.path.splitext(os.path.basename(src))[0]
                for suffix in ("_ModelGeometry", "_Takeoff+Model", "_Takeoff", "_Model"):
                    if base.endswith(suffix):
                        base = base[: -len(suffix)]
                stem = base
            else:
                stem = job_d["job_code"]
        if src and src.lower().endswith((".xlsx", ".xlsm")):
            res.geometry_csv = write_geometry_csv(rows, os.path.join(out_dir, f"{stem}_ModelGeometry.csv"))
            say(f"read {len(rows)} rows from the Model Geometry tab → {os.path.basename(res.geometry_csv)}")
        else:
            res.geometry_csv = src
            say(f"read {len(rows)} geometry rows")

        ifc_path = os.path.join(out_dir, f"{stem}_Model.ifc")
        say("building IFC …")
        b = build(job_d, rows, ifc_path, strict=strict)
        res.ifc, res.manifest = b["ifc"], b["manifest"]
        res.pieces, res.totals, res.storeys, res.build_problems = b["pieces"], b["totals"], b["storeys"], b["problems"]
        say(f"wrote {os.path.basename(ifc_path)} — {res.pieces} pieces, {res.grand_lbs/2000:.2f} T")

        say("checking …")
        res.check = check(ifc_path, rows, os.path.join(out_dir, f"{stem}_Model_views.png"))
        res.png = res.check.png
        res.check_txt = os.path.join(out_dir, f"{stem}_Model_check.txt")
        with open(res.check_txt, "w", encoding="utf-8") as fh:
            fh.write(res.check.report + "\n")
        say("check: " + ("PASS" if res.check.ok else f"FAIL ({len(res.check.fails)})"))

        if write_tab:
            import openpyxl
            if src and src.lower().endswith((".xlsx", ".xlsm")):
                wb = openpyxl.load_workbook(src)
                if "Model Geometry" in wb.sheetnames:
                    del wb["Model Geometry"]
            else:
                wb = openpyxl.Workbook(); wb.remove(wb.active)
            add_model_geometry_tab(wb, job_d, rows, status=job_d.get("rev", "IN PROGRESS"))
            res.workbook_out = os.path.join(out_dir, f"{stem}_Takeoff+Model.xlsx" if src and src.lower().endswith((".xlsx", ".xlsm"))
                                            else f"{stem}_ModelGeometry.xlsx")
            wb.save(res.workbook_out)
            say(f"wrote {os.path.basename(res.workbook_out)} (Model Geometry tab)")
        res.ok = res.check.ok and not res.build_problems
    except SystemExit as ex:         # build() raises SystemExit on strict geometry problems
        res.error = str(ex)
    except Exception as ex:          # pragma: no cover
        import traceback
        res.error = f"{type(ex).__name__}: {ex}\n" + traceback.format_exc()
    res.elapsed = time.time() - t0
    return res


def geometry_template_rows() -> list[dict]:
    """three example rows that show the conventions (a column, a beam, a base plate)"""
    return [
        {"MARK": "C1", "PIECE": "1", "TYPE": "COLUMN", "SIZE": "W8x31", "GRADE": "A992", "FINISH": "Primed", "SHEET": "S101",
         "GRID": "1/A", "LEVEL": "T/FTG -2'-0\" to T/STL 14'-0\"", "X1": 0, "Y1": 0, "Z1": -2, "X2": 0, "Y2": 0, "Z2": 14,
         "ROT": 0, "CP": 5, "LB_FT": 31, "LBS": "", "RFI": "", "NOTES": "example row — delete"},
        {"MARK": "B1", "PIECE": "1", "TYPE": "BEAM", "SIZE": "W12x26", "GRADE": "A992", "FINISH": "Primed", "SHEET": "S102",
         "GRID": "A/1-2", "LEVEL": "T/STL 14'-0\"", "X1": 0, "Y1": 0, "Z1": 14, "X2": 25, "Y2": 0, "Z2": 14,
         "ROT": 0, "CP": 8, "LB_FT": 26, "LBS": "", "RFI": "", "NOTES": "example row — delete"},
        {"MARK": "BP1", "PIECE": "C1-1", "TYPE": "PLATE", "SIZE": "PL 3/4x12x12", "GRADE": "A572 Gr.50", "FINISH": "Primed",
         "SHEET": "S501", "GRID": "1/A", "LEVEL": "T/FTG -2'-0\"", "X1": 0, "Y1": 0, "Z1": -2, "X2": "", "Y2": "", "Z2": "",
         "ROT": 0, "CP": 5, "LB_FT": "", "LBS": "", "RFI": "", "NOTES": "example row — delete"},
    ]
