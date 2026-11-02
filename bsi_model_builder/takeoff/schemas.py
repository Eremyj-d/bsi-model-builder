"""
Tool-use schemas for the extraction stages. Each stage forces the model to answer by "calling" one tool whose
input_schema is below, so every answer is structured JSON that maps straight onto takeoff/model.py.
Lengths in DECIMAL FEET; weights in lb; blank = unknown (never guess — flag with an RFI instead).
"""
from __future__ import annotations

RFI_LIST = {"type": "array", "items": {"type": "string"}, "description": "BSI-xx codes this row is tied to (empty if none)"}
FINISH_STEEL = {"type": "string", "enum": ["Primed", "Galv"]}
FINISH_HW = {"type": "string", "enum": ["Plain", "Galv"]}
PRIORITY = {"type": "string", "enum": ["P1", "P2", "P3", "INFO"]}

RFI_DRAFT = {
    "type": "object", "required": ["key", "priority", "to", "subject", "question", "carried"],
    "properties": {
        "key": {"type": "string", "description": "short stable key for this issue, e.g. 'c2-height' — the synthesis stage assigns BSI-xx numbers"},
        "priority": PRIORITY, "to": {"type": "string", "description": "SER / ARCH / GC / SER/GC"},
        "subject": {"type": "string"}, "question": {"type": "string", "description": "'confirm or correct' wording with the carried value stated"},
        "carried": {"type": "string", "description": "what is in the bid"},
        "exposure_lbs": {"type": "number", "description": "swing in lb if answered the other way (0 if none)"},
    },
}

INDEX = {
    "name": "record_sheet_index",
    "description": "Classify every page of the drawing set for a structural steel takeoff.",
    "input_schema": {
        "type": "object", "required": ["sheets", "set_description"],
        "properties": {
            "set_description": {"type": "string", "description": "one line: issue name, date, addenda, specs present"},
            "parties": {"type": "object", "properties": {k: {"type": "string"} for k in ("owner", "architect", "ser", "gc", "site", "bid_due", "job")}},
            "sheets": {"type": "array", "items": {"type": "object", "required": ["number", "title", "kind", "steel"], "properties": {
                "number": {"type": "string"}, "title": {"type": "string"},
                "kind": {"type": "string", "enum": ["general_notes", "foundation_plan", "column_schedule", "framing_plan", "elevation",
                                                     "sections_details", "schedules", "arch_plan", "arch_elevation", "arch_section_detail",
                                                     "mechanical", "electrical", "plumbing", "civil", "specs", "cover_index", "other"]},
                "steel": {"type": "string", "enum": ["Y", "N", "?"], "description": "does this sheet carry steel scope to take off"},
                "why": {"type": "string", "description": "one phrase"},
                "page": {"type": "integer", "description": "page index given in the listing"}}}},
        },
    },
}

NOTES = {
    "name": "record_general_notes",
    "description": "Material grades, finish rules, bolt specs and other takeoff-relevant notes from general-notes / spec pages.",
    "input_schema": {
        "type": "object", "required": ["grades", "finish", "notes"],
        "properties": {
            "grades": {"type": "object", "properties": {k: {"type": "string"} for k in ("W", "HSS", "plates", "angles", "channels", "anchor_rods", "bolts", "pipe")},
                       "description": "as specified; blank when the notes are silent (BSI defaults then apply)"},
            "finish": {"type": "object", "properties": {"interior": FINISH_STEEL, "exterior": FINISH_STEEL, "anchor_rods": FINISH_HW,
                                                          "galvanize_rule": {"type": "string"}, "primer": {"type": "string"}, "aess": {"type": "string"}}},
            "connection_design": {"type": "string", "description": "delegated to the fabricator? standard details? bolt type (A325-N / SC)"},
            "deck": {"type": "string"}, "joists": {"type": "string"},
            "notes": {"type": "array", "items": {"type": "object", "required": ["sheet", "text"], "properties": {"sheet": {"type": "string"}, "text": {"type": "string"}}},
                      "description": "key notes by sheet, verbatim-ish, that affect the takeoff"},
            "rfis": {"type": "array", "items": RFI_DRAFT},
        },
    },
}

