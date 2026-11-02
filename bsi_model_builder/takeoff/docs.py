"""
Document builders for a Takeoff — the pre-bid RFI log (external + internal), the structural steel scope letter
(Word, on Bohling Steel letterhead) and the markdown takeoff notes. Formats are BSI_STANDARDS.md sections 5-7.

    build_rfi_log(takeoff, path, internal=False)   landscape .docx, RFI | PRI | TO | STATUS | QUESTION | CARRIED IN BID
    build_scope_letter(takeoff, path)              portrait .docx, SCOPE INCLUDES / QUANTITIES / EXCLUSIONS / CLARIFICATIONS
    build_notes_md(takeoff, path)                  markdown notes kept with the job
    build_all_docs(takeoff, out_dir, stem)         all four files -> {"rfi", "rfi_internal", "scope", "notes"}

Everything is read from the Takeoff; nothing is typed in here except the fixed wording the standards prescribe.
"""
from __future__ import annotations

import os
import re

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from .model import Takeoff, ft_in

__all__ = ["build_rfi_log", "build_scope_letter", "build_notes_md", "build_all_docs"]

# ----------------------------------------------------------------------------- palette / fixed wording
NAVY = "1F3864"
BLUE = "2E75B6"
RED = "C00000"
GRAY = "595959"
RULE_GRAY = "BFBFBF"
ZEBRA = "EAF1F8"
PRI_FILL = {"P1": "F4CCCC", "P2": "FCE4D6", "P3": "FFF2CC", "INFO": "E7E6E6"}
FONT = "Arial"

RFI_INTRO = "Please confirm or correct the following; the quantity carried in Bohling's bid is stated with each item."
CONTACT_LINE = "Please contact the undersigned with any questions."
BLANK = "—"   # em dash shown where the model has no value yet

_XML_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")

# OOXML child order (python-docx only orders the elements it knows; ours are inserted by hand)
_PPR_SEQ = ["pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl", "numPr", "suppressLineNumbers",
            "pBdr", "shd", "tabs", "suppressAutoHyphens", "kinsoku", "wordWrap", "overflowPunct", "topLinePunct", "autoSpaceDE",
            "autoSpaceDN", "bidi", "adjustRightInd", "snapToGrid", "spacing", "ind", "contextualSpacing", "mirrorIndents",
            "suppressOverlap", "jc", "textDirection", "textAlignment", "textboxTightWrap", "outlineLvl", "divId", "cnfStyle",
            "rPr", "sectPr", "pPrChange"]
_TBLPR_SEQ = ["tblStyle", "tblpPr", "tblOverlap", "bidiVisual", "tblStyleRowBandSize", "tblStyleColBandSize", "tblW", "jc",
              "tblCellSpacing", "tblInd", "tblBorders", "shd", "tblLayout", "tblCellMar", "tblLook", "tblCaption", "tblDescription"]
_TCPR_SEQ = ["cnfStyle", "tcW", "gridSpan", "hMerge", "vMerge", "tcBorders", "shd", "noWrap", "tcMar", "textDirection",
             "tcFitText", "vAlign", "hideMark"]


# ----------------------------------------------------------------------------- low-level docx helpers
def _clean(s) -> str:
    return _XML_BAD.sub("", "" if s is None else str(s))


def _insert_ordered(parent, child, seq):
    """put `child` into `parent` at the schema position (Word is strict about child order in pPr / tblPr / tcPr)"""
    order = [qn("w:" + t) for t in seq]
    for existing in parent.findall(child.tag):
        parent.remove(existing)
    pos = order.index(child.tag)
    for el in list(parent):
        if el.tag in order and order.index(el.tag) > pos:
            el.addprevious(child)
            return child
    parent.append(child)
    return child


def _style_run(run, size, bold=None, italic=None, color=None):
    run.font.name = FONT
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    for att in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rfonts.set(qn(att), FONT)
    run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if italic is not None:
        run.font.italic = italic
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    return run


