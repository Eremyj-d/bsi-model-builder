# BSI Model Builder — user guide

## 1. What the app is for
Every Bohling takeoff now ends with a 3D model of the main steel in IFC. The app builds that model from the
**Model Geometry** table (tab 12 of the takeoff workbook) and checks it independently before you send it:

* to **Tekla PowerFab** — File → Import → Estimating (or Advance Bill) → IFC. In the Import Field Map, map
  `PRELIM_MARK` → Reference #. Unknown shape or grade spellings go through Translate Shapes/Grades once.
  Re-importing a revised model updates the items in place because every piece keeps the same GUID.
* to the **detailer** — the reference model to convert into native Tekla / SDS2 objects. They export the
  PowerFab Exchange package (`.pfxt`) for Production Control from their model; we do not write that file.

## 2. The three inputs

### Job file (`<Job>_job.json`) — *Setup…*
| field | what |
|---|---|
| Job name | as on the workbook header |
| Job code | 2–24 letters/digits, **constant across revisions** — it seeds every GUID |
| Building | optional |
| Takeoff revision | REV 0 / REV 0.1 … |
| Source | workbook file / drawing set the geometry came from |
| Datum | where 0,0,0 is and which way +X / +Y point — written onto the tab and into the IFC |
| Grids along +X / +Y | `tag = feet`, one per line — numbered grids along +X, lettered along +Y. Pseudo-grids (post stations, beam lines) are fine |
| Storeys | `name = feet` — real levels; leave blank to derive them from the beam T/STL values |

Feet can be typed as `25.5`, `25'-6"` or `25'-6 1/2"`.

### Geometry table — one row per PIECE
`MARK PIECE TYPE SIZE GRADE FINISH SHEET GRID LEVEL X1 Y1 Z1 X2 Y2 Z2 ROT CP LB_FT LBS RFI NOTES`

