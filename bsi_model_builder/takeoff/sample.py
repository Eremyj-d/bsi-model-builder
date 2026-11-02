"""
A small fictional job that exercises every tab and every row type — the fixture for the builder tests and
the mock extraction. Not a real project. "SAMPLE SHELL BUILDING", 6 columns, 14 beams, kits A-C + Z,
anchors, bolts, base plates, a ladder, 4 RFIs.
"""
from .model import *


def sample_takeoff() -> Takeoff:
    t = Takeoff()
    t.header = Header(job="Sample Shell Building", job_code="SAMPLE", building="", rev="REV 0", status="DRAFT — SAMPLE",
                      owner="Sample Owner LLC", architect="Sample Architects", ser="Sample Structural Engineers (SER)",
                      gc="Sample Builders, Inc.", site="100 Example Rd, Lynchburg, VA", bid_due="2026-12-01 2:00 PM",
                      set_description="Permit set 11/01/2026 (S001–S501, A101–A301), no addenda, no project manual",
                      source_files=["SAMPLE_Structural.pdf"],
                      scope_summary="Structural steel for a one-story shell: HSS columns, W-beam roof framing over CMU bearing walls, "
                                    "loose lintels at CMU openings, RTU opening frames, one roof-access ladder (Misc Metals).")
    t.sheets = [Sheet("S001", "General Notes", "RECEIVED", "11/01/2026", "N", True, "grades, finish, bolt spec"),
                Sheet("S101", "Foundation Plan & Column Schedule", "RECEIVED", "11/01/2026", "Y", True),
                Sheet("S102", "Roof Framing Plan", "RECEIVED", "11/01/2026", "Y", True),
                Sheet("S501", "Typical Details", "RECEIVED", "11/01/2026", "Y", True),
                Sheet("A101", "Floor Plan", "RECEIVED", "11/01/2026", "Y", True, "lintel schedule"),
                Sheet("A301", "Wall Sections", "RECEIVED", "11/01/2026", "N", True),
                Sheet("M101", "Mechanical Roof Plan", "NOT RECEIVED", "", "?", False, "RTU sizes pending")]
    t.inclusions = ["Columns (HSS6x6) + base plates + anchor rods", "Roof beams W12 / W16", "Misc Parts — base plates, cap plates, "
                    "shear tabs, RTU opening frames, loose lintels", "Field bolts A325-N", "Misc Metals (separate) — roof ladder"]
    t.exclusions = ["Open-web joists (memo)", "Steel roof deck (memo)", "CMU / concrete / masonry", "Field painting, fireproofing",
                    "Aluminum canopies by others"]
    for i, (mark, grid, x, y) in enumerate([("C1", "1/A", 0, 0), ("C1", "2/A", 25, 0), ("C1", "3/A", 50, 0),
                                           ("C2", "1/B", 0, 30), ("C2", "2/B", 25, 30), ("C2", "3/B", 50, 30)], start=1):
        size = "HSS6x6x3/8" if mark == "C1" else "HSS6x6x1/2"
        t.columns.append(ColumnRow(mark=f"{mark}-{i}", size=size, qty=1, height_ft=16.0 if mark == "C1" else 17.5, lb_ft=27.48 if mark == "C1" else 35.11,
                                   base_plate="PL 3/4 x 12 x 1'-0\"", bp_elev="T/FTG -2'-0\" → T/STL " + ("14'-0\"" if mark == "C1" else "15'-6\""),
                                   anchors='(4) 3/4" dia x 1\'-6"', finish="Primed", grade="A500 Gr.C", location=f"grid {grid}", sheet="S101",
                                   rfi=["BSI-01"] if i in (4, 5, 6) else []))
        z1, z2 = -2.0, (14.0 if mark == "C1" else 15.5)
        t.geometry.append(GeometryRow(MARK=f"{mark}-{i}", TYPE="COLUMN", SIZE=size, X1=x, Y1=y, Z1=z1, X2=x, Y2=y, Z2=z2, GRADE="A500 Gr.C",
                                      SHEET="S101", GRID=grid, LEVEL=f"T/FTG -2'-0\" to T/STL {ft_in(z2)}", CP=5, LB_FT=27.48 if mark == "C1" else 35.11,
                                      RFI="BSI-01" if i in (4, 5, 6) else ""))
        t.geometry.append(GeometryRow(MARK="BP-A", PIECE=f"{mark}-{i}", TYPE="PLATE", SIZE="PL 3/4x12x12", X1=x, Y1=y, Z1=-2.0, GRADE="A572 Gr.50",
                                      SHEET="S501", GRID=grid, LEVEL="T/FTG -2'-0\"", CP=5))
    beams = [("S102", "W12x26", 25.0, "A/1-2", 0, 0, 25, 0, 14.0), ("S102", "W12x26", 25.0, "A/2-3", 25, 0, 50, 0, 14.0),
             ("S102", "W12x26", 25.0, "B/1-2", 0, 30, 25, 30, 15.5), ("S102", "W12x26", 25.0, "B/2-3", 25, 30, 50, 30, 15.5),
             ("S102", "W16x31", 30.0375, "1/A-B", 0, 0, 0, 30, None), ("S102", "W16x31", 30.0375, "2/A-B", 25, 0, 25, 30, None),
             ("S102", "W16x31", 30.0375, "3/A-B", 50, 0, 50, 30, None)]
    n = 0
    for sheet, size, L, grid, x1, y1, x2, y2, z in beams:
        n += 1
        lbft = 26.0 if size == "W12x26" else 31.0
        slope = z is None
        t.beams.append(BeamRow(sheet=sheet, size=size, length_ft=L, lb_ft=lbft, tag=grid, mark=f"B{n}", level="T/STL 14'-0\" / 15'-6\" (sloped)" if slope else f"T/STL {ft_in(z)}",
                               note="sloped girder A→B, slope-corrected" if slope else "", rfi=["BSI-02"] if slope else []))
        t.geometry.append(GeometryRow(MARK=f"B{n}", TYPE="BEAM", SIZE=size, X1=x1, Y1=y1, Z1=14.0 if slope else z, X2=x2, Y2=y2, Z2=15.5 if slope else z,
                                      SHEET=sheet, GRID=grid, LEVEL="sloped 14'-0\" to 15'-6\"" if slope else f"T/STL {ft_in(z)}", CP=8, LB_FT=lbft,
                                      RFI="BSI-02" if slope else ""))
    for k in range(7):   # infill beams
        n += 1
        t.beams.append(BeamRow(sheet="S102", size="W12x19", length_ft=30.0375, lb_ft=19.0, tag=f"infill {k+1}", mark=f"B{n}", level="sloped",
                               note="infill @ 6'-3\" o.c."))
        x = 6.25 * (k + 1) if k < 3 else 25 + 6.25 * (k - 2)
        t.geometry.append(GeometryRow(MARK=f"B{n}", TYPE="BEAM", SIZE="W12x19", X1=x, Y1=0, Z1=14.0, X2=x, Y2=30, Z2=15.5, SHEET="S102",
                                      GRID=f"infill {k+1}", LEVEL="sloped", CP=8, LB_FT=19.0))
    t.memo = [MemoRow("S102", "Roof deck 1 1/2\" x 22 ga Type B", 1500, "SF", 2.0 / 1.0, None, "memo — deck by others", []),
              MemoRow("S102", "Open-web joists 20K5 (K-series, SJI)", 12, "EA", 8.0, 30.0, "memo — joists by SJI supplier", [])]
    t.anchors = [AnchorRow("Column ABs", "6 columns", "HSS6x6", '3/4"', 4, 6, '1\'-6"', 1.6, "Galv", "F1554 Gr.55", "per S501 det. 1", ["BSI-03"]),
                 AnchorRow("Lintel ABs", "A101 lintel L-1 (4)", "L6x4x3/8", '1/2"', 2, 4, '6"', 0.45, "Galv", "A307", "Titen HD at CMU jambs", [])]
    t.bolts = [BoltRow("Beam-to-Beam Shear", "W12 to W16 shear tabs", "shear tab", '3/4" x 2 1/2" A325-N', 3, 14, 0.65, "Plain", "AISC 3 bolts W12"),
               BoltRow("Beam-on-Column Cap Plate", "W16 on cap plates", "cap plate", '3/4" x 2 1/2" A325-N', 4, 6, 0.65, "Plain", ""),
               BoltRow("Post-installed", "RTU curb angles to deck", "Titen HD", '3/8" x 4" Titen HD', 8, 2, 0.25, "Galv", "furnish + install by BSI (precedent)", [])]
    t.misc_parts = [PartRow("Base Plates", 6, "PL", "3/4 x 12 x 12", 30.6, '3/4"', 1.0, "Primed", "A572 Gr.50", "S501 det. 1", "BP-A", []),
                    PartRow("Plate Washers", 24, "PL", "3/8 x 3 x 3", 0.96, '3/8"', None, "Galv", "A572 Gr.50", "S501 det. 1", "PW-1", [])]
    t.misc_metals = [PartRow("Ladders", 1, "LADDER", "Roof-access ladder, 1/2 x 2 1/2 bar rails, 3/4\" rungs", 180.0, "", 14.0, "Galv", "A36",
                             "A301 — allowance, no detail", "MM-1", ["BSI-04"], allowance=True)]
    t.kits = [Kit("A", "COLUMN CAPS AND SHEAR TABS", "S501 details 1, 2, 3", [
                  DetailItem("2/S501", "Cap plate at every column", "Cap plate", 'PL 3/4 x 8 x 0\'-8"', "1 per column", 13.6, 6, "EA", "6 columns", "shop welded"),
                  DetailItem("3/S501", "Beam-to-beam shear connection", "Shear tab", 'PL 3/8 x 4 x 0\'-9"', "1 per W12 end", 3.83, 14, "EA", "14 W12 ends", "3 bolts per AISC")]),
              Kit("B", "RTU OPENING FRAMES", "S501 detail 4 · M101 pending", [
                  DetailItem("4/S501", "Frame at RTU curb opening", "Angle frame", "L4x4x1/4", "per LF of opening", 6.6, 48, "LF", "2 openings x 24 LF (sizes PENDING M101)", "", "Primed", "A572 Gr.50", ["BSI-05"]),
                  DetailItem("4/S501", "Frame to deck", "Titen HD", '3/8" x 4"', "@ 2'-0\" o.c.", 0.0, None, "EA", "on Field Bolts", "counted on Field Bolts tab")]),
              Kit("C", "LOOSE LINTELS AT CMU", "A101 lintel schedule", [
                  DetailItem("A101 L-1", "Lintel over 4'-0\" openings", "Loose lintel", "L6x4x3/8 (LLV)", "per lintel 5'-4\"", 12.3 * 5.3333, 4, "EA", "4 openings tagged L-1", "bearing 8\" each end", "Galv", "A572 Gr.50")]),
              Kit("Z", "DETAILS REVIEWED — NO NEW STEEL", "S501 details 5, 6; A301 sections", [
                  DetailItem("5/S501", "Deck attachment", "—", "puddle welds by deck installer", "—", 0.0, None, "—", "", "no BSI steel"),
                  DetailItem("6/S501", "CMU bond beam", "—", "masonry", "—", 0.0, None, "—", "", "no BSI steel")], no_steel=True)]
    t.notes = [NoteLine("S001", "Structural steel: W shapes A992; HSS A500 Gr.C; plates and angles A572 Gr.50; anchor rods F1554 Gr.55; bolts A325-N."),
               NoteLine("S001", "Exterior exposed steel hot-dip galvanized; interior steel shop primed SSPC-SP2."),
               NoteLine("S102", "Roof slopes A→B 1/2\":12; T/STL 14'-0\" at A, 15'-6\" at B."),
               NoteLine("A101", "Lintel schedule: L-1 L6x4x3/8 LLV, 8\" bearing each end, galvanized.")]
    t.rfis = [RFIItem("BSI-01", "P1", "SER", "C2 column height", "Column schedule shows C2 T/STL 15'-6\" but S102 reads 15'-0\" at grid B — confirm or correct; carried 15'-6\".",
                      "3 x HSS6x6x1/2 at 17'-6\" T/FTG to T/STL", "OPEN", 3 * 35.11 * 17.5, "Column Tonnage: C2-4..6; Model Geometry", 3 * 35.11 * 0.5),
              RFIItem("BSI-02", "P2", "SER", "Sloped girders", "W16x31 girders A→B slope 1/2\":12 — confirm beams are sloped (not stepped); carried slope-corrected 30'-0 3/8\".",
                      "3 x W16x31 at 30'-0 3/8\"", "OPEN", 3 * 31 * 30.0375, "Beam Detail: B5-B7", 0),
              RFIItem("BSI-03", "P3", "SER", "Anchor rod finish", "S001 calls anchor rods galvanized, S501 det. 1 silent — carried HDG; confirm.",
                      "24 x 3/4\" x 1'-6\" F1554 Gr.55 HDG", "OPEN", 24 * 1.6, "Anchor Bolt Summary: Column ABs", 0),
              RFIItem("BSI-04", "INFO", "ARCH", "Roof ladder", "A301 shows a roof-access ladder with no detail — carried as a Misc Metals allowance (180 lb, galvanized).",
                      "1 ladder allowance", "INFO", 180, "Misc Metals: MM-1", 180),
              RFIItem("BSI-05", "P2", "GC", "RTU opening sizes", "M101 not in the set — RTU opening frames carried at 2 x 24 LF L4x4x1/4; confirm sizes and count.",
                      "48 LF L4x4x1/4", "OPEN", 48 * 6.6, "Detail Register: kit B", 48 * 6.6)]
    t.scope = Scope(inclusions=["Furnish and erect structural steel per S-sheets", "Loose lintels per A101 schedule", "RTU opening frames",
                                "Anchor rods and setting templates", "Field bolts"],
                    exclusions=["Open-web joists and roof deck", "CMU, concrete, masonry", "Field painting and fireproofing", "Aluminum canopies",
                                "Testing and inspection"],
                    clarifications=["Column heights per the S101 schedule pending BSI-01", "RTU opening frames are an allowance pending M101 (BSI-05)",
                                    "Roof ladder carried as an allowance — no detail (BSI-04)"],
                    quantities=[ScopeItem("Columns HSS6x6", "6", "each"), ScopeItem("Roof beams W12 / W16", "14", "each"), ScopeItem("Loose lintels", "4", "each"),
                                ScopeItem("RTU opening frames", "2", "each"), ScopeItem("Anchor rods 3/4\"", "24", "each"), ScopeItem("Roof-access ladder (Misc Metals)", "1", "each")],
                    tonnage_statement="Approximately 6.8 tons of fabricated structural steel (6 columns, 14 beams) plus Misc Metals 180 lb (separate).", preliminary=True)
    t.revisions = [Revision("REV 0", "2026-11-02", "Initial takeoff from the 11/01/2026 permit set", None, None)]
    t.assumptions = ["M101 not received — RTU openings carried as an allowance", "Roof ladder sized by allowance"]
    t.galv_unquantified = ["Lintel bearing plates (if required by the masonry contractor)"]
    return t


if __name__ == "__main__":
    t = sample_takeoff()
    print(t.totals()); print(t.finish_totals())