def _fmt(par, before=0, after=0, align=None, keep_next=False, keep_together=False, line=1.0):
    pf = par.paragraph_format
    pf.space_before, pf.space_after, pf.line_spacing = Pt(before), Pt(after), line
    if align is not None:
        par.alignment = align
    if keep_next:
        pf.keep_with_next = True
    if keep_together:
        pf.keep_together = True
    return par


def _text(container, text, size=10, bold=None, italic=None, color=None, before=0, after=0, align=None,
          keep_next=False, style=None):
    """add one paragraph with one run to a Document / cell / header / footer"""
    par = container.add_paragraph(style=style) if style else container.add_paragraph()
    _fmt(par, before, after, align, keep_next)
    _style_run(par.add_run(_clean(text)), size, bold, italic, color)
    return par


def _border_bottom(par, color, sz=6, space=1):
    ppr = par._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for k, v in (("val", "single"), ("sz", str(sz)), ("space", str(space)), ("color", color)):
        bottom.set(qn("w:" + k), v)
    pbdr.append(bottom)
    _insert_ordered(ppr, pbdr, _PPR_SEQ)


def _shade(cell, fill):
    tcpr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    _insert_ordered(tcpr, shd, _TCPR_SEQ)


def _tbl_borders(table, color=RULE_GRAY, sz=4):
    tblpr = table._tbl.tblPr
    b = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = OxmlElement("w:" + edge)
        for k, v in (("val", "single"), ("sz", str(sz)), ("space", "0"), ("color", color)):
            e.set(qn("w:" + k), v)
        b.append(e)
    _insert_ordered(tblpr, b, _TBLPR_SEQ)


def _tbl_cell_margins(table, top=30, bottom=30, left=80, right=80):
    tblpr = table._tbl.tblPr
    m = OxmlElement("w:tblCellMar")
    for edge, v in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        e = OxmlElement("w:" + edge)
        e.set(qn("w:w"), str(v))
        e.set(qn("w:type"), "dxa")
        m.append(e)
    _insert_ordered(tblpr, m, _TBLPR_SEQ)


def _row_flags(row, header=False):
    trpr = row._tr.get_or_add_trPr()
    trpr.append(OxmlElement("w:cantSplit"))
    if header:
        trpr.append(OxmlElement("w:tblHeader"))


def _fill_cell(cell, content, size=9, bold=False, italic=False, color=None, align=None, fill=None, valign=None):
    """content: str, or a list of paragraphs, each str or (str, {bold, italic, color, after})"""
    items = content if isinstance(content, list) else [content]
    for n, item in enumerate(items):
        text, opts = item if isinstance(item, tuple) else (item, {})
        par = cell.paragraphs[0] if n == 0 else cell.add_paragraph()
        _fmt(par, 0, opts.get("after", 0), align)
        _style_run(par.add_run(_clean(text)), size, opts.get("bold", bold), opts.get("italic", italic), opts.get("color", color))
    if fill:
        _shade(cell, fill)
    cell.vertical_alignment = valign if valign is not None else WD_CELL_VERTICAL_ALIGNMENT.TOP


def _set_widths(table, widths):
    table.autofit = False
    tblw = table._tbl.tblPr.find(qn("w:tblW"))
    if tblw is None:
        tblw = OxmlElement("w:tblW")
        _insert_ordered(table._tbl.tblPr, tblw, _TBLPR_SEQ)
    tblw.set(qn("w:type"), "dxa")
    tblw.set(qn("w:w"), str(int(round(sum(widths) * 1440))))
    for i, w in enumerate(widths):
        table.columns[i].width = Inches(w)
    for row in table.rows:
        for i, w in enumerate(widths):
            row.cells[i].width = Inches(w)


def _grid_table(doc, headers, widths, size=9, aligns=None):
    """bordered table with a blue header row (white bold text) that repeats on every page"""
    table = doc.add_table(rows=1, cols=len(headers))
    _tbl_borders(table)
    _tbl_cell_margins(table)
    _row_flags(table.rows[0], header=True)
    for i, h in enumerate(headers):
        _fill_cell(table.rows[0].cells[i], h, size=size, bold=True, color="FFFFFF", fill=BLUE,
                   align=(aligns[i] if aligns else None), valign=WD_CELL_VERTICAL_ALIGNMENT.CENTER)
    _set_widths(table, widths)   # re-run after rows are added (see _add_row)
    return table


