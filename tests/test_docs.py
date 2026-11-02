"""Document builders: RFI log (external + internal), scope letter, takeoff notes — built from the sample fixture."""
import os
import re

import pytest
from docx import Document
from docx.enum.section import WD_ORIENT

from bsi_model_builder.takeoff.docs import build_all_docs, build_notes_md, build_rfi_log, build_scope_letter
from bsi_model_builder.takeoff.model import Scope, ScopeItem, Takeoff
from bsi_model_builder.takeoff.sample import sample_takeoff


@pytest.fixture(scope="module")
def takeoff():
    return sample_takeoff()


@pytest.fixture(scope="module")
def built(takeoff, tmp_path_factory):
    out = tmp_path_factory.mktemp("docs")
    return build_all_docs(takeoff, str(out), "SAMPLE")


def all_text(path):
    """every string in the document: body paragraphs, table cells, headers, footers"""
    d = Document(path)
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts.extend(c.text for c in row.cells)
    for s in d.sections:
        parts.extend(p.text for p in s.header.paragraphs)
        parts.extend(p.text for p in s.footer.paragraphs)
    return "\n".join(parts)


def rfi_table(path):
    """the RFI table is the one whose first header cell is 'RFI'"""
    for t in Document(path).tables:
        if t.rows and t.rows[0].cells[0].text == "RFI":
            return t
    raise AssertionError("no RFI table in " + path)


# ----------------------------------------------------------------------------- build_all_docs
def test_build_all_docs_names_and_files(built):
    assert set(built) == {"rfi", "rfi_internal", "scope", "notes"}
    assert built["rfi"].endswith("SAMPLE_RFI_Log_BohlingSteel.docx")
    assert built["rfi_internal"].endswith("SAMPLE_RFI_Log_BohlingSteel_INTERNAL.docx")
    assert built["scope"].endswith("SAMPLE_Steel_Scope_BohlingSteel.docx")
    assert built["notes"].endswith("SAMPLE_takeoff_notes.md")
    for p in built.values():
        assert os.path.getsize(p) > 500, p


# ----------------------------------------------------------------------------- RFI log
def test_rfi_external_table(takeoff, built):
    t = rfi_table(built["rfi"])
    assert len(t.columns) == 6
    assert len(t.rows) == 1 + len(takeoff.rfis)
    assert [c.text for c in t.rows[0].cells] == ["RFI", "PRI", "TO", "STATUS", "QUESTION", "CARRIED IN BID"]
    # rows sorted by code, every cell filled
    codes = [r.cells[0].text for r in t.rows[1:]]
    assert codes == sorted(r.code for r in takeoff.rfis)
    for row in t.rows[1:]:
        for c in row.cells:
            assert c.text.strip(), f"empty cell in row {row.cells[0].text}"


def test_rfi_internal_table(takeoff, built):
    t = rfi_table(built["rfi_internal"])
    assert len(t.columns) == 8
    assert len(t.rows) == 1 + len(takeoff.rfis)
    assert [c.text for c in t.rows[0].cells][-2:] == ["EXPOSURE (lb)", "WHERE FLAGGED IN WORKBOOK"]
    for row in t.rows[1:]:
        for c in row.cells:
            assert c.text.strip()


def test_every_rfi_code_appears(takeoff, built):
    for key in ("rfi", "rfi_internal"):
        text = all_text(built[key])
        for r in takeoff.rfis:
            assert r.code in text, (key, r.code)
            assert r.subject in text and r.carried in text


def test_internal_only_marked_internal(built):
    assert "INTERNAL" not in all_text(built["rfi"])
    assert "INTERNAL" not in all_text(built["scope"])
    internal = all_text(built["rfi_internal"])
    paras = [p.text for p in Document(built["rfi_internal"]).paragraphs]
    assert "INTERNAL — DO NOT SEND" in paras                                # the red body line
    assert "PRE-BID RFI LOG — SAMPLE SHELL BUILDING — INTERNAL" in paras    # and the title
    footer = "".join(p.text for p in Document(built["rfi_internal"]).sections[0].footer.paragraphs)
    assert "INTERNAL — DO NOT SEND" in footer                               # footer repeats it on every page
    assert "INTERNAL" not in "".join(p.text for p in Document(built["rfi"]).sections[0].footer.paragraphs)


