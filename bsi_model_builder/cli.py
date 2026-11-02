"""
BSI Model Builder command line.

  BSI_Model_Builder build  --job JOB.json  (--geom GEOM.csv | --xlsx TAKEOFF.xlsx) [--out DIR] [--stem NAME] [--tab] [--lenient]
  BSI_Model_Builder check  MODEL.ifc [--geom GEOM.csv]
  BSI_Model_Builder template [--out DIR] [--name "Job name"]     # job.json + Model Geometry workbook to fill in
  BSI_Model_Builder selftest                                      # builds + checks the bundled synthetic frame
  BSI_Model_Builder --version
"""
from __future__ import annotations
import argparse, os, sys, tempfile
from . import __version__, __app_name__


def _utf8_console():
    """Windows consoles default to cp1252; make stdout/stderr UTF-8 (unencodable chars become '?')."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _progress(msg: str):
    print(msg, flush=True)


def cmd_build(a) -> int:
    from .core.pipeline import run
    geometry = a.xlsx or a.geom
    res = run(a.job, geometry, out_dir=a.out, stem=a.stem, strict=not a.lenient, write_tab=a.tab, progress=_progress)
    print(res.summary())
    if res.build_problems:
        for p in res.build_problems:
            print("  skipped:", p)
    if res.check:
        for x in res.check.fails:
            print("  FAIL", x)
    if res.error:
        print(res.error)
    return 0 if res.ok else 1


def cmd_check(a) -> int:
    from .core.check_ifc import check
    from .core.pipeline import load_geometry
    rows = load_geometry(a.geom)[0] if a.geom else None
    r = check(a.ifc, rows, a.png)
    print(r.report)
    return 0 if r.ok else 1


def cmd_template(a) -> int:
    import openpyxl
    from .core.jobfile import new_job, save_job
    from .core.geometry_tab import add_model_geometry_tab
    from .core.pipeline import geometry_template_rows, write_geometry_csv
    out = a.out or os.getcwd()
    os.makedirs(out, exist_ok=True)
    job = new_job(a.name or "New job", source="type the workbook / drawing set here")
    stem = job["job_code"]
    save_job(job, os.path.join(out, f"{stem}_job.json"))
    wb = openpyxl.Workbook(); wb.remove(wb.active)
    add_model_geometry_tab(wb, job, geometry_template_rows(), status="TEMPLATE")
    wb.save(os.path.join(out, f"{stem}_ModelGeometry.xlsx"))
    write_geometry_csv(geometry_template_rows(), os.path.join(out, f"{stem}_ModelGeometry.csv"))
    print(f"wrote {stem}_job.json, {stem}_ModelGeometry.xlsx and {stem}_ModelGeometry.csv in {out}")
    return 0


def cmd_takeoff(a) -> int:
    """takeoff run --job NAME --code CODE --out DIR PDF [PDF …]   |   takeoff docs --xlsx EDITED.xlsx --json X_takeoff.json"""
    from .takeoff.model import Header
    if a.sub == "run":
        from .takeoff.engine import run_takeoff
        from .takeoff.outputs import build_deliverables
        if a.mock:
            from .takeoff.providers import MockProvider
            provider = MockProvider(a.mock)
        else:
            from .takeoff.credentials import get_api_key
            from .takeoff.providers import AnthropicProvider, DEFAULT_MODEL
            key = a.api_key or get_api_key()
            if not key:
                print("no API key: set one in the app, pass --api-key, or set ANTHROPIC_API_KEY"); return 2
            provider = AnthropicProvider(key, model=a.model or DEFAULT_MODEL, cache_dir=os.path.join(a.out, ".api_cache"))
        from .core.jobfile import code_from_name
        h = Header(job=a.job, job_code=a.code or code_from_name(a.job), rev=a.rev or "REV 0", building=a.building or "")
        res = run_takeoff(a.pdfs, h, provider, a.out, progress=_progress, job_notes=a.notes or "")
        for e in res.errors:
            print("WARN", e.splitlines()[0])
        paths = build_deliverables(res.takeoff, a.out, h.job_code, progress=_progress)
        for k, v in paths.items():
            if isinstance(v, str):
                print(f"  {k:14s} {v}")
        print(f"API cost ≈ ${res.cost:.2f}")
        return 0 if not res.errors else 1
    if a.sub == "docs":
        from .takeoff.outputs import build_from_workbook
        paths = build_from_workbook(a.xlsx, a.json, a.out or os.path.dirname(a.xlsx), progress=_progress)
        for k, v in paths.items():
            if isinstance(v, str):
                print(f"  {k:14s} {v}")
        return 0
    if a.sub == "deliver":
        from .takeoff.model import Takeoff
        from .takeoff.outputs import build_deliverables
        t = Takeoff.from_json(a.json)
        paths = build_deliverables(t, a.out or os.path.dirname(a.json), progress=_progress)
        for k, v in paths.items():
            if isinstance(v, str):
                print(f"  {k:14s} {v}")
        return 0
    return 2


def cmd_selftest(a) -> int:
    from .core.pipeline import run
    from .selftest import sample_paths
    job, geom = sample_paths()
    out = a.out or tempfile.mkdtemp(prefix="bsi_selftest_")
    res = run(job, geom, out_dir=out, stem="SELFTEST", write_tab=True, progress=_progress)
    print(res.summary())
    if res.error:
        print(res.error)
    ok = res.ok and res.pieces == 23 and abs(res.grand_lbs - 15281) < 2
    print("SELFTEST", "PASS" if ok else "FAIL", "→", out)
    return 0 if ok else 1


def main(argv=None) -> int:
    _utf8_console()
    ap = argparse.ArgumentParser(prog="BSI_Model_Builder", description=f"{__app_name__} {__version__}")
    ap.add_argument("--version", action="version", version=f"{__app_name__} {__version__}")
    sub = ap.add_subparsers(dest="cmd")
    b = sub.add_parser("build", help="geometry table → IFC + check + views")
    b.add_argument("--job", required=True); g = b.add_mutually_exclusive_group(required=True)
    g.add_argument("--geom", help="Model Geometry CSV"); g.add_argument("--xlsx", help="takeoff workbook with a Model Geometry tab")
    b.add_argument("--out"); b.add_argument("--stem"); b.add_argument("--tab", action="store_true", help="also write the workbook copy with the Model Geometry tab")
    b.add_argument("--lenient", action="store_true", help="skip bad rows instead of stopping")
    b.set_defaults(fn=cmd_build)
    c = sub.add_parser("check", help="re-check an IFC"); c.add_argument("ifc"); c.add_argument("--geom"); c.add_argument("--png")
    c.set_defaults(fn=cmd_check)
    t = sub.add_parser("template", help="write a job.json + Model Geometry template"); t.add_argument("--out"); t.add_argument("--name")
    t.set_defaults(fn=cmd_template)
    s = sub.add_parser("selftest", help="build + check the bundled synthetic frame"); s.add_argument("--out")
    s.set_defaults(fn=cmd_selftest)
    tk = sub.add_parser("takeoff", help="drawings → workbook + docs + model (Claude API)")
    tks = tk.add_subparsers(dest="sub")
    r = tks.add_parser("run"); r.add_argument("pdfs", nargs="+"); r.add_argument("--job", required=True); r.add_argument("--code"); r.add_argument("--building")
    r.add_argument("--rev"); r.add_argument("--out", required=True); r.add_argument("--model"); r.add_argument("--api-key"); r.add_argument("--notes")
    r.add_argument("--mock", help="replay canned responses from this folder instead of calling the API (tests)")
    dd = tks.add_parser("docs", help="rebuild docs + model from an edited workbook"); dd.add_argument("--xlsx", required=True); dd.add_argument("--json", required=True); dd.add_argument("--out")
    dl = tks.add_parser("deliver", help="rebuild everything from a takeoff JSON"); dl.add_argument("--json", required=True); dl.add_argument("--out")
    tk.set_defaults(fn=cmd_takeoff)
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help(); return 0
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