def _add_row(table, widths, cells, size=9, fills=None, aligns=None, bolds=None, zebra=False):
    row = table.add_row()
    _row_flags(row)
    for i, content in enumerate(cells):
        fill = (fills[i] if fills and fills[i] else (ZEBRA if zebra else None))
        _fill_cell(row.cells[i], content, size=size, bold=bool(bolds and bolds[i]), fill=fill,
                   align=(aligns[i] if aligns else None))
        row.cells[i].width = Inches(widths[i])
    return row


def _add_field(par, instr, size, color=GRAY):
    def piece(kind=None, text=None, instr_text=None):
        r = par.add_run()
        _style_run(r, size, color=color)
        if kind:
            fc = OxmlElement("w:fldChar")
            fc.set(qn("w:fldCharType"), kind)
            r._r.append(fc)
        if instr_text:
            it = OxmlElement("w:instrText")
            it.set(qn("xml:space"), "preserve")
            it.text = instr_text
            r._r.append(it)
        if text:
            r.text = text
    piece("begin")
    piece(instr_text=f" {instr} ")
    piece("separate")
    piece(text="1")
    piece("end")


# ----------------------------------------------------------------------------- shared page pieces
def _new_document(takeoff: Takeoff, landscape: bool, title: str, margin_in: float):
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(10)
    rpr = normal.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    for att in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rfonts.set(qn(att), FONT)
    for name in ("List Bullet",):
        doc.styles[name].font.name = FONT
        doc.styles[name].font.size = Pt(10)
    sec = doc.sections[0]
    if landscape:
        sec.orientation = WD_ORIENT.LANDSCAPE
        sec.page_width, sec.page_height = Inches(11), Inches(8.5)
    else:
        sec.orientation = WD_ORIENT.PORTRAIT
        sec.page_width, sec.page_height = Inches(8.5), Inches(11)
    sec.left_margin = sec.right_margin = sec.top_margin = sec.bottom_margin = Inches(margin_in)
    sec.footer_distance = Inches(0.3)
    h = takeoff.header
    cp = doc.core_properties
    cp.title = title
    cp.author = h.estimator or "Bohling Steel, Inc."
    cp.last_modified_by = cp.author
    cp.subject = h.job
    cp.comments = ""
    return doc


def _job_label(takeoff: Takeoff) -> str:
    h = takeoff.header
    return h.job + (f" — {h.building}" if h.building else "")


def _letterhead(doc, takeoff: Takeoff):
    h = takeoff.header
    _text(doc, h.company, size=18, bold=True, color=NAVY, after=0)
    addr = _text(doc, h.address, size=9, color=GRAY, after=8)
    _border_bottom(addr, BLUE, sz=8, space=4)   # thin blue rule under the letterhead


def _project_block(doc, takeoff: Takeoff, label_w: float, value_w: float):
    h = takeoff.header
    rows = [("Owner", h.owner), ("Architect", h.architect), ("SER", h.ser), ("GC", h.gc), ("Set", h.set_description),
            ("Date", h.date), ("Revision", h.rev), ("Bid due", h.bid_due)]
    table = doc.add_table(rows=0, cols=2)          # no style -> no borders
    _tbl_cell_margins(table, top=15, bottom=15, left=0, right=80)
    for label, value in rows:
        row = table.add_row()
        _row_flags(row)
        _fill_cell(row.cells[0], label.upper(), size=9, bold=True, color=NAVY)
        _fill_cell(row.cells[1], value or BLANK, size=9)
    _set_widths(table, [label_w, value_w])
    return table


def _heading(doc, text, before=10, after=3):
    par = _text(doc, text, size=10, bold=True, color=NAVY, before=before, after=after, keep_next=True)
    _border_bottom(par, RULE_GRAY, sz=4, space=1)
    return par


