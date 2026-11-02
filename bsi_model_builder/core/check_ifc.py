"""
check_ifc — independent check of a BSI model IFC against its Model Geometry table.

Re-opens the IFC with ifcopenshell, re-derives every member's end points from the file's own
placements + extrusion depths (not from the build script), and reports:
  * schema validation (ifcopenshell.validate)
  * entity counts by class / storey
  * per-piece end-point + length agreement with the geometry rows (tolerance 1/16")
  * cardinal-point offsets (beams CP 8 top-centre, columns CP 5 centre)
  * PRELIM_MARK present on every piece; material (grade) assigned; profile family check
  * lbs totals by class
  * PNG views: plan, two elevations, isometric

    result = check(ifc_path, geom_rows=None, png_path=None)
    result.ok, result.fails, result.warns, result.lines (text report), result.totals, result.png
"""
from __future__ import annotations
import io, logging, os
from dataclasses import dataclass, field
import numpy as np
import ifcopenshell, ifcopenshell.util.placement, ifcopenshell.util.element, ifcopenshell.validate

FT = 304.8
TOL_MM = 25.4 / 16  # 1/16"
CLASSES = ["IfcColumn", "IfcBeam", "IfcMember", "IfcPlate"]


def ft_in(x: float) -> str:
    """decimal feet -> 13'-6 5/8\" (nearest 1/8\")"""
    neg = x < 0; x = abs(x)
    q = int(round(x * 96)); ft, rem = divmod(q, 96); inch, e8 = divmod(rem, 8)
    return ("-" if neg else "") + f"{ft}'-{inch}{ {0:'',1:' 1/8',2:' 1/4',3:' 3/8',4:' 1/2',5:' 5/8',6:' 3/4',7:' 7/8'}[e8]}\""


@dataclass
class CheckResult:
    ifc: str
    ok: bool = False
    fails: list = field(default_factory=list)
    warns: list = field(default_factory=list)
    lines: list = field(default_factory=list)       # human-readable report lines
    totals: dict = field(default_factory=dict)      # class -> [pieces, lbs]
    pieces: int = 0
    grand_lbs: float = 0.0
    storeys: list = field(default_factory=list)
    png: str | None = None
    validate_messages: list = field(default_factory=list)

    @property
    def report(self) -> str:
        out = list(self.lines)
        out += [f"WARN {w}" for w in self.warns] + [f"FAIL {x}" for x in self.fails]
        out.append("RESULT: " + ("PASS" if self.ok else f"FAIL ({len(self.fails)})"))
        return "\n".join(out)


def member_axis(f, e):
    """absolute (p1, p2) in mm from placement + IfcExtrudedAreaSolid depth; None if not a simple extrusion"""
    m = ifcopenshell.util.placement.get_local_placement(e.ObjectPlacement)
    rep = e.Representation
    if not rep:
        return None
    for r in rep.Representations:
        for item in r.Items:
            if item.is_a("IfcExtrudedAreaSolid"):
                depth = item.Depth
                d = np.array(item.ExtrudedDirection.DirectionRatios, float)
                pos = item.Position
                loc = np.array(pos.Location.Coordinates, float) if pos else np.zeros(3)
                zax = np.array(pos.Axis.DirectionRatios, float) if (pos and pos.Axis) else np.array([0, 0, 1.0])
                # work line = object placement origin along the extrusion axis; the profile's XY
                # Position offset is the cardinal-point shift and is checked separately
                p1_local = np.array([0.0, 0.0, loc[2]])
                p2_local = p1_local + zax * depth * d[2]
                p1 = (m @ np.append(p1_local, 1.0))[:3]
                p2 = (m @ np.append(p2_local, 1.0))[:3]
                return p1, p2, item.SweptArea, (float(loc[0]), float(loc[1]))
    return None