COLUMNS = {
    "name": "record_columns",
    "description": "Every steel column location with its length top of footing → top of steel, base plate and anchor rods.",
    "input_schema": {
        "type": "object", "required": ["columns", "base_plates", "anchor_groups"],
        "properties": {
            "columns": {"type": "array", "items": {"type": "object", "required": ["mark", "size", "grid", "height_ft", "finish"], "properties": {
                "mark": {"type": "string"}, "size": {"type": "string", "description": "as printed, e.g. HSS6x6x3/8, W12x53"},
                "grid": {"type": "string", "description": "grid intersection, e.g. 2/B"},
                "x_ft": {"type": "number"}, "y_ft": {"type": "number"},
                "tftg_ft": {"type": "number", "description": "top of footing / base elevation in feet relative to the datum (negative below slab)"},
                "tstl_ft": {"type": "number", "description": "top of steel in feet relative to the datum"},
                "height_ft": {"type": "number", "description": "tstl - tftg, decimal feet"},
                "base_plate": {"type": "string", "description": "PL t x W x L as printed"},
                "anchors": {"type": "string", "description": "(4) 3/4\" dia x 1'-6\" …"},
                "rotation_deg": {"type": "number", "description": "0 = flanges parallel to +X"},
                "finish": FINISH_STEEL, "grade": {"type": "string"},
                "notes": {"type": "string"}, "sheet": {"type": "string"}, "rfi": RFI_LIST, "allowance": {"type": "boolean"}}}},
            "base_plates": {"type": "array", "items": {"type": "object", "required": ["mark", "size", "qty"], "properties": {
                "mark": {"type": "string"}, "size": {"type": "string", "description": "PL 3/4 x 12 x 12 (inches)"}, "qty": {"type": "integer"},
                "finish": FINISH_STEEL, "grade": {"type": "string"}, "source": {"type": "string"}, "rfi": RFI_LIST}}},
            "plate_washers": {"type": "array", "items": {"type": "object", "required": ["size", "qty"], "properties": {
                "size": {"type": "string"}, "qty": {"type": "integer"}, "finish": FINISH_HW, "source": {"type": "string"}}}},
            "anchor_groups": {"type": "array", "items": {"type": "object", "required": ["location", "member", "diameter", "per_item", "item_qty", "length"], "properties": {
                "group": {"type": "string", "enum": ["Column ABs", "Additional AB Groups", "Lintel ABs"]},
                "location": {"type": "string"}, "member": {"type": "string"}, "diameter": {"type": "string"},
                "per_item": {"type": "integer"}, "item_qty": {"type": "integer"}, "length": {"type": "string"},
                "finish": FINISH_HW, "grade": {"type": "string"}, "notes": {"type": "string"}, "rfi": RFI_LIST, "allowance": {"type": "boolean"}}}},
            "datum": {"type": "string", "description": "what 0,0,0 is for the x/y/z values (grid origin, T/SLAB elevation)"},
            "rfis": {"type": "array", "items": RFI_DRAFT},
        },
    },
}

