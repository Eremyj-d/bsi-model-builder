"""
Deliverables from a Takeoff: the 12-tab workbook, the RFI log (+ INTERNAL), the scope letter, the notes, the
job file + Model Geometry CSV, and the IFC model (through core.pipeline).

    paths = build_deliverables(takeoff, out_dir, stem, what=("workbook", "docs", "model"))

Review-in-Excel round trip: after the estimator edits the draft workbook, `build_from_workbook(xlsx, takeoff_json,
out_dir)` re-reads the Model Geometry tab (the only tab the IFC needs) and rebuilds the model + docs from the
takeoff JSON — the edited workbook itself is the takeoff of record and is never regenerated over.
"""
from __future__ import annotations
import csv, dataclasses, json, os
from .model import Takeoff, ft_in
from ..core.jobfile import new_job, save_job, validate_job
from ..core.pipeline import run as run_model, write_geometry_csv, GEOM_COLUMNS


def job_dict_from_takeoff(t: Takeoff) -> dict:
    h = t.header
    job = new_job(h.job, h.job_code, h.rev, h.set_description or ", ".join(h.source_files))
    job["building"] = h.building
    job["date"] = h.date
    datum = next((a for a in t.assumptions if a.lower().startswith("datum:")), "")
    if datum:
        job["datum"]["description"] = datum[6:].strip() + " +X along the numbered grids, +Y along the lettered grids, +Z up; decimal feet."
    # storeys from the distinct beam T/STL values (both ends), plus the column base levels
    levels = {}
    for g in t.geometry:
        if g.TYPE in ("BEAM", "GIRDER", "LINTEL"):
            for z in (g.Z1, g.Z2):
                if z is not None:
                    levels.setdefault(round(z, 3), f"T/STL {ft_in(z)}")
        elif g.TYPE in ("COLUMN", "POST"):
            levels.setdefault(round(g.Z1, 3), f"BASE {ft_in(g.Z1)}")
    job["storeys"] = [{"name": n, "elev_ft": e} for e, n in sorted(levels.items())]
    return job


def geometry_rows(t: Takeoff) -> list[dict]:
    rows = []
    for g in t.geometry:
        d = dataclasses.asdict(g)
        rows.append({k: ("" if d.get(k) is None else d.get(k)) for k in GEOM_COLUMNS})
    return rows


def build_deliverables(t: Takeoff, out_dir: str, stem: str | None = None, what=("workbook", "docs", "model"), progress=None) -> dict:
    say = progress or (lambda *_: None)
    os.makedirs(out_dir, exist_ok=True)
    stem = stem or t.header.job_code or "JOB"
    paths = {"takeoff_json": t.to_json(os.path.join(out_dir, f"{stem}_takeoff.json"))}
    if "workbook" in what:
        from .workbook import build_workbook
        paths["workbook"] = build_workbook(t, os.path.join(out_dir, f"{stem}_Takeoff.xlsx"))
        say(f"wrote {os.path.basename(paths['workbook'])}")
    if "docs" in what:
        from .docs import build_all_docs
        paths.update(build_all_docs(t, out_dir, stem))
        say("wrote RFI log (+ INTERNAL), scope letter, takeoff notes")
    if "model" in what:
        job = job_dict_from_takeoff(t)
        probs = validate_job(job)
        if probs:
            say("job file problems: " + "; ".join(probs))
        jpath = os.path.join(out_dir, f"{stem}_job.json"); save_job(job, jpath)
        paths["job"] = jpath
        rows = geometry_rows(t)
        if rows:
            gcsv = write_geometry_csv(rows, os.path.join(out_dir, f"{stem}_ModelGeometry.csv"))
            paths["geometry_csv"] = gcsv
            res = run_model(jpath, gcsv, out_dir=out_dir, stem=stem, strict=False, write_tab=False, progress=say)
            paths["ifc"] = res.ifc; paths["ifc_check"] = res.check_txt; paths["ifc_views"] = res.png; paths["ifc_ok"] = res.ok
            if res.error:
                say("model: " + res.error.splitlines()[0])
        else:
            say("model: no geometry rows (no positions were read) — IFC skipped")
    return paths


def build_from_workbook(xlsx: str, takeoff_json: str, out_dir: str, stem: str | None = None, progress=None) -> dict:
    """Review-in-Excel: the edited workbook's Model Geometry tab drives the IFC; docs come from the takeoff JSON."""
    from ..core.geometry_tab import read_model_geometry_tab
    say = progress or (lambda *_: None)
    t = Takeoff.from_json(takeoff_json)
    stem = stem or t.header.job_code or os.path.splitext(os.path.basename(xlsx))[0].replace("_Takeoff", "")
    paths = {}
    from .docs import build_all_docs
    paths.update(build_all_docs(t, out_dir, stem))
    say("wrote RFI log (+ INTERNAL), scope letter, takeoff notes from the takeoff JSON")
    try:
        rows = read_model_geometry_tab(xlsx)
    except Exception as ex:
        say(f"Model Geometry tab not read ({ex}) — IFC skipped"); return paths
    job = job_dict_from_takeoff(t)
    jpath = os.path.join(out_dir, f"{stem}_job.json"); save_job(job, jpath); paths["job"] = jpath
    res = run_model(jpath, rows, out_dir=out_dir, stem=stem, strict=False, write_tab=False, progress=say)
    paths["ifc"] = res.ifc; paths["ifc_check"] = res.check_txt; paths["ifc_views"] = res.png; paths["ifc_ok"] = res.ok
    return paths
