"""
jobfile — the job.json that goes with every model.

    job = load_job(path)              # dict, validated + defaults filled
    save_job(job, path)
    job = new_job("Job name", "CODE") # template with the standard datum text
    problems = validate_job(job)      # list[str]; empty = OK

Fields
  job          project name as it reads on the workbook header
  job_code     short code that seeds every GUID (uuid5 of job_code|mark|piece) — keep it constant across revisions
  building     optional building designation
  rev          takeoff revision the model was built from
  date         ISO date
  source       workbook file name / drawing set the geometry came from
  datum.description   where 0,0,0 is and which way +X / +Y point (goes on the Model Geometry tab and into the IFC)
  grids.X / grids.Y   {tag: decimal feet} — numbered grids along +X, lettered grids along +Y (pseudo-grids OK)
  storeys      [{name, elev_ft}] — real levels; if empty they are derived from the beam T/STL values
"""
from __future__ import annotations
import datetime, json, re

DEFAULT_DATUM = ("Origin = first numbered grid / first lettered grid at T/SLAB 0'-0\". "
                 "+X along the numbered grids, +Y along the lettered grids, +Z up. "
                 "Decimal feet in the geometry table; millimetres in the IFC.")


def new_job(name: str = "", code: str = "", rev: str = "REV 0", source: str = "") -> dict:
    return {
        "job": name, "job_code": code or code_from_name(name), "building": "", "rev": rev,
        "date": datetime.date.today().isoformat(), "source": source,
        "datum": {"description": DEFAULT_DATUM},
        "grids": {"X": {}, "Y": {}},
        "storeys": [],
    }


def code_from_name(name: str) -> str:
    """'Newport News Seafood Market' -> NNSM, 'Phoenix Bristol' -> PHOENIBRIS, 'Mirada' -> MIRADA"""
    words = [w for w in re.findall(r"[A-Za-z0-9]+", name or "") if w.lower() not in ("the", "of", "and", "at", "a", "an", "for")]
    if not words:
        return "JOB"
    if len(words) >= 3:
        code = "".join(w[0] for w in words)
    elif len(words) == 2:
        code = words[0][:6] + words[1][:4]
    else:
        code = words[0][:10]
    return code.upper()[:12]


def validate_job(job: dict) -> list[str]:
    p = []
    if not str(job.get("job", "")).strip():
        p.append("job name is blank")
    code = str(job.get("job_code", "")).strip()
    if not code:
        p.append("job_code is blank")
    elif not re.fullmatch(r"[A-Za-z0-9_\-]{2,24}", code):
        p.append("job_code must be 2–24 letters / digits (no spaces)")
    for axis in ("X", "Y"):
        for tag, v in (job.get("grids", {}).get(axis, {}) or {}).items():
            try:
                float(v)
            except Exception:
                p.append(f"grid {axis} '{tag}' is not a number: {v!r}")
    seen = set()
    for s in job.get("storeys", []) or []:
        try:
            e = round(float(s.get("elev_ft")), 3)
        except Exception:
            p.append(f"storey {s.get('name')!r} has no numeric elev_ft"); continue
        if e in seen:
            p.append(f"two storeys at {e} ft")
        seen.add(e)
        if not str(s.get("name", "")).strip():
            p.append(f"storey at {e} ft has no name")
    return p


def load_job(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        job = json.load(fh)
    base = new_job()
    for k, v in base.items():
        job.setdefault(k, v)
    job.setdefault("datum", {}).setdefault("description", DEFAULT_DATUM)
    job.setdefault("grids", {}); job["grids"].setdefault("X", {}); job["grids"].setdefault("Y", {})
    job.setdefault("storeys", [])
    return job


def save_job(job: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(job, fh, indent=1, ensure_ascii=False)