FRAMING = {
    "name": "record_framing",
    "description": "Every beam / girder / lintel / brace on one framing sheet, with true lengths, levels and connection counts.",
    "input_schema": {
        "type": "object", "required": ["members", "levels"],
        "properties": {
            "levels": {"type": "array", "items": {"type": "object", "required": ["name", "elev_ft"], "properties": {"name": {"type": "string"}, "elev_ft": {"type": "number"}}},
                       "description": "T/STL levels on this sheet relative to the datum"},
            "members": {"type": "array", "items": {"type": "object", "required": ["size", "length_ft", "type"], "properties": {
                "type": {"type": "string", "enum": ["BEAM", "GIRDER", "LINTEL", "BRACE", "GIRT", "PURLIN", "STRUT", "KICKER", "POST"]},
                "size": {"type": "string"}, "tag": {"type": "string", "description": "studs / camber / plan tag as printed, e.g. [8]"},
                "grid": {"type": "string", "description": "A/1-2 (line / between)"},
                "length_ft": {"type": "number", "description": "true length (slope-corrected) end to end"},
                "x1_ft": {"type": "number"}, "y1_ft": {"type": "number"}, "z1_ft": {"type": "number"},
                "x2_ft": {"type": "number"}, "y2_ft": {"type": "number"}, "z2_ft": {"type": "number"},
                "level": {"type": "string"}, "finish": FINISH_STEEL, "grade": {"type": "string"},
                "end1": {"type": "string", "description": "support / connection at end 1: 'col C1 cap plate' / 'W16 girder shear tab' / 'CMU pocket'"},
                "end2": {"type": "string"},
                "note": {"type": "string"}, "flag": {"type": "string", "description": "VERIFY … when the length or size is uncertain"},
                "x_pt": {"type": "number"}, "y_pt": {"type": "number"},
                "rfi": RFI_LIST, "allowance": {"type": "boolean"}}}},
            "memo": {"type": "array", "items": {"type": "object", "required": ["item", "qty", "unit"], "properties": {
                "item": {"type": "string"}, "qty": {"type": "number"}, "unit": {"type": "string", "enum": ["EA", "SF", "LF"]},
                "lb_per_unit": {"type": "number"}, "length_ft": {"type": "number"}, "note": {"type": "string"}}},
                     "description": "joists, deck, joist girders — memo only"},
            "openings": {"type": "array", "items": {"type": "object", "required": ["kind", "qty", "size"], "properties": {
                "kind": {"type": "string"}, "qty": {"type": "integer"}, "size": {"type": "string"}, "detail": {"type": "string"}, "note": {"type": "string"}}}},
            "connections": {"type": "array", "items": {"type": "object", "required": ["group", "connection_type", "count"], "properties": {
                "group": {"type": "string", "enum": ["Beam-to-Beam Shear", "Beam-on-Column Cap Plate", "Moment", "Brace", "Post-installed"]},
                "connection_type": {"type": "string"}, "location": {"type": "string"}, "count": {"type": "integer"},
                "member_sizes": {"type": "string", "description": "e.g. W12 ends → 2 bolts; W16 → 3 bolts"}, "detail": {"type": "string"}}}},
            "sheet_notes": {"type": "array", "items": {"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}}},
            "rfis": {"type": "array", "items": RFI_DRAFT},
        },
    },
}

DETAILS = {
    "name": "record_details",
    "description": "Every steel item out of each detail / section cut / schedule on this sheet, grouped into kits, plus connection hardware.",
    "input_schema": {
        "type": "object", "required": ["kits"],
        "properties": {
            "kits": {"type": "array", "items": {"type": "object", "required": ["title", "refs", "items"], "properties": {
                "title": {"type": "string", "description": "CONDITION IN CAPS, e.g. COLUMN BASE AND CAP PLATES"}, "refs": {"type": "string"},
                "no_steel": {"type": "boolean", "description": "true for details reviewed that add no new BSI steel"},
                "items": {"type": "array", "items": {"type": "object", "required": ["detail_ref", "condition", "item", "size_spec", "unit_basis", "unit"], "properties": {
                    "detail_ref": {"type": "string"}, "condition": {"type": "string"}, "item": {"type": "string"},
                    "size_spec": {"type": "string", "description": "size as printed; for plates PL t x W x L"},
                    "unit_basis": {"type": "string"}, "unit": {"type": "string", "enum": ["LF", "EA", "SET", "PR", "SF", "—"]},
                    "lb_per_unit": {"type": "number", "description": "leave 0 if you want the app to compute it from size_spec"},
                    "qty_applied": {"type": "number", "description": "omit when NOT YET APPLIED (the plan count is unknown)"},
                    "qty_source": {"type": "string"}, "notes": {"type": "string"},
                    "finish": FINISH_STEEL, "grade": {"type": "string"}, "rfi": RFI_LIST}}}}}},
            "bolts": {"type": "array", "items": {"type": "object", "required": ["group", "connection_type", "spec", "per_conn"], "properties": {
                "group": {"type": "string", "enum": ["Beam-to-Beam Shear", "Beam-on-Column Cap Plate", "Moment", "Brace", "Post-installed"]},
                "connection_type": {"type": "string"}, "location": {"type": "string"}, "spec": {"type": "string"},
                "per_conn": {"type": "integer"}, "conn_qty": {"type": "integer", "description": "omit when the count comes from the framing stage"},
                "lb_ea": {"type": "number"}, "finish": FINISH_HW, "notes": {"type": "string"}, "rfi": RFI_LIST, "allowance": {"type": "boolean"}}}},
            "misc_parts": {"type": "array", "items": {"type": "object", "required": ["group", "qty", "shape", "size"], "properties": {
                "group": {"type": "string"}, "qty": {"type": "integer"}, "shape": {"type": "string"}, "thickness": {"type": "string"},
                "size": {"type": "string"}, "length_ft": {"type": "number"}, "lb_ea": {"type": "number"},
                "finish": FINISH_STEEL, "grade": {"type": "string"}, "source": {"type": "string"}, "mark": {"type": "string"}, "rfi": RFI_LIST, "allowance": {"type": "boolean"}}}},
            "misc_metals": {"type": "array", "items": {"type": "object", "required": ["group", "qty", "shape", "size"], "properties": {
                "group": {"type": "string"}, "qty": {"type": "integer"}, "shape": {"type": "string"}, "size": {"type": "string"},
                "length_ft": {"type": "number"}, "lb_ea": {"type": "number"}, "finish": FINISH_STEEL, "grade": {"type": "string"},
                "source": {"type": "string"}, "mark": {"type": "string"}, "rfi": RFI_LIST, "allowance": {"type": "boolean"}}}},
            "sheet_notes": {"type": "array", "items": {"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}}},
            "rfis": {"type": "array", "items": RFI_DRAFT},
        },
    },
}

SYNTHESIS = {
    "name": "record_synthesis",
    "description": "RFI log, scope letter content, Summary blocks and assumptions for the whole takeoff.",
    "input_schema": {
        "type": "object", "required": ["rfis", "inclusions", "exclusions", "scope"],
        "properties": {
            "rfis": {"type": "array", "items": {"type": "object", "required": ["code", "priority", "to", "subject", "question", "carried", "where_flagged"], "properties": {
                "code": {"type": "string", "description": "BSI-01, BSI-02 … sequential, P1 first"}, "key": {"type": "string", "description": "the draft key it came from"},
                "priority": PRIORITY, "to": {"type": "string"}, "subject": {"type": "string"}, "question": {"type": "string"},
                "carried": {"type": "string"}, "status": {"type": "string", "enum": ["OPEN", "ANSWERED", "INFO"]},
                "where_flagged": {"type": "string", "description": "tab: marks / rows"}, "exposure_lbs": {"type": "number"}}}},
            "inclusions": {"type": "array", "items": {"type": "string"}, "description": "Summary green block, member-family level"},
            "exclusions": {"type": "array", "items": {"type": "string"}, "description": "Summary red block"},
            "assumptions": {"type": "array", "items": {"type": "string"}},
            "galv_unquantified": {"type": "array", "items": {"type": "string"}},
            "scope_summary": {"type": "string", "description": "one paragraph for SCOPE OF WORK"},
            "scope": {"type": "object", "required": ["inclusions", "exclusions", "clarifications", "quantities"], "properties": {
                "inclusions": {"type": "array", "items": {"type": "string"}}, "exclusions": {"type": "array", "items": {"type": "string"}},
                "clarifications": {"type": "array", "items": {"type": "string"}},
                "quantities": {"type": "array", "items": {"type": "object", "required": ["item", "quantity", "unit"], "properties": {
                    "item": {"type": "string"}, "quantity": {"type": "string"}, "unit": {"type": "string"}}}},
                "tonnage_statement": {"type": "string"}}},
        },
    },
}

STAGES = {"index": INDEX, "notes": NOTES, "columns": COLUMNS, "framing": FRAMING, "details": DETAILS, "synthesis": SYNTHESIS}
