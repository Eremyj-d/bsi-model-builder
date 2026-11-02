# Bohling Steel takeoff standards — the spec for the builders and the extraction prompts

Consolidated from the BSI estimating project (Jeremy Davis, Estimator). Everything the app produces must follow
this. Where a rule says "hard rule", it has been missed before and must be audited before delivery.

## 1. Tonnage definitions
* **PROJECT TONNAGE** = Columns + Beams + Detail Register + Misc Parts (net) + Anchor Bolts + Field Bolts. Tons = lbs / 2000.
* **Misc Parts** = connection material that is *not* out of a detail kit: column base plates, plate washers,
  anything not covered by the Detail Register. The Summary note reads "+ Misc Parts (base plates + connection
  material)" — never "Misc Metals". Misc Parts is shown **net of** the Detail Register with a gold memo row
  pointing at the Detail Register total (not added).
* **Detail Register** (the "detail summary") = everything out of section cuts / details / schedules, in kits.
  Rolls to the Summary on its own line.
* **Misc Metals** (stairs, rails, ladders, bollards, gates, decorative) = EXCLUDED from tonnage, its own line below the total.
* **Open-web joists, joist girders, roof deck** = EXCLUDED, memo lines below the total (gold).
* Bohling does not bid a single building over 400 T — flag it.

## 2. Workbook — 12 tabs, in order
Every tab: row 1 title `PROJECT NAME | Building (if any) | TAB SUBJECT | STATUS` (navy fill 1F3864, white bold
Arial 12), row 2+ scope / references / material specs (small italic), blank row, then the column header row
(blue 2E75B6, white bold), then data with EAF1F8 / DEEAF1 zebra banding. Arial throughout. Gridlines off. Freeze
panes below the header. Formulas for every total / subtotal / rollup; blank (not zero) for empty cells.

1. **Summary** — (a) green ✓ INCLUDED / red ✗ EXCLUDED two-column block at the very top; (b) DRAWINGS RECEIVED
   TO DATE: SHEET | DESCRIPTION | STATUS | DATE; (c) TONNAGE SUMMARY: Columns / Beams / Detail Register /
   Misc Parts (net) / Anchor Bolts / Field Bolts → **PROJECT TOTAL** lbs and tons, then memo lines (gold):
   joists, deck, Misc Metals; cross-tab references use `IFERROR('Tab'!cell,0)` pointing at the fixed grand-total
   cell of each tab; (d) REVISION LOG: REV | DATE | WAS lbs | NOW lbs | Δ | NOTE; (e) PROJECT NOTES: owner /
   architect / SER / GC / site / bid due / set description; (f) ASSUMPTIONS; (g) **FLAGS** table mirroring the
   RFI log: RFI | PRI | TO | STATUS | SUBJECT | WHERE FLAGGED (tab: marks / rows) | LBS CARRIED (SUM over the
   flagged rows' lbs, Beam Detail rows not double-counted), cells filled by priority.
2. **Column Tonnage** — MARK / LOCATION | QTY | SIZE | BASE PLATE | HEIGHT (FT-IN) | LB/FT | COL LBS | TOTAL LBS |
   BP ELEV (T/FTG → T/STL) | ANCHORS | FINISH | GRADE | NOTES / SOURCE | RFI, hidden decimal HEIGHT helper
   driving the math; TOTAL row; BY SIZE SUMMARY (SUMIF) ; COLUMN GRAND TOTAL lbs / tons at a fixed cell.
3. **Beam Tonnage** — SUMMARY BY SHEET (SHEET | DESCRIPTION | PIECES | LBS | TONS); ROLLUP BY MEMBER one row
   per sheet × size × length: SIZE | SHEET | QTY | LB/FT | LENGTH (ft-in) | TOTAL LBS | FINISH | GRADE | NOTES |
   RFI with hidden decimal length; joist + deck memo rows (gold, not summed); BY SIZE SUMMARY; grand total.
4. **Anchor Bolt Summary** — LOCATION | MEMBER | AB DIAMETER | AB PER ITEM | ITEM QTY | TOTAL ABs | AB LENGTH |
   LB/EA | TOTAL LBS | FINISH (Plain/Galv) | GRADE | NOTES / SOURCE | RFI; groups Column ABs / Additional AB
   Groups / Lintel ABs; grand total.
5. **Field Bolts & Anchors** — CONNECTION TYPE | LOCATION | BOLT / ANCHOR SPEC | PER CONN. | CONN. QTY |
   TOTAL EA | LB/EA | TOTAL LBS | FINISH | NOTES / SOURCE | RFI; groups Beam-to-Beam Shear / Beam-on-Column
   Cap Plate / Moment / Brace / Post-installed; grand total.
6. **Misc Parts** — QTY | SHAPE | THICKNESS | SIZE / DIMENSIONS | LENGTH (ft-in) | LB/EA | TOTAL LBS | FINISH |
   GRADE | SOURCE / NOTES | MARK | RFI (MARK is a reference label, never the lead column; never lump shape +
   size + length in one cell); groups Base Plates, Plate Washers, then section-referenced items; gold memo row
   "Detail Register total (see tab) — not added"; grand total (net).
7. **Misc Metals** — same columns; stairs / ladders / rails / bollards / gates; separate deliverable.
8. **Detail Register** — DETAIL REF | CONDITION | ITEM | SIZE / SPEC | UNIT BASIS | LB PER UNIT | QTY APPLIED
   (**yellow input** FFF2CC) | UNIT | TOTAL LBS (formula = LB PER UNIT × QTY APPLIED, blank when QTY blank) |
   QTY SOURCE | NOTES | RFI; kits A, B, C … each with a title row (letter + title + refs), item rows, a Subtotal
   row; a closing kit (gold) listing details reviewed that add no new steel (no quantities); GRAND TOTAL rolling
   to the Summary; a "HOW TO USE THIS TAB" block at the bottom. Items whose QTY APPLIED is blank show "NOT YET
   APPLIED" in QTY SOURCE.
9. **Finish Summary** — ROLLUP BY FINISH linked to the other tabs with SUMIF over each tab's FINISH column:
   Primed subtotal, Galv subtotal, TOTAL FABRICATED; HELD OUT list (base plates? no — base plates are
   fabricated; held out = anchor rods, plate washers on rods, all field bolts and post-installed anchors — keyed
   manually in Fabtrol); RECONCILIATION: fabricated + held out vs Summary PROJECT TOTAL, **VARIANCE must read 0**
   (formula); PIECE COUNT check (columns, beams); GALVANIZED BUT UNQUANTIFIED list.
10. **Beam Detail — by Member** — SHEET | SIZE | STUDS / TAG | LENGTH (ft-in) | LB/FT | LBS | NOTE / FLAG |
    PLAN X (pt) | PLAN Y (pt) | RFI, one row per callout, hidden decimal length, total tying to Beam Tonnage
    (a ✓ / CHECK formula).
11. **S-Sheet Notes** — SHEET | NOTE, reference only.
12. **Model Geometry** — see the app's README (one row per piece, ft-in visible, hidden decimal helpers,
    LENGTH and LBS formulas, TOTAL row = modelled steel cross-check).