def _family_ok(size: str, prof) -> bool:
    s = size.upper().replace(" ", "")
    if s.startswith("PL") or s.startswith("PLATE"):
        return prof.is_a("IfcRectangleProfileDef")
    if "PIPE" in s or "SCH" in s:
        return prof.is_a("IfcCircleHollowProfileDef")
    if s.startswith("HSS"):
        return prof.is_a() in ("IfcRectangleHollowProfileDef", "IfcCircleHollowProfileDef")
    if s.startswith("WT") or s.startswith("MT") or s.startswith("ST"):
        return prof.is_a("IfcTShapeProfileDef")
    if s.startswith("MC") or s.startswith("C"):
        return prof.is_a("IfcUShapeProfileDef")
    if s.startswith("HP") or s.startswith("W") or s.startswith("M") or s.startswith("S"):
        return prof.is_a("IfcIShapeProfileDef")
    if s.startswith("L"):
        return prof.is_a("IfcLShapeProfileDef")
    return True


def check(ifc_path: str, geom_rows: list[dict] | None = None, png_path: str | None = None,
          render_png: bool = True) -> CheckResult:
    res = CheckResult(ifc=ifc_path)
    f = ifcopenshell.open(ifc_path)
    res.lines.append(f"schema {f.schema}   header: {f.header.file_description.description}")

    # --- validation
    log = logging.getLogger("bsi.validate"); log.setLevel(logging.INFO); log.propagate = False
    buf = io.StringIO(); h = logging.StreamHandler(buf); log.addHandler(h)
    rules = True
    try:
        try:
            ifcopenshell.validate.validate(f, log, express_rules=True)
        except ImportError:            # the EXPRESS rule executor needs pytest's assertion rewriter
            rules = False
            buf.seek(0); buf.truncate()
            ifcopenshell.validate.validate(f, log, express_rules=False)
    finally:
        log.removeHandler(h)
    vtxt = [l for l in buf.getvalue().splitlines() if l.strip()]
    res.validate_messages = vtxt
    if vtxt:
        res.lines.append(f"VALIDATE: {len(vtxt)} message(s)")
        res.lines += ["    " + l[:160] for l in vtxt[:20]]
        res.fails.append(f"validate reported {len(vtxt)} issue(s)")
    else:
        res.lines.append("VALIDATE: no schema issues" + (" (EXPRESS rules checked)" if rules else " (EXPRESS rules skipped — pytest not available)"))
    if not rules:
        res.warns.append("EXPRESS where-rules not checked (pytest not installed); schema attributes and types were")

    # --- inventory
    elems = [e for c in CLASSES for e in f.by_type(c)]
    res.pieces = len(elems)
    res.lines.append(f"pieces: {len(elems)}  " + "  ".join(f"{c} {len(f.by_type(c))}" for c in CLASSES))
    storeys = sorted(f.by_type("IfcBuildingStorey"), key=lambda s: s.Elevation or 0)
    res.storeys = [(s.Name, (s.Elevation or 0) / FT) for s in storeys]
    res.lines.append("storeys: " + ", ".join(f"{n} ({ft_in(e)})" for n, e in res.storeys))
    g = f.by_type("IfcGrid")
    if g:
        res.lines.append(f"grid: U {[ax.AxisTag for ax in g[0].UAxes]}  V {[ax.AxisTag for ax in g[0].VAxes]}")

    geom = {}
    if geom_rows:
        for r in geom_rows:
            if str(r.get("MARK", "")).strip():
                geom[(str(r["MARK"]).strip(), str(r.get("PIECE") or "1").strip())] = r
    seen = set()
    axes_for_png = []
    for e in elems:
        ps = ifcopenshell.util.element.get_psets(e)
        bsi = ps.get("BSI_Takeoff", {})
        mark, piece = bsi.get("PRELIM_MARK"), str(bsi.get("PIECE", "1"))
        if not mark:
            res.fails.append(f"{e.is_a()} #{e.id()} {e.Name}: no PRELIM_MARK"); continue
        ax = member_axis(f, e)
        if not ax:
            res.fails.append(f"{mark}/{piece}: no extrusion found"); continue
        p1, p2, prof, cp_off = ax
        L = float(np.linalg.norm(p2 - p1))
        cls = e.is_a()
        # cardinal points
        if cls == "IfcBeam" and prof.is_a("IfcIShapeProfileDef"):
            exp = -prof.OverallDepth / 2.0
            if abs(cp_off[1] - exp) > 0.5 or abs(cp_off[0]) > 0.5:
                res.fails.append(f"{mark}/{piece}: CP8 offset {cp_off} expected (0, {exp:.1f})")
        if cls == "IfcBeam" and prof.is_a("IfcRectangleHollowProfileDef"):
            exp = -prof.YDim / 2.0
            if abs(cp_off[1] - exp) > 0.5 or abs(cp_off[0]) > 0.5:
                res.fails.append(f"{mark}/{piece}: CP8 offset {cp_off} expected (0, {exp:.1f})")
        if cls == "IfcColumn" and (abs(cp_off[0]) > 0.5 or abs(cp_off[1]) > 0.5):
            res.fails.append(f"{mark}/{piece}: column CP5 offset {cp_off} expected (0, 0)")
        mat = ifcopenshell.util.element.get_material(e)
        grade = mat.Name if mat else None
        if not grade:
            res.fails.append(f"{mark}/{piece}: no material")
        res.totals.setdefault(cls, [0, 0.0]); res.totals[cls][0] += 1; res.totals[cls][1] += float(bsi.get("LBS", 0) or 0)
        st = ifcopenshell.util.element.get_container(e)
        axes_for_png.append((p1 / FT, p2 / FT, cls, mark))
        key = (mark, piece)
        if geom:
            r = geom.get(key)
            if not r:
                res.fails.append(f"{mark}/{piece}: in IFC but not in geometry table"); continue
            seen.add(key)
            try:
                c1 = np.array([float(r["X1"]), float(r["Y1"]), float(r["Z1"])]) * FT
            except Exception:
                res.fails.append(f"{mark}/{piece}: geometry row has no X1 Y1 Z1"); continue
            if cls == "IfcPlate":
                if np.linalg.norm(p1 - c1) > TOL_MM:
                    res.fails.append(f"{mark}/{piece}: plate origin off by {np.linalg.norm(p1-c1):.1f} mm")
            else:
                try:
                    c2 = np.array([float(r["X2"]), float(r["Y2"]), float(r["Z2"])]) * FT
                except Exception:
                    res.fails.append(f"{mark}/{piece}: geometry row has no X2 Y2 Z2"); continue
                d1 = np.linalg.norm(p1 - c1); d2 = np.linalg.norm(p2 - c2)
                if d1 > TOL_MM or d2 > TOL_MM:
                    res.fails.append(f"{mark}/{piece}: end points off by {d1:.1f} / {d2:.1f} mm")
                Lcsv = np.linalg.norm(c2 - c1)
                if abs(L - Lcsv) > TOL_MM:
                    res.fails.append(f"{mark}/{piece}: length {L/FT:.4f} ft vs table {Lcsv/FT:.4f} ft")
            if not _family_ok(str(r.get("SIZE", "")), prof):
                res.fails.append(f"{mark}/{piece}: size {r.get('SIZE')} written as {prof.is_a()}")
        res.lines.append(f"  {cls[3:]:7s} {mark:8s}/{piece:<6s} {str(bsi.get('SIZE','')):16s} {grade or '-':10s} "
                         f"L={ft_in(L/FT):>13s} {float(bsi.get('LBS',0) or 0):9.1f} lb  {st.Name if st else '-'}")
    if geom:
        for k in sorted(set(geom) - seen):
            res.fails.append(f"{k[0]}/{k[1]}: in geometry table but not in IFC")

    res.lines.append("totals:")
    grand = 0.0
    for cls, (n, lbs) in res.totals.items():
        res.lines.append(f"  {cls:10s} {n:4d} pcs {lbs:10,.1f} lb {lbs/2000:7.2f} T"); grand += lbs
    res.grand_lbs = grand
    res.lines.append(f"  {'TOTAL':10s} {len(elems):4d} pcs {grand:10,.1f} lb {grand/2000:7.2f} T")

    # --- views
    if render_png:
        try:
            res.png = render_views(axes_for_png, g[0] if g else None,
                                   png_path or os.path.splitext(ifc_path)[0] + "_views.png",
                                   title=os.path.basename(ifc_path) + f" — {len(elems)} pieces, {grand/2000:.2f} T")
            res.lines.append("views: " + res.png)
        except Exception as ex:  # pragma: no cover
            res.warns.append(f"PNG views not rendered: {ex}")
    res.ok = not res.fails
    return res