def test_rfi_letterhead_title_and_layout(takeoff, built):
    d = Document(built["rfi"])
    texts = [p.text for p in d.paragraphs]
    assert texts[0] == takeoff.header.company == "Bohling Steel, Inc."
    assert texts[1] == takeoff.header.address
    assert "PRE-BID RFI LOG — SAMPLE SHELL BUILDING" in texts
    assert "Please confirm or correct the following; the quantity carried in Bohling's bid is stated with each item." in texts
    # letterhead run: navy bold company name
    run = d.paragraphs[0].runs[0]
    assert run.bold and str(run.font.color.rgb) == "1F3864"
    # blue rule = bottom border on the address paragraph
    assert d.paragraphs[1]._p.xpath('.//w:pBdr/w:bottom[@w:color="2E75B6"]')
    # landscape, 0.6" margins
    s = d.sections[0]
    assert s.orientation == WD_ORIENT.LANDSCAPE and s.page_width > s.page_height
    assert abs(s.left_margin.inches - 0.6) < 0.01 and abs(s.top_margin.inches - 0.6) < 0.01
    # signature
    assert texts[-2:] == [takeoff.header.estimator, takeoff.header.company]


def test_rfi_priority_shading_and_header_fill(takeoff, built):
    t = rfi_table(built["rfi"])
    want = {"P1": "F4CCCC", "P2": "FCE4D6", "P3": "FFF2CC", "INFO": "E7E6E6"}
    for row in t.rows[1:]:
        code, pri = row.cells[0].text, row.cells[1].text
        fill = row.cells[1]._tc.xpath("./w:tcPr/w:shd/@w:fill")
        assert fill == [want[pri]], (code, pri, fill)
    for c in t.rows[0].cells:
        assert c._tc.xpath("./w:tcPr/w:shd/@w:fill") == ["2E75B6"]
        r = c.paragraphs[0].runs[0]
        assert r.bold and str(r.font.color.rgb) == "FFFFFF" and r.font.name == "Arial"


def test_rfi_question_cell_subject_bold_then_question(takeoff, built):
    t = rfi_table(built["rfi"])
    by_code = {r.code: r for r in takeoff.rfis}
    for row in t.rows[1:]:
        r = by_code[row.cells[0].text]
        q = row.cells[4]
        assert q.paragraphs[0].text == r.subject and q.paragraphs[0].runs[0].bold
        assert q.paragraphs[1].text == r.question and not q.paragraphs[1].runs[0].bold


def test_internal_footer_wasnow_and_totals(takeoff, built):
    d = Document(built["rfi_internal"])
    headers = [[c.text for c in t.rows[0].cells] for t in d.tables]
    assert ["REV", "DATE", "WAS lb", "NOW lb", "Δ", "NOTE"] in headers
    wn = next(t for t in d.tables if t.rows[0].cells[0].text == "REV")
    assert len(wn.rows) == 1 + len(takeoff.revisions)
    # sample REV 0 has no WAS / NOW -> blank cells; note present
    r0 = [c.text for c in wn.rows[1].cells]
    assert r0[0] == "REV 0" and r0[2] == "" and r0[3] == "" and r0[4] == "" and r0[5]
    tot = takeoff.totals()
    exposure = sum(r.exposure_lbs for r in takeoff.rfis)
    line = f"Carried: {tot['project']:,.1f} lb = {tot['tons']:.2f} T; exposure flagged: {exposure:,.1f} lb"
    assert line in [p.text for p in d.paragraphs]
    assert "WAS / NOW" in [p.text for p in d.paragraphs]
    # exposure column carries each RFI's exposure
    t = rfi_table(built["rfi_internal"])
    by_code = {r.code: r for r in takeoff.rfis}
    for row in t.rows[1:]:
        assert row.cells[6].text == f"{by_code[row.cells[0].text].exposure_lbs:,.0f}"


def test_wasnow_values_when_present(tmp_path):
    t = sample_takeoff()
    t.revisions.append(__import__("bsi_model_builder.takeoff.model", fromlist=["Revision"]).Revision("REV 1", "2026-11-09", "Addendum 1", 20000.0, 20123.45))
    p = build_rfi_log(t, tmp_path / "x.docx", internal=True)
    wn = next(tb for tb in Document(p).tables if tb.rows[0].cells[0].text == "REV")
    assert [c.text for c in wn.rows[2].cells] == ["REV 1", "2026-11-09", "20,000.0", "20,123.5", "+123.5", "Addendum 1"]


