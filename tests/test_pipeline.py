import csv, json, os
import pytest
from bsi_model_builder.core import run, resolve, new_job, validate_job
from bsi_model_builder.core.check_ifc import check
from bsi_model_builder.core.pipeline import load_geometry, write_geometry_csv
from bsi_model_builder.selftest import sample_paths

DATA = os.path.join(os.path.dirname(__file__), "data")


def test_profiles_resolve():
    cases = {"W14x38": ("W", "W14X38", 38.0), "HSS5x5x5/16": ("HSS_RECT", "HSS5X5X5/16", 19.08),
             "HSS9.625x.500": ("HSS_ROUND", "HSS9.625X0.500", 48.77), "L6x6x5/16": ("L", "L6X6X5/16", 12.4),
             "C12x20.7": ("C", "C12X20.7", 20.7), "PIPE 8 SCH 40": ("PIPE", "PIPE8STD", 28.6),
             "WT5x11": ("WT", "WT5X11", 11.0), "PL 3/4x18x1'-6\"": ("PL", None, None)}
    for s, (fam, label, plf) in cases.items():
        r = resolve(s)
        assert r and r["family"] == fam, s
        if label:
            assert r["label"] == label and abs(r["plf"] - plf) < 0.01, s
    assert resolve("W99x999") is None
    assert resolve("PL 3/4x18x1'-6\"")["dims"] == {"t": 0.75, "w": 18.0, "l": 18.0}


def test_job_validation():
    j = new_job("Test Job")
    assert j["job_code"] == "TESTJOB" and validate_job(j) == []
    j["job_code"] = "bad code"
    assert validate_job(j)


def test_synthetic_frame(tmp_path):
    job, geom = sample_paths()
    res = run(job, geom, out_dir=str(tmp_path), stem="T", write_tab=True)
    assert res.error is None, res.error
    assert res.ok and res.pieces == 23
    assert abs(res.grand_lbs - 15281) < 2
    assert res.totals["IfcColumn"][0] == 7 and res.totals["IfcBeam"][0] == 8
    assert res.check.ok and not res.check.fails
    for p in (res.ifc, res.manifest, res.png, res.check_txt, res.workbook_out):
        assert p and os.path.isfile(p), p
    # workbook round trip builds the same model: same GUIDs, end points, sizes and weights
    res2 = run(job, res.workbook_out, out_dir=str(tmp_path / "rt"), stem="T")
    assert res2.ok and res2.pieces == 23
    keys = ("MARK", "PIECE", "GUID", "CLASS", "SIZE", "GRADE", "X1", "Y1", "Z1", "X2", "Y2", "Z2", "ROT", "CP", "LBS")
    a = sorted(tuple(r[k] for k in keys) for r in csv.DictReader(open(res.manifest, encoding="utf-8")))
    b = sorted(tuple(r[k] for k in keys) for r in csv.DictReader(open(res2.manifest, encoding="utf-8")))
    assert a == b


def test_guids_stable(tmp_path):
    job, geom = sample_paths()
    r1 = run(job, geom, out_dir=str(tmp_path / "a"), stem="T")
    r2 = run(job, geom, out_dir=str(tmp_path / "b"), stem="T")
    g1 = {(r["MARK"], r["PIECE"]): r["GUID"] for r in csv.DictReader(open(r1.manifest))}
    g2 = {(r["MARK"], r["PIECE"]): r["GUID"] for r in csv.DictReader(open(r2.manifest))}
    assert g1 == g2 and len(g1) == 23


def test_phoenix_bristol(tmp_path):
    job = os.path.join(DATA, "phoenix_bristol_job.json"); geom = os.path.join(DATA, "phoenix_bristol_geometry.csv")
    res = run(job, geom, out_dir=str(tmp_path), stem="PHX")
    assert res.error is None, res.error
    assert res.ok and res.pieces == 379
    assert res.totals["IfcColumn"] [0] == 82 and res.totals["IfcBeam"][0] == 43 and res.totals["IfcPlate"][0] == 172
    assert abs(res.grand_lbs - 185696) < 5          # workbook 187,084 less splice PL / anchors / bolts


def test_bad_rows_stop_or_skip(tmp_path):
    job, geom = sample_paths()
    rows = load_geometry(geom)[0]
    rows[0]["SIZE"] = "W99x999"
    bad = write_geometry_csv(rows, str(tmp_path / "bad.csv"))
    strict = run(job, bad, out_dir=str(tmp_path / "s"), stem="T")
    assert strict.error and "W99x999" in strict.error and strict.ifc is None
    lenient = run(job, bad, out_dir=str(tmp_path / "l"), stem="T", strict=False)
    assert lenient.pieces == 22 and len(lenient.build_problems) == 1 and not lenient.ok


def test_check_detects_tampering(tmp_path):
    job, geom = sample_paths()
    res = run(job, geom, out_dir=str(tmp_path), stem="T")
    rows = load_geometry(geom)[0]
    rows[7]["X2"] = float(rows[7]["X2"]) + 1.0          # move a beam end by a foot in the table only
    r = check(res.ifc, rows, render_png=False)
    assert not r.ok and any("end points off" in f for f in r.fails)
