"""pdfset — drawing-PDF ingestion checked against the synthetic SAMPLE SHELL BUILDING set (tests/synth)."""
import json
import os
import sys
from collections import Counter

import pytest

pymupdf = pytest.importorskip("pymupdf")          # pdfset needs pymupdf; the synthetic set needs reportlab
pytest.importorskip("reportlab")

from bsi_model_builder.takeoff.pdfset import (DrawingSet, merge_collinear, parse_ft_in, find_ft_in,   # noqa: E402
                                              split_at_points, SIZE_RE)

try:
    from tests.synth.make_drawings import make_set, PAGE_W, PAGE_H, PT_PER_FT
except ImportError:                                 # tests/ is not a package: import relative to this file
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from synth.make_drawings import make_set, PAGE_W, PAGE_H, PT_PER_FT

EXPECTED_SHEETS = [("S001", "General Notes"), ("S101", "Foundation Plan & Column Schedule"),
                   ("S102", "Roof Framing Plan"), ("S501", "Typical Details")]
EXPECTED_MEMBERS = {"W12x26": (4, 25.0), "W16x31": (3, 30.0), "W12x19": (7, 30.0)}


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    out = tmp_path_factory.mktemp("synth")
    paths = make_set(str(out))
    return {"paths": paths, "combined": paths[0], "separate": paths[1:5], "rot90": paths[5]}


@pytest.fixture(scope="module")
def ds(synth):
    d = DrawingSet([synth["combined"]])
    yield d
    d.close()


# ------------------------------------------------------------------------------------------ pure helpers
def test_parse_ft_in():
    assert parse_ft_in("25'-0\"") == 25.0
    assert abs(parse_ft_in("23'-6 1/2\"") - 23.5416667) < 1e-6
    assert parse_ft_in("30'-0 3/8\"") == 30.03125
    assert parse_ft_in("12'-3 15/16\"") == 12.328125
    assert parse_ft_in("25'") == 25.0
    assert parse_ft_in("6\"") == 0.5
    assert parse_ft_in("-2'-0\"") == -2.0
    assert parse_ft_in("25") is None and parse_ft_in("") is None and parse_ft_in("W12x26") is None
    assert [v for _, v in find_ft_in("T/STL 14'-0\" at A, 15'-6\" at B")] == [14.0, 15.5]


def test_size_regex():
    cases = {"W12x26": ("W12x26", ""), "W16x31 [8]": ("W16x31", "8"), "W21x44 (18)": ("W21x44", "18"),
             "HSS5x5x5/16": ("HSS5x5x5/16", ""), "HSS 6.625x0.280": ("HSS6.625x0.280", ""),
             "L4x4x1/4": ("L4x4x1/4", ""), "2L3x3x1/4": ("2L3x3x1/4", ""), "C12x20.7": ("C12x20.7", ""),
             "MC12x31": ("MC12x31", ""), "WT5x11": ("WT5x11", ""), "PL 3/4 x 12 x 1'-0\"": ("PL 3/4x12x1'-0\"", ""),
             "PIPE 4 STD": ("PIPE 4 STD", ""), "W12X26 TYP.": ("W12x26", "TYP."), "W18x35 c=1\"": ("W18x35", "c=1\"")}
    for text, (size, tag) in cases.items():
        got = DrawingSet.parse_size(text)
        assert got and got[0] == size and got[1] == tag, (text, got)
    for text in ("C1", "C2", "S101", "W12", "PLAN 1", "SEE S501", "T/STL 14'-0\""):
        assert DrawingSet.parse_size(text) is None, text
    assert SIZE_RE.search("W12x26")


def test_merge_and_split():
    mk = lambda x1, y1, x2, y2, w=1.2: {"p1": (x1, y1), "p2": (x2, y2), "width": w, "color": None,
                                         "dashes": None, "length": ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5}
    lines = [mk(0, 10, 100, 10), mk(101, 10, 200, 10), mk(205, 10, 300, 10),       # touching, then a 5-pt gap
             mk(0, 50, 0, 150), mk(0, 150.5, 0, 250),                              # vertical, touching
             mk(0, 10.5, 100, 10.5, 0.3), mk(0, 100, 100, 100)]                    # same line (offset 0.5), other
    m = merge_collinear(lines, max_gap_pt=3.0)
    lens = sorted(round(x["length"], 1) for x in m)
    assert lens == [95.0, 100.0, 200.0, 200.0], lens
    long = [x for x in m if round(x["length"]) == 200 and abs(x["p1"][1] - 10) < 1][0]
    assert long["n_parts"] == 3 and long["width"] == 1.2
    s = split_at_points(m, [(100.0, 10.0), (0.0, 150.0), (0.0, 10.0)], tol_pt=3.0)
    lens = sorted(round(x["length"], 1) for x in s)
    assert lens == [95.0, 100.0, 100.0, 100.0, 100.0, 100.0], lens


# ------------------------------------------------------------------------------------------ the synthetic set
def test_set_files(synth):
    assert len(synth["paths"]) == 6
    for p in synth["paths"]:
        assert os.path.exists(p) and os.path.getsize(p) > 1000
    assert pymupdf.open(synth["combined"]).page_count == 4
    assert all(pymupdf.open(p).page_count == 1 for p in synth["separate"])
    assert all(pg.rotation == 90 for pg in pymupdf.open(synth["rot90"]))