### Hard rules
* **Lengths in feet-inches in every visible cell** (including total-LF cells); hidden decimal helpers drive
  the math. Display formula (nearest 1/8"):
  `=IF(x="","",INT(ROUND(x*96,0)/96)&"'-"&INT(MOD(ROUND(x*96,0),96)/8)&CHOOSE(MOD(ROUND(x*96,0),8)+1,""," 1/8"," 1/4"," 3/8"," 1/2"," 5/8"," 3/4"," 7/8")&"""")`
* **FINISH** column (header exactly `FINISH`, never "Galv?"): `Primed` / `Galv` for shapes, plates, angles;
  `Plain` / `Galv` for bolts and anchors. Never yes/no, never a grade in the finish cell.
* Colours: ORANGE FCE4D6 = allowance / assumed / directed / verify · GOLD FFE699 = memo / excluded ·
  YELLOW FFF2CC = Detail Register inputs and RFI cells · GREEN E2EFDA / RED FBE2E2 = Summary inclusions /
  exclusions · RFI cells filled by priority: P1 F4CCCC, P2 FCE4D6, P3 FFF2CC, INFO E7E6E6.
* Every material row tied to an RFI shows its BSI-xx in the trailing RFI column (one or more codes).
* recalc must report 0 formula errors; Finish Summary VARIANCE 0; Beam Detail ties to Beam Tonnage.
* Cross-tab references point at fixed grand-total cells; never `insert_rows` on sheets with merges.

## 3. Material rules
* Grades (BSI standard unless the drawings say otherwise): W / WT / C / MC = A992 (C/MC often A36 — follow the
  notes); HSS = A500 Gr.C; plates, bars, angles = A572 Gr.50 (not A36 for angles ≤ 4" unless specified);
  anchor rods = F1554 Gr.55 weldable (verify — some projects Gr.36); field bolts A325-N; pipe A53 Gr.B.
* Finish default: interior steel Primed (shop prime SSPC-SP2); exterior / weather-exposed Galv (HDG) per the
  galvanizing note; anchor rods per the spec (often HDG).
* Weights: AISC Shapes Database v16 lb/ft; plates 0.2836 lb/in³ (= 40.8 lb/ft² per inch of thickness);
  bolts per standard tables (3/4" x 2 1/2" A325 ≈ 0.65 lb with nut + washer).
* Connection material per the details plus AISC to fill gaps: shear tabs 3 bolts W14–W18, 2 bolts W10–W12;
  moment connections per detail; always stiffeners, doublers, cap plates, clips, bent plates, kickers, shims.

## 4. Takeoff methodology (what the extraction must do)
* **Never estimate.** Count every member; take every length from gridline-to-gridline or labelled
  dimensions; no averaging, no "typical" spans. Not legible → PENDING + RFI.
* **Geometry method** on vector PDFs: calibrate grid bubbles (pt/ft; ~9.0 pt/ft at 1/8"=1'-0"), read beam
  labels with position + text direction, extract thick structural line segments (width ≥ ~0.85 pt), merge
  collinear, match labels to the nearest parallel line, read end points for true length. Outlier flags:
  > 30–35 % off the group median, < 2.5 ft, > ~45 ft single member. Rotated members: Euclidean length along the
  text direction.
* **Column length = top of footing → top of steel** (no deductions for piers, cap plates, seats); perimeter
  columns run full length through CMU stem walls; each footing's own T/FTG tag; show T/FTG and T/STL.
* **Slope correction** mandatory where T/STL differs between supports: √(horizontal² + rise²).
* **Every sheet is reviewed** — elevations (girts, bracing, wind columns), pipe-support plans, A-sheets
  (lintels, misc metals, shelf angles, ladders, rails, bollards), MEP (roof openings, RTU frames), civil
  (bollards, site rails), specs (Division 05: finish, certification, delegated design).
* **Every detail and section cut is applied** → Detail Register kits; decode symbol legends before counting.
* Lintels always steel scope (check the schedule; CMU lintel blocks are masonry); tilt-up panel openings get no
  steel lintels. Roof openings always itemized (RTU curbs, hatches, skylights, overruns, shafts). Post-installed
  anchors always itemized on Field Bolts with product and finish.
* Standing scope calls (carry as COUNTED with a "per precedent" note, still listed in the scope letter):
  arch shelf angles at water tables = BY BSI, galvanized; Titen HD at deck-edge / bridging angles = furnish +
  install by BSI; RTU curb support frames = BY BSI including "future" positions; roof ladders stay on Misc
  Metals as allowance lines.
* Stale-information audit before delivery: headers, RFI references, tonnage across workbook / letter, counts.

## 5. RFI log
* Numbered BSI-01 …; **priority-coded**: P1 affects tonnage / scope, P2 affects detailing / finish, P3 pricing
  awareness, INFO for the record; framed "confirm or correct" with the carried quantity stated; addressed TO
  SER / ARCH / GC; STATUS column (OPEN / ANSWERED / INFO).
* External docx on BSI letterhead: Bohling Steel, Inc. · 3410 Forest Brook Road, Lynchburg, VA 24501; title
  "PRE-BID RFI LOG — <Job>"; project block (owner, architect, SER, GC, set, date, rev); table RFI | PRI | TO |
  STATUS | QUESTION (subject bold + question) | CARRIED IN BID; signed Jeremy Davis, Estimator.
* INTERNAL version adds EXPOSURE (lb) and WHERE FLAGGED IN WORKBOOK columns and a WAS / NOW footer
  (revision log). Never sent out.

## 6. Scope letter
* "STRUCTURAL STEEL SCOPE — <Job>", marked **PRELIMINARY** until QC complete; project block; SCOPE
  INCLUDES (bullets); QUANTITIES as a headed three-column table SCOPE ITEM | QUANTITY | UNIT with the unit
  word on every line (member counts — never bare "104 —"); one tonnage statement; EXCLUSIONS; CLARIFICATIONS
  (no assumptions / RFI content beyond a reference); signed Jeremy Davis, Estimator, Bohling Steel, Inc.

## 7. Takeoff notes (markdown, kept with the job)
Set and parties · result table (scope / lb / pcs) · what changed per revision (WAS → NOW) · key calls · sheet
coverage · open items before bid.

## 8. Model Geometry / IFC
See `docs/USER_GUIDE.md` §2 — one row per piece; columns base-plate centre → T/STL (CP 5); beams work line at
top of steel (CP 8); plates centre of bottom face; decimal feet from the job datum.
