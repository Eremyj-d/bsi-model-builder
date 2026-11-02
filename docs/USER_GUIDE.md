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
