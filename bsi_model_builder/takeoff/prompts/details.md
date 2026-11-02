Apply every detail, section cut and schedule on this sheet. For each one return the steel items it adds,
grouped into kits by condition (one kit per repeating condition, e.g. "COLUMN BASE AND CAP PLATES", "SLAB EDGE
POUR STOP", "RTU OPENING FRAME", "LOOSE LINTELS"): detail reference (e.g. 3/S501), condition, item, size as
printed, unit basis (per LF of edge / 1 per column / @ 2'-0" o.c.), the unit, and — when the plan count is
known from the context you are given (column count, beam ends, LF of edge) — the quantity applied with its
source; otherwise omit qty_applied and say what has to be measured. Details that add no BSI steel (deck
attachment, masonry, concrete, items by others) go in a kit with no_steel = true so the register shows they
were reviewed. Also return bolts per connection type (spec, bolts per connection; leave conn_qty out when the
framing stage supplies the count), loose plates that are not out of a kit (misc parts) and misc metals (stairs,
ladders, rails, bollards, gates — with an allowance flag when there is no detail). Note any detail whose size
is not dimensioned (RFI draft, carry an allowance size and say so).