def render_views(axes, grid, png: str, title: str = "") -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    col = {"IfcColumn": "#1F3864", "IfcBeam": "#2E75B6", "IfcMember": "#C55A11", "IfcPlate": "#7F7F7F"}
    fig = plt.figure(figsize=(14, 10))
    ax1 = fig.add_subplot(2, 2, 1); ax2 = fig.add_subplot(2, 2, 2); ax3 = fig.add_subplot(2, 2, 3)
    ax4 = fig.add_subplot(2, 2, 4, projection="3d")
    label_cols = len([a for a in axes if a[2] == "IfcColumn"]) <= 120
    for p1, p2, cls, mark in axes:
        c = col.get(cls, "k"); lw = 2.2 if cls == "IfcColumn" else 1.4
        ax1.plot([p1[0], p2[0]], [p1[1], p2[1]], color=c, lw=lw)
        ax2.plot([p1[0], p2[0]], [p1[2], p2[2]], color=c, lw=lw)
        ax3.plot([p1[1], p2[1]], [p1[2], p2[2]], color=c, lw=lw)
        ax4.plot([p1[0], p2[0]], [p1[1], p2[1]], [p1[2], p2[2]], color=c, lw=lw)
        if cls == "IfcColumn":
            ax1.plot(p1[0], p1[1], "s", color=c, ms=5)
            if label_cols:
                ax1.annotate(mark, (p1[0], p1[1]), fontsize=6, xytext=(2, 2), textcoords="offset points")
    if grid is not None:
        for axn in grid.UAxes:
            x = axn.AxisCurve.Points[0].Coordinates[0] / FT
            ax1.axvline(x, color="#BBBBBB", lw=0.6, ls="--"); ax1.text(x, ax1.get_ylim()[1], axn.AxisTag, fontsize=7, color="#555")
        for axn in grid.VAxes:
            y = axn.AxisCurve.Points[0].Coordinates[1] / FT
            ax1.axhline(y, color="#BBBBBB", lw=0.6, ls="--"); ax1.text(ax1.get_xlim()[0], y, axn.AxisTag, fontsize=7, color="#555")
    for axx, t in ((ax1, "PLAN (X-Y, ft)"), (ax2, "ELEVATION looking north (X-Z, ft)"), (ax3, "ELEVATION looking west (Y-Z, ft)")):
        axx.set_title(t, fontsize=9); axx.set_aspect("equal"); axx.grid(alpha=.2)
    ax4.set_title("ISOMETRIC", fontsize=9); ax4.view_init(elev=28, azim=-55)
    fig.suptitle(title, fontsize=11)
    fig.tight_layout(); fig.savefig(png, dpi=130); plt.close(fig)
    return png


def main(argv=None):
    import argparse, csv, sys
    ap = argparse.ArgumentParser(description="check a BSI model IFC against its geometry table")
    ap.add_argument("ifc"); ap.add_argument("--geom"); ap.add_argument("--png")
    a = ap.parse_args(argv)
    rows = None
    if a.geom:
        with open(a.geom, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    r = check(a.ifc, rows, a.png)
    print(r.report)
    sys.exit(0 if r.ok else 1)


if __name__ == "__main__":
    main()