def _signature(doc, takeoff: Takeoff, with_address: bool):
    h = takeoff.header
    _text(doc, h.estimator, size=10, bold=True, before=14, keep_next=True)
    _text(doc, h.company, size=10, keep_next=with_address)
    if with_address:
        _text(doc, h.address, size=9, color=GRAY)


def _footer(doc, left: str, internal: bool = False, preliminary: bool = False):
    footer = doc.sections[0].footer
    footer.is_linked_to_previous = False
    par = footer.paragraphs[0]
    _fmt(par, 0, 0, WD_ALIGN_PARAGRAPH.CENTER)
    if internal:
        _style_run(par.add_run("INTERNAL — DO NOT SEND   "), 8, bold=True, color=RED)
    if preliminary:
        _style_run(par.add_run("PRELIMINARY — subject to QC   "), 8, bold=True, color=RED)
    _style_run(par.add_run(_clean(left) + "   ·   Page "), 8, color=GRAY)
    _add_field(par, "PAGE", 8)
    _style_run(par.add_run(" of "), 8, color=GRAY)
    _add_field(par, "NUMPAGES", 8)


def _code_key(code: str):
    m = re.match(r"^(.*?)(\d+)\s*$", code or "")
    return (m.group(1), int(m.group(2))) if m else (code or "", 0)


def _lb(x) -> str:
    return f"{x:,.1f}"


def _save(doc, out_path) -> str:
    out_path = os.fspath(out_path)
    d = os.path.dirname(out_path)
    if d:
        os.makedirs(d, exist_ok=True)
    doc.save(out_path)
    return out_path


# ----------------------------------------------------------------------------- RFI log
def build_rfi_log(takeoff: Takeoff, out_path, internal: bool = False) -> str:
    """Pre-bid RFI log. External = RFI | PRI | TO | STATUS | QUESTION | CARRIED IN BID (goes to the SER / architect / GC).
    internal=True adds EXPOSURE (lb) and WHERE FLAGGED IN WORKBOOK, the WAS / NOW footer and the totals line — never sent."""
    h = takeoff.header
    title = f"PRE-BID RFI LOG — {_job_label(takeoff).upper()}" + (" — INTERNAL" if internal else "")
    doc = _new_document(takeoff, landscape=True, title=title, margin_in=0.6)
    _letterhead(doc, takeoff)
    _text(doc, title, size=14, bold=True, color=NAVY, before=2, after=2)
    if internal:
        _text(doc, "INTERNAL — DO NOT SEND", size=11, bold=True, color=RED, after=4)
    _project_block(doc, takeoff, 1.1, 6.5)
    _text(doc, RFI_INTRO, size=10, before=6, after=5)

    if internal:
        headers = ["RFI", "PRI", "TO", "STATUS", "QUESTION", "CARRIED IN BID", "EXPOSURE (lb)", "WHERE FLAGGED IN WORKBOOK"]
        widths = [0.65, 0.45, 0.55, 0.65, 3.5, 1.45, 0.9, 1.65]        # = 9.8 in usable
        aligns = [None, WD_ALIGN_PARAGRAPH.CENTER, None, None, None, None, WD_ALIGN_PARAGRAPH.RIGHT, None]
    else:
        headers = ["RFI", "PRI", "TO", "STATUS", "QUESTION", "CARRIED IN BID"]
        widths = [0.7, 0.5, 0.65, 0.75, 4.6, 2.6]
        aligns = [None, WD_ALIGN_PARAGRAPH.CENTER, None, None, None, None]
    table = _grid_table(doc, headers, widths, size=9, aligns=aligns)

    rfis = sorted(takeoff.rfis, key=lambda r: _code_key(r.code))
    for r in rfis:
        question = [(r.subject or BLANK, {"bold": True, "after": 2}), r.question or BLANK]
        if r.answer:
            question.append((f"Answer: {r.answer}", {"italic": True, "after": 0}))
        cells = [r.code, r.priority, r.to or BLANK, r.status, question, r.carried or BLANK]
        fills = [None, PRI_FILL.get(r.priority), None, None, None, None]
        bolds = [True, True, False, False, False, False]
        if internal:
            where = [w.strip() for w in (r.where_flagged or "").split(";") if w.strip()] or [BLANK]
            cells += [f"{r.exposure_lbs:,.0f}", where]
            fills += [None, None]
            bolds += [False, False]
        _add_row(table, widths, cells, size=9, fills=fills, aligns=aligns, bolds=bolds)
    if not rfis:
        _text(doc, "No RFIs at this time.", size=9, italic=True, before=4)

    if internal:
        _heading(doc, "WAS / NOW", before=8)
        if takeoff.revisions:
            rw = [0.8, 1.0, 1.1, 1.1, 1.0, 4.8]
            ra = [None, None, WD_ALIGN_PARAGRAPH.RIGHT, WD_ALIGN_PARAGRAPH.RIGHT, WD_ALIGN_PARAGRAPH.RIGHT, None]
            rt = _grid_table(doc, ["REV", "DATE", "WAS lb", "NOW lb", "Δ", "NOTE"], rw, size=9, aligns=ra)
            for n, rev in enumerate(takeoff.revisions):
                delta = (rev.now_lbs - rev.was_lbs) if (rev.was_lbs is not None and rev.now_lbs is not None) else None
                cells = [rev.rev, rev.date,
                         "" if rev.was_lbs is None else _lb(rev.was_lbs),
                         "" if rev.now_lbs is None else _lb(rev.now_lbs),
                         "" if delta is None else f"{delta:+,.1f}",
                         rev.note]
                _add_row(rt, rw, cells, size=9, aligns=ra, zebra=bool(n % 2))
        else:
            _text(doc, "No revisions recorded.", size=9, italic=True)
        t = takeoff.totals()
        exposure = sum(r.exposure_lbs for r in takeoff.rfis)
        _text(doc, f"Carried: {_lb(t['project'])} lb = {t['tons']:.2f} T; exposure flagged: {_lb(exposure)} lb",
              size=10, bold=True, before=6, after=0, keep_next=True)

    _signature(doc, takeoff, with_address=False)
    _footer(doc, f"{h.company} · Pre-bid RFI log · {_job_label(takeoff)} · {h.rev}", internal=internal)
    return _save(doc, out_path)


