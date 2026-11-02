"""End to end on the synthetic set: drawings → (mock) extraction → takeoff JSON → workbook + docs + IFC."""
import os, json, subprocess, sys
import pytest
from bsi_model_builder.takeoff.model import Header, Takeoff
from bsi_model_builder.takeoff.providers import MockProvider
from bsi_model_builder.takeoff.engine import run_takeoff
from bsi_model_builder.takeoff.outputs import build_deliverables, build_from_workbook

HERE = os.path.dirname(__file__)
MOCK = os.path.join(HERE, "data", "mock_responses")
RECALC = "/mnt/skills/public/xlsx/scripts/recalc.py"


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    from tests.synth.make_drawings import make_set
    d = tmp_path_factory.mktemp("synth")
    paths = make_set(str(d))
    pdf = [p for p in paths if p.endswith("SAMPLE_Structural.pdf")][0]
    return pdf


def test_engine_mock(synth, tmp_path):
    prov = MockProvider(MOCK)
    res = run_takeoff([synth], Header(job="Sample Shell Building", job_code="SAMPLE"), prov, str(tmp_path), progress=print)
    assert not res.errors, res.errors
    t = res.takeoff
    stages = [c[0] for c in prov.calls]
    assert stages == ["index", "notes", "columns", "framing", "details", "synthesis"]
    assert len(t.sheets) == 4 and all(s.reviewed for s in t.sheets)
    assert len(t.columns) == 6 and sum(c.qty for c in t.columns) == 6
    assert len(t.beams) == 14 and len([b for b in t.beams if b.size == "W12x19"]) == 7
    assert all(b.lb_ft for b in t.beams) and all(c.lb_ft for c in t.columns)          # AISC weights resolved
    assert [k.letter for k in t.kits] == ["A", "Z"] and t.kits[0].items[0].lb_per_unit == pytest.approx(13.61, abs=0.05)
    assert any(b.group == "Beam-to-Beam Shear" and b.conn_qty == 14 for b in t.bolts)   # count from the framing stage
    assert [r.code for r in t.rfis] == ["BSI-01", "BSI-02"]
    assert all(c.rfi == ["BSI-01"] for c in t.columns if c.size.endswith("1/2"))        # draft key → code
    assert t.rfis[0].lbs_flagged == pytest.approx(3 * 35.11 * 17.5, rel=0.01)
    assert len(t.geometry) == 6 + 6 + 14                                                # columns + base plates + beams
    tot = t.totals()
    assert tot["pieces"] == {"columns": 6, "beams": 14}
    assert 6.0 < tot["tons"] < 7.5
    assert os.path.isfile(res.takeoff_json)
    t2 = Takeoff.from_json(res.takeoff_json)
    assert t2.totals()["project"] == pytest.approx(tot["project"])


def test_deliverables_and_review_roundtrip(synth, tmp_path):
    res = run_takeoff([synth], Header(job="Sample Shell Building", job_code="SAMPLE"), MockProvider(MOCK), str(tmp_path))
    paths = build_deliverables(res.takeoff, str(tmp_path), "SAMPLE", progress=print)
    for k in ("workbook", "rfi", "rfi_internal", "scope", "notes", "job", "geometry_csv", "ifc", "ifc_check", "ifc_views"):
        assert paths.get(k) and os.path.isfile(paths[k]), k
    assert paths["ifc_ok"] is True
    if os.path.isfile(RECALC):
        out = subprocess.run([sys.executable, RECALC, paths["workbook"], "120"], capture_output=True, text=True).stdout
        assert '"total_errors": 0' in out, out[-800:]
    # review-in-Excel round trip: rebuild docs + model from the (unedited) workbook + takeoff json
    rt = build_from_workbook(paths["workbook"], paths["takeoff_json"], str(tmp_path / "rt"), progress=print)
    assert rt["ifc_ok"] is True and os.path.isfile(rt["rfi"])


def test_cli_mock(synth, tmp_path):
    from bsi_model_builder.cli import main
    rc = main(["takeoff", "run", synth, "--job", "Sample Shell Building", "--code", "SAMPLE", "--out", str(tmp_path), "--mock", MOCK])
    assert rc == 0
    assert os.path.isfile(tmp_path / "SAMPLE_Takeoff.xlsx") and os.path.isfile(tmp_path / "SAMPLE_Model.ifc")
