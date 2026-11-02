"""Writes the canned extraction-stage answers for the synthetic drawing set (tests/synth/make_drawings.py) —
what a correct extraction returns for those four sheets. `python -m tests.synth.mock_responses <dir>`."""
import json, os, sys


def write(out_dir: str) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    def W(o, n):
        p = os.path.join(out_dir, n)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(o, fh, indent=1)
        return p
    paths = []
    paths.append(W({"set_description": "Permit set 11/01/2026 — S001, S101, S102, S501 (synthetic sample)",
       "parties": {"owner": "Sample Owner LLC", "architect": "Sample Architects", "ser": "Sample Structural Engineers", "gc": "", "site": "100 Example Rd, Lynchburg, VA", "bid_due": "", "job": "Sample Shell Building"},
       "sheets": [{"number": "S001", "title": "General Notes", "kind": "general_notes", "steel": "N", "why": "grades / finish / bolts", "page": 0},
                  {"number": "S101", "title": "Foundation Plan & Column Schedule", "kind": "column_schedule", "steel": "Y", "why": "6 columns, base plates, anchor rods", "page": 1},
                  {"number": "S102", "title": "Roof Framing Plan", "kind": "framing_plan", "steel": "Y", "why": "W12 / W16 roof framing", "page": 2},
                  {"number": "S501", "title": "Typical Details", "kind": "sections_details", "steel": "Y", "why": "base plate, cap plate, shear tab details", "page": 3}]}, "index.json"))

    paths.append(W({"grades": {"W": "A992", "HSS": "A500 Gr.C", "plates": "A572 Gr.50", "angles": "A572 Gr.50", "channels": "", "anchor_rods": "F1554 Gr.55", "bolts": "A325-N", "pipe": ""},
       "finish": {"interior": "Primed", "exterior": "Galv", "anchor_rods": "Galv", "galvanize_rule": "exterior exposed steel hot-dip galvanized", "primer": "SSPC-SP2 shop primer", "aess": ""},
       "connection_design": "standard details per S501; A325-N bearing bolts", "deck": "1 1/2\" x 22 ga Type B by others", "joists": "none",
       "notes": [{"sheet": "S001", "text": "W shapes A992; HSS A500 Gr.C; plates and angles A572 Gr.50; anchor rods F1554 Gr.55; bolts A325-N."},
                 {"sheet": "S001", "text": "Exterior exposed steel hot-dip galvanized; interior steel shop primed SSPC-SP2."}],
       "rfis": []}, "notes.json"))

    cols = []
    for mark, grid, x, y, size, tstl in [("C1-1", "1/A", 0, 0, "HSS6x6x3/8", 14.0), ("C1-2", "2/A", 25, 0, "HSS6x6x3/8", 14.0), ("C1-3", "3/A", 50, 0, "HSS6x6x3/8", 14.0),
                                         ("C2-4", "1/B", 0, 30, "HSS6x6x1/2", 15.5), ("C2-5", "2/B", 25, 30, "HSS6x6x1/2", 15.5), ("C2-6", "3/B", 50, 30, "HSS6x6x1/2", 15.5)]:
        cols.append({"mark": mark, "size": size, "grid": grid, "x_ft": x, "y_ft": y, "tftg_ft": -2.0, "tstl_ft": tstl, "height_ft": tstl + 2.0,
                     "base_plate": "PL 3/4x12x12", "anchors": "(4) 3/4\" dia x 1'-6\"", "rotation_deg": 0, "finish": "Primed", "grade": "A500 Gr.C",
                     "notes": "per S101 schedule", "sheet": "S101", "rfi": ["c2-height"] if size.endswith("1/2") else [], "allowance": False})
    paths.append(W({"columns": cols,
       "base_plates": [{"mark": "BP-A", "size": "PL 3/4x12x12", "qty": 6, "finish": "Primed", "grade": "A572 Gr.50", "source": "S501 det. 1", "rfi": []}],
       "plate_washers": [{"size": "PL 3/8x3x3", "qty": 24, "finish": "Galv", "source": "S501 det. 1"}],
       "anchor_groups": [{"group": "Column ABs", "location": "6 columns", "member": "HSS6x6", "diameter": "3/4\"", "per_item": 4, "item_qty": 6, "length": "1'-6\"",
                          "finish": "Galv", "grade": "F1554 Gr.55", "notes": "per S501 det. 1", "rfi": [], "allowance": False}],
       "datum": "grid 1 / grid A at T/SLAB 0'-0\"; T/FTG -2'-0\" per the schedule",
       "rfis": [{"key": "c2-height", "priority": "P1", "to": "SER", "subject": "C2 column height",
                 "question": "Column schedule shows C2 T/STL 15'-6\" at grid B — confirm or correct; carried 15'-6\".",
                 "carried": "3 x HSS6x6x1/2 at 17'-6\" T/FTG to T/STL", "exposure_lbs": 53}]}, "columns.json"))

    members = []
    for grid, x1, y1, x2, y2, z in [("A/1-2", 0, 0, 25, 0, 14.0), ("A/2-3", 25, 0, 50, 0, 14.0), ("B/1-2", 0, 30, 25, 30, 15.5), ("B/2-3", 25, 30, 50, 30, 15.5)]:
        lvl = "T/STL 14'-0\"" if z == 14.0 else "T/STL 15'-6\""
        members.append({"type": "BEAM", "size": "W12x26", "tag": "", "grid": grid, "length_ft": 25.0, "x1_ft": x1, "y1_ft": y1, "z1_ft": z, "x2_ft": x2, "y2_ft": y2, "z2_ft": z,
                        "level": lvl, "finish": "Primed", "grade": "A992", "end1": "col cap plate", "end2": "col cap plate", "note": "", "flag": "", "rfi": [], "allowance": False})
    for grid, x in [("1/A-B", 0), ("2/A-B", 25), ("3/A-B", 50)]:
        members.append({"type": "GIRDER", "size": "W16x31", "tag": "", "grid": grid, "length_ft": 30.0375, "x1_ft": x, "y1_ft": 0, "z1_ft": 14.0, "x2_ft": x, "y2_ft": 30, "z2_ft": 15.5,
                        "level": "sloped 14'-0\" to 15'-6\"", "finish": "Primed", "grade": "A992", "end1": "col cap plate", "end2": "col cap plate", "note": "slope-corrected", "flag": "", "rfi": ["sloped-girders"], "allowance": False})
    for k in range(7):
        x = 6.25 * (k + 1) if k < 3 else 25 + 6.25 * (k - 2)
        members.append({"type": "BEAM", "size": "W12x19", "tag": "", "grid": f"infill {k+1}", "length_ft": 30.0375, "x1_ft": x, "y1_ft": 0, "z1_ft": 14.0, "x2_ft": x, "y2_ft": 30, "z2_ft": 15.5,
                        "level": "sloped", "finish": "Primed", "grade": "A992", "end1": "W12x26 shear tab", "end2": "W12x26 shear tab", "note": "infill @ 6'-3\" o.c.", "flag": "", "rfi": [], "allowance": False})
    paths.append(W({"levels": [{"name": "T/STL at A", "elev_ft": 14.0}, {"name": "T/STL at B", "elev_ft": 15.5}],
       "members": members,
       "memo": [{"item": "Roof deck 1 1/2\" x 22 ga Type B", "qty": 1500, "unit": "SF", "lb_per_unit": 2.0, "note": "deck by others"}],
       "openings": [],
       "connections": [{"group": "Beam-to-Beam Shear", "connection_type": "shear tab", "location": "W12x19 infill to W12x26", "count": 14, "member_sizes": "W12 → 3 bolts per S501 det. 3", "detail": "3/S501"},
                       {"group": "Beam-on-Column Cap Plate", "connection_type": "cap plate", "location": "W12x26 / W16x31 on columns", "count": 6, "member_sizes": "", "detail": "2/S501"}],
       "sheet_notes": [{"text": "Roof slopes A→B 1/2\":12; T/STL 14'-0\" at A, 15'-6\" at B."}],
       "rfis": [{"key": "sloped-girders", "priority": "P2", "to": "SER", "subject": "Sloped girders",
                 "question": "W16x31 girders A→B slope 1/2\":12 — confirm sloped (not stepped); carried slope-corrected 30'-0 3/8\".", "carried": "3 x W16x31 at 30'-0 3/8\"", "exposure_lbs": 0}]}, "framing__S102.json"))

    paths.append(W({"kits": [{"title": "COLUMN CAPS AND SHEAR TABS", "refs": "S501 details 2, 3", "no_steel": False, "items": [
                    {"detail_ref": "2/S501", "condition": "Cap plate at every column", "item": "Cap plate", "size_spec": "PL 3/4x8x0'-8\"", "unit_basis": "1 per column", "unit": "EA", "lb_per_unit": 0, "qty_applied": 6, "qty_source": "6 columns", "notes": "shop welded", "finish": "Primed", "grade": "A572 Gr.50", "rfi": []},
                    {"detail_ref": "3/S501", "condition": "Beam-to-beam shear connection", "item": "Shear tab", "size_spec": "PL 3/8x4x0'-9\"", "unit_basis": "1 per W12 end", "unit": "EA", "lb_per_unit": 0, "qty_applied": 14, "qty_source": "14 W12x19 ends", "notes": "3 bolts per detail", "finish": "Primed", "grade": "A572 Gr.50", "rfi": []}]},
                {"title": "DECK ATTACHMENT", "refs": "S501 detail 4", "no_steel": True, "items": [
                    {"detail_ref": "4/S501", "condition": "Deck to beam", "item": "—", "size_spec": "puddle welds by deck installer", "unit_basis": "—", "unit": "—", "lb_per_unit": 0, "qty_source": "", "notes": "no BSI steel", "finish": "Primed", "grade": "", "rfi": []}]}],
       "bolts": [{"group": "Beam-to-Beam Shear", "connection_type": "shear tab", "location": "W12x19 to W12x26", "spec": "3/4\" x 2 1/2\" A325-N", "per_conn": 3, "lb_ea": 0.65, "finish": "Plain", "notes": "per 3/S501", "rfi": [], "allowance": False},
                 {"group": "Beam-on-Column Cap Plate", "connection_type": "cap plate", "location": "beams on columns", "spec": "3/4\" x 2 1/2\" A325-N", "per_conn": 4, "lb_ea": 0.65, "finish": "Plain", "notes": "per 2/S501", "rfi": [], "allowance": False}],
       "misc_parts": [], "misc_metals": [],
       "sheet_notes": [{"text": "Det. 1: PL 3/4 x 12 x 1'-0\" base plate, (4) 3/4\" dia F1554 Gr.55 anchor rods."}],
       "rfis": []}, "details__S501.json"))

    paths.append(W({"rfis": [{"code": "BSI-01", "key": "c2-height", "priority": "P1", "to": "SER", "subject": "C2 column height",
                 "question": "Column schedule shows C2 T/STL 15'-6\" — confirm or correct; carried 15'-6\" (17'-6\" T/FTG to T/STL).", "carried": "3 x HSS6x6x1/2 at 17'-6\"", "status": "OPEN", "where_flagged": "Column Tonnage: C2-4..C2-6; Model Geometry", "exposure_lbs": 53},
                {"code": "BSI-02", "key": "sloped-girders", "priority": "P2", "to": "SER", "subject": "Sloped girders",
                 "question": "W16x31 girders A→B slope 1/2\":12 — confirm sloped (not stepped); carried slope-corrected 30'-0 3/8\".", "carried": "3 x W16x31 at 30'-0 3/8\"", "status": "OPEN", "where_flagged": "Beam Detail: B5-B7", "exposure_lbs": 0}],
       "inclusions": ["Columns HSS6x6 + base plates + anchor rods", "Roof beams W12 / W16", "Misc Parts — base plates, cap plates, shear tabs", "Field bolts A325-N"],
       "exclusions": ["Steel roof deck (memo)", "CMU / concrete / masonry", "Field painting"],
       "assumptions": ["Roof deck by others (memo only)"],
       "galv_unquantified": [],
       "scope_summary": "Structural steel for a one-story shell: six HSS6x6 columns on base plates, W12x26 spandrels, W16x31 sloped girders and W12x19 infill at 6'-3\" o.c., cap plates and shear tabs per S501.",
       "scope": {"inclusions": ["Furnish and erect structural steel per S101, S102, S501", "Anchor rods and setting templates", "Field bolts"],
                 "exclusions": ["Roof deck", "CMU, concrete, masonry", "Field painting and fireproofing"],
                 "clarifications": ["Column heights per the S101 schedule pending BSI-01", "Girders carried sloped per BSI-02"],
                 "quantities": [{"item": "Columns HSS6x6", "quantity": "6", "unit": "each"}, {"item": "Roof beams W12 / W16", "quantity": "14", "unit": "each"},
                                {"item": "Anchor rods 3/4\"", "quantity": "24", "unit": "each"}],
                 "tonnage_statement": "Approximately 6.7 tons of fabricated structural steel (6 columns, 14 beams)."}}, "synthesis.json"))
    return paths


if __name__ == "__main__":
    for p in write(sys.argv[1] if len(sys.argv) > 1 else "tests/data/mock_responses"):
        print(p)