def test_sheet_numbers_and_titles(ds):
    assert [(p.sheet_number, p.sheet_title) for p in ds.pages] == EXPECTED_SHEETS
    for p in ds.pages:
        assert (p.width_pt, p.height_pt, p.rotation) == (PAGE_W, PAGE_H, 0)
        assert p.has_text and p.text_chars > 100 and p.image_count == 0
    assert ds.pages[1].has_vector and ds.pages[2].has_vector      # plans: > 50 paths
    assert ds.find_sheet("s102") == 2
    table = ds.summary_table()
    assert "S102" in table and "Roof Framing Plan" in table
    assert [r["sheet_number"] for r in ds.summary()] == [s for s, _ in EXPECTED_SHEETS]


def test_separate_files_detect_the_same(synth):
    d = DrawingSet(synth["separate"])
    assert [(p.sheet_number, p.sheet_title) for p in d.pages] == EXPECTED_SHEETS
    assert [p.file_page for p in d.pages] == [0, 0, 0, 0] and [p.page_index for p in d.pages] == [0, 1, 2, 3]
    d.close()


def test_grid_bubbles_s102(ds):
    b = ds.grid_bubbles(2)
    assert b["method"] == "circles"
    assert set(b["x_axis"]) == {"1", "2", "3"} and set(b["y_axis"]) == {"A", "B"}
    assert list(b["x_axis"]) == ["1", "2", "3"]                     # sorted left to right
    assert b["y_axis"]["A"][1] > b["y_axis"]["B"][1]                # A below B on the page
    assert all(x["gridline"] for x in b["bubbles"]) and not b["markers"]
    # detail markers on S501 are not grid bubbles
    m = ds.grid_bubbles(3)
    assert not m["x_axis"] and not m["y_axis"]
    assert sorted(x["tag"] for x in m["markers"]) == ["1", "2", "3"]
    assert ds.grid_bubbles(0)["method"] == "none"


def test_calibration_s102(ds):
    cal = ds.calibrate(ds.grid_bubbles(2))
    assert cal["method"] == "dimension strings"
    assert abs(cal["pt_per_ft"] - PT_PER_FT) / PT_PER_FT < 0.01
    for tag, ft in {"1": 0.0, "2": 25.0, "3": 50.0}.items():
        assert abs(cal["x_ft"][tag] - ft) < 0.05, (tag, cal["x_ft"])
    for tag, ft in {"A": 0.0, "B": 30.0}.items():
        assert abs(cal["y_ft"][tag] - ft) < 0.05, (tag, cal["y_ft"])
    assert cal["residual_pt"] < 0.5
    assert len(cal["pairs"]) == 3 and all(p["ft"] for p in cal["pairs"])
    # given spacings override the text
    cal2 = ds.calibrate(ds.grid_bubbles(2), known_spacings={"1-2": 25.0, "2-3": 25.0, ("A", "B"): 30.0})
    assert cal2["method"] == "given spacings" and abs(cal2["pt_per_ft"] - PT_PER_FT) < 0.01


def test_members_s102(ds):
    cal = ds.calibrate(ds.grid_bubbles(2))
    mem = ds.members(2, cal)
    matched = [m for m in mem if m["line"] is not None]
    assert len(matched) == 14 and all(m["flag"] == "" for m in mem), [(m["size"], m["flag"]) for m in mem]
    counts = Counter(m["size"] for m in matched)
    assert counts == {s: n for s, (n, _) in EXPECTED_MEMBERS.items()}, counts
    for m in matched:
        n, L = EXPECTED_MEMBERS[m["size"]]
        assert abs(m["length_ft"] - L) < 0.05, (m["size"], m["length_ft"])
        # end points in grid feet are consistent with the length
        dx, dy = m["x2_ft"] - m["x1_ft"], m["y2_ft"] - m["y1_ft"]
        assert abs((dx * dx + dy * dy) ** 0.5 - m["length_ft"]) < 1e-6
    # the W12x26 along A sit at y = 0 ft, along B at y = 30 ft; the W16x31 run from A to B on grids 1, 2, 3
    ys = sorted(round(m["y1_ft"], 2) for m in matched if m["size"] == "W12x26")
    assert ys == [0.0, 0.0, 30.0, 30.0]
    xs = sorted(round(m["x1_ft"], 2) for m in matched if m["size"] == "W16x31")
    assert xs == [0.0, 25.0, 50.0]
    assert {round(min(m["y1_ft"], m["y2_ft"]), 2) for m in matched if m["size"] == "W16x31"} == {0.0}
    # labels: horizontal text on A/B, rotated text on the vertical members
    assert all(abs(m["dir"][1]) < 1e-6 for m in matched if m["size"] == "W12x26")
    assert all(abs(m["dir"][0]) < 1e-6 for m in matched if m["size"] != "W12x26")


