# BSI Model Builder

Windows desktop app for Bohling Steel estimating: turns the **Model Geometry** table of a takeoff into
**`<Job>_Model.ifc`** — an IFC2x3 structural steel model with parametric AISC profiles — plus a manifest,
an independent check report and plan / elevation / isometric views.

The IFC imports straight into **Tekla PowerFab** Estimating / Advance Bill (map `PRELIM_MARK` → Reference #)
and goes to the **detailer** as the reference model for shop drawings once a job is booked.

No AI, no API key, no network: the app runs entirely on the PC.

## Install (Windows)
1. Download `BSI_Model_Builder_v<version>_win64.zip` from the Releases page.
2. Unzip anywhere (e.g. `C:\Tools\BSI_Model_Builder\`). No installer, no admin rights.
3. Double-click `BSI_Model_Builder.exe`. (`BSI_Model_Builder_cli.exe` is the same program for the command line.)

Windows SmartScreen may warn the first time because the exe is not code-signed — *More info → Run anyway*.

## Use
1. **Job file** — `Setup…` to create or edit (`<Job>_job.json`): name, job code, revision, datum text, grid
   coordinates, storeys. The job code seeds every GUID: keep it the same across revisions so PowerFab
   re-imports update items instead of duplicating them.
2. **Geometry** — the takeoff workbook (its *Model Geometry* tab) or a CSV with the same columns.
   `Template…` writes an empty job file + Model Geometry workbook to fill in.
3. **Build model** — writes into the output folder (default: next to the geometry file):
   `<Job>_Model.ifc`, `_Model_manifest.csv`, `_Model_views.png`, `_Model_check.txt`,
   `_ModelGeometry.csv` and (option) `_Takeoff+Model.xlsx` carrying the Model Geometry tab.
4. Read the **Check report**. Deliver only on `RESULT: PASS`.

Full conventions (coordinates, cardinal points, rotations, sizes) are on the app's *About* tab and in
[docs/USER_GUIDE.md](docs/USER_GUIDE.md).

## Command line
```
BSI_Model_Builder_cli build --job Job_job.json --xlsx Job_Takeoff.xlsx [--out DIR] [--tab] [--lenient]
BSI_Model_Builder_cli build --job Job_job.json --geom Job_ModelGeometry.csv
BSI_Model_Builder_cli check Job_Model.ifc --geom Job_ModelGeometry.csv
BSI_Model_Builder_cli template --out DIR --name "Job name"
BSI_Model_Builder_cli selftest
```

## Develop
```
pip install -r requirements.txt
python -m pytest -q                      # 7 tests: profiles, job file, synthetic frame, GUID stability, Phoenix Bristol, bad rows, tamper detection
python -m bsi_model_builder              # the window
python -m bsi_model_builder selftest     # bundled 23-piece frame → PASS
pip install pyinstaller && pyinstaller --noconfirm --clean packaging/BSI_Model_Builder.spec   # dist/BSI_Model_Builder/
```
Python 3.11–3.13. Dependencies: ifcopenshell, openpyxl, numpy, matplotlib, pillow, pytest (ifcopenshell's EXPRESS rule checker uses it).

## Release
Tag and push: `git tag v0.1.1 && git push --tags`. GitHub Actions runs the tests on Ubuntu and Windows,
freezes the app with PyInstaller on a Windows runner, runs the frozen selftest, and attaches
`BSI_Model_Builder_v0.1.1_win64.zip` to the release. Bump `__version__` in `bsi_model_builder/__init__.py`
and `version` in `pyproject.toml` first.

## Layout
```
bsi_model_builder/
  core/        aisc_profiles · geometry_tab · build_ifc · check_ifc · jobfile · pipeline
  ui/          app (Tkinter window) · jobeditor · settings
  takeoff/     phase 2 placeholder — takeoff from drawings through the Claude API
  data/aisc/   AISC Shapes Database v16.0 CSVs (from the Apache-2.0 steelpy package)
  data/selftest/  bundled synthetic frame
  cli.py · selftest.py · __main__.py
packaging/     PyInstaller spec, launcher, headless UI smoke test (xvfb)
tests/         pytest suite + Phoenix Bristol fixture
docs/          USER_GUIDE.md
.github/workflows/build.yml
```

## Roadmap
- **0.1** (this) — IFC model step: Model Geometry → IFC + check + views. Shakedown job: Phoenix Bristol TN (379 pieces).
- **0.2** — Phase 2: takeoff from drawings inside the app through the Claude API (drawings in → 12-tab
  workbook + Model Geometry out → estimator review → Build). Interface sketched in `bsi_model_builder/takeoff/`.
- Wishlist: embedded 3D viewer; IFC4 export option; direct write into the takeoff workbook in place.

Internal tool of Bohling Steel, Inc. — Lynchburg, VA.
