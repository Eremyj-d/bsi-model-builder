"""Spec-book scan and the steel-word prefilter: no API call for a 1,000-page manual or a finish-schedule sheet."""
import os, json, pytest
from bsi_model_builder.takeoff.engine import Engine, STEEL_WORDS, run_takeoff
from bsi_model_builder.takeoff.model import Header
from bsi_model_builder.takeoff.providers import MockProvider

HERE = os.path.dirname(__file__)


def make_spec_book(path, pages=80, steel_pages=(10, 11, 40)):
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(path, pagesize=letter)
    for i in range(pages):
        c.setFont("Helvetica", 10)
        if i in steel_pages:
            c.drawString(72, 720, f"SECTION 051200 STRUCTURAL STEEL FRAMING — page {i}")
            c.drawString(72, 700, "2.3 ANCHOR RODS: ASTM F1554 Grade 55, hot-dip galvanized per ASTM A153.")
        else:
            c.drawString(72, 720, f"SECTION 09{i:04d} FINISHES — page {i}")
            c.drawString(72, 700, "Paint, carpet and ceiling tile requirements for the interior finish schedule.")
        for k in range(20):
            c.drawString(72, 680 - 14 * k, "Lorem ipsum specification text line for padding so the page has real text content on it.")
        c.showPage()
    c.save()
    return path


def test_spec_book_is_scanned_not_listed(tmp_path):
    from tests.synth.make_drawings import make_set
    pdf = [p for p in make_set(str(tmp_path / "s")) if p.endswith("SAMPLE_Structural.pdf")][0]
    book = make_spec_book(str(tmp_path / "ProjectManual.pdf"))
    prov = MockProvider(os.path.join(HERE, "data", "mock_responses"))
    seen = {}
    orig = prov.call
    def spy(stage, system, blocks, tool, use_cache=True, label=""):
        seen[stage] = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        return orig(stage, system, blocks, tool, use_cache, label)
    prov.call = spy
    res = run_takeoff([pdf, book], Header(job="Sample Shell Building", job_code="SAMPLE"), prov, str(tmp_path / "out"))
    assert not res.errors, res.errors
    assert "SPEC BOOK" in seen["index"] and "project manual, 80 pages" in seen["index"]
    assert "page 41 text" not in seen["index"] and "FINISHES — page 50" not in seen["index"]   # book pages not listed one by one
    assert "051200 STRUCTURAL STEEL" in seen["notes"] and "FINISHES — page 50" not in seen["notes"]   # only the steel sections reach the notes stage
    assert seen["notes"].count("spec page") == 3


def test_steel_words_prefilter():
    assert STEEL_WORDS.search("LINTEL SCHEDULE L6x4x3/8 GALV")
    assert STEEL_WORDS.search("ROOF LADDER PER DETAIL 5/A501")
    assert STEEL_WORDS.search("W12X26 ABOVE")
    assert not STEEL_WORDS.search("ROOM FINISH SCHEDULE: CARPET CPT-1, PAINT P-2, ACOUSTICAL CEILING TILE, VINYL BASE")
    assert not STEEL_WORDS.search("REFLECTED CEILING PLAN — LIGHT FIXTURES, DIFFUSERS, SPRINKLER HEADS")