* Coordinates in **decimal feet** from the job datum; +Z up. On the workbook tab the visible cells show ft-in
  (nearest 1/8") and hidden decimal columns carry the numbers; the CSV carries decimals.
* **TYPE** → IFC class: COLUMN / POST → IfcColumn · BEAM / GIRDER / LINTEL / HEADER / JOIST → IfcBeam ·
  BRACE / GIRT / PURLIN / STRUT / KICKER / MEMBER / ANGLE / CHANNEL → IfcMember ·
  PLATE / BASEPLATE / BP / EMBED / CAP → IfcPlate.
* **Columns**: X1 Y1 Z1 = base-plate centre at the base elevation (T/FTG per the column-length rule),
  X2 Y2 = same, Z2 = T/STL. CP 5 (centre). ROT 0 = flanges parallel to +X, degrees CCW in plan.
* **Beams / members**: X1→X2 = work line at **top of steel**, end to end as measured. CP 8 (top centre) so the
  top flange sits at Z. ROT 0 = web vertical; right-hand rule about end 1 → end 2. Sloped members carry both Z's.
* **Plates**: X1 Y1 Z1 = centre of the plate's bottom face; SIZE `PL t x W x L` (inches, feet-inches OK for L);
  extruded +Z by t; ROT about Z. X2/Y2/Z2 blank.
* **SIZE** as written on the drawings: `W14x38`, `HSS5x5x5/16`, `HSS9.625x.500`, `L6x6x5/16`, `L3-1/2x3-1/2x1/4`,
  `C12x20.7`, `WT5x11`, `PIPE 8 SCH 40` / `6" SCH 80 PIPE`, `PL 3/4x18x1'-6"`. Any AISC v16 shape resolves;
  an unknown size stops the build (or is skipped with *Lenient*).
* **LB_FT**: the workbook's value (AISC weight if blank). **LBS**: blank for members (lb/ft × length); a given
  value is checked against lb/ft × length (±1 %). Plates: blank → t × W × L × 0.2836.
* **RFI**: BSI-xx codes ride into the IFC on every piece.

### Output folder
Blank = next to the geometry file. Existing outputs with the same stem are overwritten; the original
workbook is never modified (the option writes a *copy* `<Job>_Takeoff+Model.xlsx`).

## 3. Outputs
| file | what |
|---|---|
| `<Job>_Model.ifc` | IFC2x3 Coordination View 2.0, mm / kg. IfcProject → Site → Building → Storey per level; IfcGrid; one element per piece with a parametric profile (I, U, T, L, rectangular / circular hollow, rectangle), Name `MARK SIZE`, Tag = mark, material = grade, property sets `Pset_*Common`, `BSI_Takeoff` (job, rev, PRELIM_MARK, piece, type, size, grade, finish, sheet, grid, level, length ft-in, lb/ft, lbs, RFI, notes), `Tekla Common`, `BaseQuantities` (Length, NetWeight) |
| `<Job>_Model_manifest.csv` | mark / piece / GUID / class / size / grade / finish / length / lbs / end points — the reconciliation list |
| `<Job>_Model_views.png` | plan, elevation looking north, elevation looking west, isometric |
| `<Job>_Model_check.txt` | the check report |
| `<Job>_ModelGeometry.csv` | the rows read from the workbook tab |
| `<Job>_Takeoff+Model.xlsx` | (option) copy of the workbook with the Model Geometry tab regenerated |

## 4. The check — what PASS means
The checker re-opens the IFC and re-derives every end point from the file's own placements and extrusion
depths — it does not trust the build:
* schema validation, including the EXPRESS where-rules;
* every end point and length within **1/16"** of the geometry table;
* cardinal-point offsets (beams top-centre, columns centre);
* `PRELIM_MARK` and a material on every piece; profile family matches the size;
* nothing in the table missing from the IFC and nothing in the IFC missing from the table;
* piece counts and lbs by class.

`RESULT: FAIL` lists every failing piece. Fix the table (or the job file) and build again.

Scope reminder: the model is the main members plus the plates that sit at a known place on a member (base,
cap, bearing). Connection plates, anchor rods and bolts stay in the workbook / manual-entry list. The
modelled total is a cross-check against Column Tonnage + Beam Tonnage + those plates, not a tonnage line.

## 5. Re-check an existing IFC
*Re-check an existing IFC…* runs the checker on any IFC; if the Geometry field points at the matching table,
end points are compared, otherwise the file is checked on its own.

## 6. Troubleshooting
* **"cannot resolve size …"** — spell it the AISC way (see §2) or check the thickness fraction.
* **"LBS … vs lb/ft x length"** — the table's LBS disagrees with LB_FT × length by more than 1 %; one of them is stale.
* **"end points off"** on re-check — the table changed after the IFC was built; rebuild.
* **PowerFab asks to translate a shape** — map it once; it remembers. HSS sizes come through as `HSS5X5X5/16`,
  round HSS as `HSS9.625X0.500`, pipe as `PIPE8STD` / `PIPE6XS`.
* **SmartScreen** — the exe is unsigned; *More info → Run anyway*.
* Settings (last paths, window size) live in `%APPDATA%\BSI Model Builder\settings.json`; delete it to reset.

---

# Part 2 — Takeoff from drawings (0.2)

## 7. What the Takeoff page does
Drawings in → the same deliverables a Bohling takeoff session produces: the 12-tab takeoff workbook (Model
Geometry tab included), the pre-bid RFI log (external + INTERNAL), the PRELIMINARY scope letter, the takeoff
notes, the job file, and the IFC model with its check and views. The drawing reading runs through the Claude
API with BSI's own key; everything else (weights, totals, formulas, documents, the IFC) is computed by the app.

## 8. The API account — what's involved
* **Account**: console.anthropic.com. Separate from the claude.ai subscription; billed per use (tokens in and
  out), with a prepaid balance or a monthly invoice depending on how it is set up. One account for the company
  is enough; make the key under BSI's name, not a personal one.
* **Key**: Settings → API keys → Create key. Paste it once into the app (*API key…* on the Takeoff page). It is
  stored in **Windows Credential Manager** under "BSI Model Builder" — not in any job folder, not in the
  settings file. Anyone with the key can spend on the account, so treat it like a password; the Console lets
  you revoke and re-issue it any time.
* **Cost**: the app prints the token count and an estimated dollar figure per stage and per run. The rates it
  uses are a table in the app (defaults are placeholders — update them from the Console's pricing page). As a
  rough guide a full run over a 100–150-sheet set is in the single-digit dollars range at opus-class prices and
  well under that on a sonnet-class model; re-running the same set costs nothing because every stage answer is
  cached on disk next to the job (`.api_cache`). A changed sheet or an edited job note re-runs only the stages
  that see it.
* **Model**: the dropdown lists the current Claude models. The default is the strongest reading model
  (drawing reading is the hard part); choose a smaller one for a quick first pass.
* **Data**: pages are sent as images plus their text; nothing is used to train models under the API terms.
  Check the Console's data-retention settings if a client set is under NDA.

## 9. Running a takeoff
1. **Job** — name, code (seeds the GUIDs; keep it for the life of the job), building, revision, bid due.
2. **Drawings** — add every PDF you have: structural, architectural, mechanical / electrical / plumbing, civil,
   the project manual. Nothing is "reference only" until the app has looked at it.
3. **Output folder** — blank writes into a `Bohling Takeoff` folder next to the first PDF (the same place the
   session deliverables go on the U: drive).
4. **Job notes** — anything the reader must know up front ("base bid + Alt 1 only", "all steel galvanized per
   addendum 2", "ignore the Phase 2 wing").
5. **Run takeoff.** The log shows each stage: index (every page classified), notes (grades / finish rules),
   columns (schedule + foundation plan), framing (one call per framing sheet, with the app's own geometry pass
   on vector pages: grid-bubble calibration, label-to-line matching, measured lengths), details (one call per
   details / arch / MEP / civil sheet, full page plus four zoomed quarters), synthesis (RFI log, scope, Summary
   blocks). Then the deliverables are built and the IFC is checked.

## 10. Reviewing in Excel
The draft workbook is the takeoff of record — open it and work through it the way you would a session's
workbook:
* every row that depended on something the reader could not settle carries a **BSI-xx** code in its RFI column
  and appears in the Summary FLAGS table; the INTERNAL RFI log lists the exposure in lb;
* rows marked **WEIGHT NOT RESOLVED** are sizes the AISC lookup did not recognise — fix the size spelling or
  type the lb/ft;
* Detail Register items showing **NOT YET APPLIED** are details the reader found but could not count from the
  plans — type the quantity (yellow cell);
* the Finish Summary VARIANCE must read 0 and the Beam Detail check must say ✓ before anything goes out.
Then *Build documents + model from an edited workbook*: pick the edited workbook (and its `_takeoff.json`,
found automatically when it sits beside it). The IFC is rebuilt from your edited Model Geometry tab; the RFI log
and scope letter are re-issued from the takeoff JSON.

## 11. What the reader will and won't do
It follows the Bohling rules (`docs/BSI_STANDARDS.md`): count everything, no estimating, column length T/FTG
→ T/STL, slope correction, every sheet and every detail reviewed, standing scope calls, priority-coded RFIs in
confirm-or-correct wording. It does not know your precedents on a particular owner / architect unless you put
them in the job notes, and it cannot read what is not legible — those come back as RFIs, not guesses. Raster
(scanned) sheets get no geometry pass; members on them are read from the image and should be spot-checked.

## 12. Command line
```
BSI_Model_Builder_cli takeoff run S.pdf A.pdf M.pdf --job "Job name" --code CODE --out "U:\…\Bohling Takeoff" [--model …] [--notes "…"]
BSI_Model_Builder_cli takeoff docs --xlsx Job_Takeoff.xlsx --json Job_takeoff.json      # after the Excel review
BSI_Model_Builder_cli takeoff deliver --json Job_takeoff.json                            # rebuild everything from the JSON
BSI_Model_Builder_cli takeoff run … --mock tests\data\mock_responses                     # replay canned answers (no API)
```