# ----------------------------------------------------------------------------- scope letter
def _tonnage_sentence(takeoff: Takeoff) -> str:
    t = takeoff.totals()
    cols, beams = t["pieces"]["columns"], t["pieces"]["beams"]
    return (f"Project tonnage approximately {t['tons']:.1f} tons ({cols + beams:,} pieces: {cols:,} columns, {beams:,} beams) "
            f"plus Misc Metals {t['misc_metals']:,.0f} lb (separate).")


def build_scope_letter(takeoff: Takeoff, out_path) -> str:
    """Structural steel scope letter (portrait). PRELIMINARY line while scope.preliminary; unit word on every quantity line."""
    h, sc = takeoff.header, takeoff.scope
    title = f"STRUCTURAL STEEL SCOPE — {_job_label(takeoff).upper()}"
    doc = _new_document(takeoff, landscape=False, title=title, margin_in=1.0)
    _letterhead(doc, takeoff)
    _text(doc, title, size=14, bold=True, color=NAVY, before=2, after=2)
    if sc.preliminary:
        _text(doc, "PRELIMINARY — subject to QC", size=11, bold=True, color=RED, after=4)
    _project_block(doc, takeoff, 1.1, 5.4)

    _heading(doc, "SCOPE INCLUDES")
    for line in sc.inclusions or [BLANK]:
        _text(doc, line, size=10, after=2, style="List Bullet")

    _heading(doc, "QUANTITIES")
    if sc.quantities:
        widths = [4.0, 1.1, 1.4]
        aligns = [None, WD_ALIGN_PARAGRAPH.CENTER, None]
        table = _grid_table(doc, ["SCOPE ITEM", "QUANTITY", "UNIT"], widths, size=10, aligns=aligns)
        for n, q in enumerate(sc.quantities):
            unit = (q.unit or "").strip() or "each"          # standards: the unit word on every line, never a bare number
            _add_row(table, widths, [q.item or BLANK, str(q.quantity).strip() or BLANK, unit], size=10, aligns=aligns, zebra=bool(n % 2))
    else:
        _text(doc, "Quantities to be confirmed.", size=10, italic=True)

    _text(doc, (sc.tonnage_statement or "").strip() or _tonnage_sentence(takeoff), size=10, bold=True, before=8, after=2)

    _heading(doc, "EXCLUSIONS")
    for line in sc.exclusions or [BLANK]:
        _text(doc, line, size=10, after=2, style="List Bullet")

    _heading(doc, "CLARIFICATIONS")
    for line in sc.clarifications or [BLANK]:
        _text(doc, line, size=10, after=2, style="List Bullet")

    _text(doc, CONTACT_LINE, size=10, before=12, keep_next=True)
    _signature(doc, takeoff, with_address=True)
    _footer(doc, f"{h.company} · Structural steel scope · {_job_label(takeoff)} · {h.rev}", preliminary=sc.preliminary)
    return _save(doc, out_path)