def test_rfi_column_widths_fit_the_page(built):
    for key, ncols in (("rfi", 6), ("rfi_internal", 8)):
        d = Document(built[key])
        s = d.sections[0]
        usable = s.page_width.inches - s.left_margin.inches - s.right_margin.inches
        t = rfi_table(built[key])
        widths = [c.width.inches for c in t.rows[1].cells]
        assert len(widths) == ncols and all(w > 0.3 for w in widths)
        assert sum(widths) <= usable + 0.01, (key, sum(widths), usable)


# ----------------------------------------------------------------------------- scope letter
def scope_table(path):
    for t in Document(path).tables:
        if t.rows[0].cells[0].text == "SCOPE ITEM":
            return t
    raise AssertionError("no quantities table")


def test_scope_letter_content(takeoff, built):
    d = Document(built["scope"])
    texts = [p.text for p in d.paragraphs]
    assert "STRUCTURAL STEEL SCOPE — SAMPLE SHELL BUILDING" in texts
    assert "PRELIMINARY — subject to QC" in texts
    for head in ("SCOPE INCLUDES", "QUANTITIES", "EXCLUSIONS", "CLARIFICATIONS"):
        assert head in texts
    assert "Please contact the undersigned with any questions." in texts
    for line in takeoff.scope.inclusions + takeoff.scope.exclusions + takeoff.scope.clarifications:
        assert line in texts
    assert takeoff.scope.tonnage_statement in texts
    assert texts[-3:] == [takeoff.header.estimator, takeoff.header.company, takeoff.header.address]
    s = d.sections[0]
    assert s.orientation == WD_ORIENT.PORTRAIT and s.page_height > s.page_width
    # PRELIMINARY line is bold red
    pre = next(p for p in d.paragraphs if p.text.startswith("PRELIMINARY"))
    assert pre.runs[0].bold and str(pre.runs[0].font.color.rgb) == "C00000"


def test_scope_quantities_table(takeoff, built):
    t = scope_table(built["scope"])
    assert [c.text for c in t.rows[0].cells] == ["SCOPE ITEM", "QUANTITY", "UNIT"]
    assert len(t.rows) == 1 + len(takeoff.scope.quantities)
    for row, q in zip(t.rows[1:], takeoff.scope.quantities):
        item, qty, unit = [c.text for c in row.cells]
        assert item == q.item and qty == q.quantity and unit.strip(), f"empty UNIT on '{q.item}'"


def test_scope_blank_unit_becomes_each_and_tonnage_fallback(tmp_path):
    t = sample_takeoff()
    t.scope = Scope(inclusions=["x"], quantities=[ScopeItem("Columns", "104", ""), ScopeItem("Beams", "7", "  ")],
                    tonnage_statement="", preliminary=False)
    p = build_scope_letter(t, tmp_path / "s.docx")
    tb = scope_table(p)
    assert [r.cells[2].text for r in tb.rows[1:]] == ["each", "each"]
    d = Document(p)
    texts = [x.text for x in d.paragraphs]
    assert not any("PRELIMINARY" in x for x in texts)
    tot = t.totals()
    want = (f"Project tonnage approximately {tot['tons']:.1f} tons ({tot['pieces']['columns'] + tot['pieces']['beams']} pieces: "
            f"{tot['pieces']['columns']} columns, {tot['pieces']['beams']} beams) plus Misc Metals {tot['misc_metals']:,.0f} lb (separate).")
    assert want in texts


def test_empty_takeoff_builds_everything(tmp_path):
    paths = build_all_docs(Takeoff(), str(tmp_path / "nested" / "dir"), "EMPTY")
    for p in paths.values():
        assert os.path.getsize(p) > 100
    assert "PROJECT TOTAL" in open(paths["notes"], encoding="utf-8").read()
    assert "No RFIs at this time." in all_text(paths["rfi"])