def test_members_other_sheets_unmatched(ds):
    s101 = ds.members(1)
    assert {m["size"] for m in s101} >= {"HSS6x6x3/8", "HSS6x6x1/2"}
    assert all(m["line"] is None and m["flag"] == "NO LINE" for m in s101)
    assert ds.members(0) == []


def test_column_symbols_s101(ds):
    pl = ds.page_lines(1)
    assert len(pl["column_symbols"]) == 6
    for s in pl["column_symbols"]:
        assert abs(s["w"] - 8.0) < 0.01 and abs(s["h"] - 8.0) < 0.01 and s["fill"] is not None
    xs = sorted({round(s["cx"]) for s in pl["column_symbols"]})
    ys = sorted({round(s["cy"]) for s in pl["column_symbols"]})
    assert xs == [500, 725, 950] and ys == [PAGE_H - 870, PAGE_H - 600]
    assert all(ln["width"] >= 0.85 for ln in pl["lines"])
    assert len(ds.page_lines(1, min_width=0)["lines"]) > len(pl["lines"])


def test_page_text_and_lines(ds):
    spans = ds.page_text(2)
    labels = [s for s in spans if s["text"].strip() == "W16x31"]
    assert len(labels) == 3 and all(abs(s["dir"][1]) == 1.0 for s in labels)
    assert all(set(s) >= {"text", "bbox", "origin", "size", "dir", "font"} for s in spans)
    lines = ds.page_text_lines(2)
    assert any("T/STL" in l["text"] for l in lines)


def test_render_page(ds, tmp_path):
    png = ds.render_page(1, dpi=72)
    pix = pymupdf.Pixmap(png)
    assert (pix.width, pix.height) == (int(PAGE_W), int(PAGE_H))
    out = ds.render_page(2, dpi=36, clip=(400, 700, 1100, 1200), out_png=str(tmp_path / "clip.png"))
    assert os.path.exists(out)
    pix = pymupdf.Pixmap(out)
    assert (pix.width, pix.height) == (350, 250)
    pix = pymupdf.Pixmap(ds.render_page(2, dpi=150))
    assert (pix.width, pix.height) == (5400, 3600)


def test_page_report_json(ds, tmp_path):
    rep = ds.page_report(2)
    s = json.dumps(rep)                      # must be serialisable
    assert rep["sheet_number"] == "S102" and rep["member_count"] == 14 and rep["unmatched_labels"] == 0
    assert rep["column_symbols"] == 6 and rep["calibration"]["pt_per_ft"] == 9.0
    assert isinstance(rep["calibration"]["origin_pt"], list) and "tuple" not in s
    p = ds.export_page_json(2, str(tmp_path / "S102.json"))
    assert json.load(open(p))["members"][0]["size"] == "W12x26"
    # report on a notes sheet still works
    rep0 = ds.page_report(0)
    assert rep0["members"] == [] and rep0["calibration"]["method"] == "unknown"


def test_rotation_90_copy(synth, ds):
    """/Rotate 90 pages: same sheets, same lengths, same bubble spacings; coordinates in the displayed frame."""
    dr = DrawingSet([synth["rot90"]])
    try:
        assert [(p.sheet_number, p.sheet_title) for p in dr.pages] == EXPECTED_SHEETS
        assert all(p.rotation == 90 and (p.width_pt, p.height_pt) == (PAGE_H, PAGE_W) for p in dr.pages)
        pix = pymupdf.Pixmap(dr.render_page(2, dpi=72))
        assert (pix.width, pix.height) == (int(PAGE_H), int(PAGE_W))
        b0, b1 = ds.grid_bubbles(2), dr.grid_bubbles(2)
        assert set(b1["x_axis"]) | set(b1["y_axis"]) == {"1", "2", "3", "A", "B"}
        c0, c1 = ds.calibrate(b0), dr.calibrate(b1)
        assert abs(c1["pt_per_ft"] - c0["pt_per_ft"]) < 0.01 * PT_PER_FT and c1["method"] == "dimension strings"
        ft0 = {**c0["x_ft"], **c0["y_ft"]}
        ft1 = {**c1["x_ft"], **c1["y_ft"]}
        for a, b in (("1", "2"), ("2", "3"), ("A", "B")):     # the same grid feet between consecutive bubbles
            assert abs(abs(ft1[b] - ft1[a]) - abs(ft0[b] - ft0[a])) < 0.05, (a, b, ft0, ft1)
        m0, m1 = ds.members(2, c0), dr.members(2, c1)
        key = lambda m: (m["size"], round(m["length_ft"], 2))
        assert sorted(map(key, m0)) == sorted(map(key, m1))
        assert all(m["flag"] == "" for m in m1)
        # label positions map through the 90° rotation: (x, y) -> (H - y, x)
        pos0 = sorted((round(PAGE_H - m["y_pt"], 1), round(m["x_pt"], 1)) for m in m0)
        pos1 = sorted((round(m["x_pt"], 1), round(m["y_pt"], 1)) for m in m1)
        assert pos0 == pos1
        assert len(dr.page_lines(1)["column_symbols"]) == 6
        rep = dr.page_report(2)
        json.dumps(rep)
        assert rep["rotation"] == 90 and rep["member_count"] == 14
    finally:
        dr.close()