# ----------------------------------------------------------------------------- takeoff notes (markdown)
_PIECE_UNITS = {"EA", "SET", "PR", "PC", "PCS"}


def _kit_pieces(takeoff: Takeoff) -> str:
    """pieces column for the Detail Register row: EA/SET/PR counts, linear items reported in LF"""
    each = lf = 0.0
    for k in takeoff.kits:
        for i in k.items:
            if i.qty_applied is None:
                continue
            u = (i.unit or "").upper()
            if u in _PIECE_UNITS:
                each += i.qty_applied
            elif u == "LF":
                lf += i.qty_applied
    parts = ([f"{each:,.0f}"] if each else []) + ([f"{lf:,.0f} LF"] if lf else [])
    return " + ".join(parts) if parts else BLANK


def _md(s) -> str:
    """cell-safe text for a markdown table"""
    return _clean(s).replace("|", "/").replace("\n", " ").strip()


def build_notes_md(takeoff: Takeoff, out_path) -> str:
    """Markdown takeoff notes kept with the job (BSI_STANDARDS.md section 7)."""
    h = takeoff.header
    t = takeoff.totals()
    out: list[str] = []
    out.append(f"# {_job_label(takeoff)} — takeoff notes ({h.rev}, {h.date})")
    out.append("")
    set_bits = [f"**Set:** {h.set_description or BLANK}"]
    if h.source_files:
        set_bits.append(f"**Files:** {', '.join(h.source_files)}")
    set_bits.append(f"**Status:** {h.status or BLANK}")
    out.append("  \n".join(set_bits))
    out.append("")
    parties = [("Owner", h.owner), ("Architect", h.architect), ("SER", h.ser), ("GC", h.gc), ("Site", h.site), ("Bid due", h.bid_due)]
    out.append("**Parties:** " + " · ".join(f"{k}: {v or BLANK}" for k, v in parties))
    out.append("")

    out.append("## Results")
    out.append("")
    out.append("| Scope | lb | pcs |")
    out.append("|---|---:|---:|")
    anchors_ea = sum(a.total_ea for a in takeoff.anchors)
    bolts_ea = sum(b.total_ea for b in takeoff.bolts)
    parts_ea = sum(p.qty for p in takeoff.misc_parts)
    out.append(f"| Columns | {_lb(t['columns'])} | {t['pieces']['columns']:,} |")
    out.append(f"| Beams | {_lb(t['beams'])} | {t['pieces']['beams']:,} |")
    out.append(f"| Detail Register | {_lb(t['detail_register'])} | {_kit_pieces(takeoff)} |")
    out.append(f"| Misc Parts (net) | {_lb(t['misc_parts'])} | {parts_ea:,} |")
    out.append(f"| Anchor rods | {_lb(t['anchor_bolts'])} | {anchors_ea:,} |")
    out.append(f"| Field bolts | {_lb(t['field_bolts'])} | {bolts_ea:,} |")
    main = t["pieces"]["columns"] + t["pieces"]["beams"]
    out.append(f"| **PROJECT TOTAL** ({t['tons']:.2f} tons) | **{_lb(t['project'])}** | {main:,} columns + beams |")
    out.append("")
    out.append(f"**PROJECT TOTAL: {_lb(t['project'])} lb = {t['tons']:.2f} tons** (columns + beams + Detail Register + Misc Parts net + anchor rods + field bolts)")
    out.append("")
    out.append("Memo — not in the total:")
    out.append("")
    out.append(f"- Joists / deck: {_lb(t['memo'])} lb")
    for m in takeoff.memo:
        dims = f" × {ft_in(m.length_ft)}" if m.length_ft else ""
        wt = f" = {_lb(m.lbs)} lb" if m.lb_per_unit is not None else ""
        out.append(f"  - {_md(m.item)}: {m.qty:,.0f} {m.unit}{dims}{wt} ({m.sheet})")
    out.append(f"- Misc Metals (separate): {_lb(t['misc_metals'])} lb")
    for p in takeoff.misc_metals:
        dims = f", {ft_in(p.length_ft)}" if p.length_ft else ""
        out.append(f"  - {_md(p.size)}: {p.qty:,} × {_lb(p.lb_ea)} lb{dims} = {_lb(p.lbs)} lb" + (" (allowance)" if p.allowance else ""))
    out.append("")

    out.append("## What changed")
    out.append("")
    if takeoff.revisions:
        for r in takeoff.revisions:
            if r.was_lbs is not None and r.now_lbs is not None:
                chg = f" — WAS {_lb(r.was_lbs)} lb → NOW {_lb(r.now_lbs)} lb ({r.now_lbs - r.was_lbs:+,.1f} lb)"
            elif r.now_lbs is not None:
                chg = f" — NOW {_lb(r.now_lbs)} lb"
            elif r.was_lbs is not None:
                chg = f" — WAS {_lb(r.was_lbs)} lb"
            else:
                chg = ""
            out.append(f"- **{_md(r.rev)}** ({_md(r.date)}): {_md(r.note)}{chg}")
    else:
        out.append("- No revisions recorded.")
    out.append("")

    out.append("## Key calls")
    out.append("")
    out.extend([f"- {_md(a)}" for a in takeoff.assumptions] or ["- None recorded."])
    out.append("")

    out.append("## Sheet coverage")
    out.append("")
    if takeoff.sheets:
        out.append("| Sheet | Title | Status | Steel (Y/N) | Reviewed | Notes |")
        out.append("|---|---|---|:---:|:---:|---|")
        for s in takeoff.sheets:
            out.append(f"| {_md(s.number)} | {_md(s.title) or BLANK} | {_md(s.status)}{(' ' + _md(s.date)) if s.date else ''} | "
                       f"{_md(s.steel) or '?'} | {'yes' if s.reviewed else 'no'} | {_md(s.notes)} |")
    else:
        out.append("- No sheets recorded.")
    out.append("")

    out.append("## Open before bid")
    out.append("")
    open_rfis = sorted((r for r in takeoff.rfis if (r.status or "").upper() != "INFO"), key=lambda r: _code_key(r.code))
    for r in open_rfis:
        box = "x" if (r.status or "").upper() == "ANSWERED" else " "
        out.append(f"- [{box}] **{_md(r.code)}** ({_md(r.priority)}, {_md(r.to)}, {_md(r.status)}) {_md(r.subject)}")
    if not open_rfis:
        out.append("- None.")
    out.append("")

    out_path = os.fspath(out_path)
    d = os.path.dirname(out_path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(out))
    return out_path


# ----------------------------------------------------------------------------- all four
def build_all_docs(takeoff: Takeoff, out_dir, stem: str) -> dict:
    out_dir = os.fspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    p = lambda suffix: os.path.join(out_dir, f"{stem}_{suffix}")
    return {
        "rfi": build_rfi_log(takeoff, p("RFI_Log_BohlingSteel.docx"), internal=False),
        "rfi_internal": build_rfi_log(takeoff, p("RFI_Log_BohlingSteel_INTERNAL.docx"), internal=True),
        "scope": build_scope_letter(takeoff, p("Steel_Scope_BohlingSteel.docx")),
        "notes": build_notes_md(takeoff, p("takeoff_notes.md")),
    }