def test_control_characters_do_not_break_docx(tmp_path):
    t = sample_takeoff()
    t.rfis[0].question = "bad\x00char\x0b in text"
    p = build_rfi_log(t, tmp_path / "c.docx")
    assert "badchar in text" in all_text(p)


# ----------------------------------------------------------------------------- notes markdown
def test_notes_md(takeoff, built):
    md = open(built["notes"], encoding="utf-8").read()
    tot = takeoff.totals()
    assert md.startswith("# Sample Shell Building — takeoff notes (REV 0, ")
    assert "PROJECT TOTAL" in md
    assert f"{tot['tons']:.2f}" in md
    assert f"{tot['project']:,.1f}" in md
    for row in ("| Columns |", "| Beams |", "| Detail Register |", "| Misc Parts (net) |", "| Anchor rods |", "| Field bolts |"):
        assert row in md
    for h in ("## What changed", "## Key calls", "## Sheet coverage", "## Open before bid"):
        assert h in md
    # memo lines use ft-in for lengths and carry the totals
    assert f"{tot['memo']:,.1f} lb" in md and f"Misc Metals (separate): {tot['misc_metals']:,.1f} lb" in md
    assert "30'-0\"" in md
    # sheets: all listed with steel flag
    for s in takeoff.sheets:
        assert f"| {s.number} |" in md
    # open items: every non-INFO RFI, no INFO RFI
    for r in takeoff.rfis:
        line = f"**{r.code}**"
        assert (line in md.split("## Open before bid")[1]) == (r.status != "INFO"), r.code
    # key calls
    for a in takeoff.assumptions:
        assert a in md
    # markdown tables are well formed: every table row has the same pipe count as its header
    block = None
    for ln in md.splitlines():
        if ln.startswith("|"):
            n = ln.count("|")
            block = n if block is None else block
            assert n == block, ln
        else:
            block = None


def test_notes_md_what_changed_was_now(tmp_path):
    from bsi_model_builder.takeoff.model import Revision
    t = sample_takeoff()
    t.revisions.append(Revision("REV 1", "2026-11-09", "Addendum 1: C2 raised", 20000.0, 20250.0))
    md = open(build_notes_md(t, tmp_path / "n.md"), encoding="utf-8").read()
    assert "WAS 20,000.0 lb → NOW 20,250.0 lb (+250.0 lb)" in md


def test_text_roundtrip_no_empty_data_cells(takeoff, built):
    """every scalar the model carries for the RFI / scope documents shows up in the re-opened files"""
    ext = all_text(built["rfi"])
    h = takeoff.header
    for v in (h.owner, h.architect, h.ser, h.gc, h.set_description, h.date, h.rev, h.bid_due, h.estimator, h.company, h.address):
        assert v in ext, v
    sc = all_text(built["scope"])
    for v in (h.owner, h.architect, h.ser, h.gc, h.set_description, h.date, h.rev, h.bid_due):
        assert v in sc, v
    # no table anywhere has a blank body cell where the sample has data (WAS/NOW blanks excepted)
    for key in ("rfi", "scope"):
        for tb in Document(built[key]).tables:
            for row in tb.rows:
                for c in row.cells:
                    assert c.text.strip(), (key, [x.text for x in row.cells])


def test_long_log_repeats_header_and_keeps_rows_whole(tmp_path):
    from bsi_model_builder.takeoff.model import RFIItem
    t = sample_takeoff()
    for n in range(6, 46):
        t.rfis.append(RFIItem(f"BSI-{n:02d}", "P2", "SER", f"Subject {n}", "Confirm or correct the carried quantity. " * 4,
                              f"{n} x W12x26", "OPEN", 100.0, "Beam Detail: rows", 50.0))
    for internal in (False, True):
        p = build_rfi_log(t, tmp_path / f"long{internal}.docx", internal=internal)
        tb = rfi_table(p)
        assert len(tb.rows) == 1 + len(t.rfis)
        assert tb.rows[0]._tr.xpath("./w:trPr/w:tblHeader")                 # header repeats on each page
        assert all(r._tr.xpath("./w:trPr/w:cantSplit") for r in tb.rows)    # a row never splits across pages
        codes = [r.cells[0].text for r in tb.rows[1:]]
        assert codes == sorted(codes) and codes[-1] == "BSI-45"            # numeric sort, BSI-10 after BSI-09
