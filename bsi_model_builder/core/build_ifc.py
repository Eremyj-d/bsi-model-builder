#!/usr/bin/env python3
"""
build_ifc.py — Bohling Steel takeoff geometry -> IFC2x3 structural steel model.

Inputs
  job.json            project header, datum, grids, storeys  (see README / sample_job.json)
  <Job>_ModelGeometry.csv   one row per PIECE (see sample_geometry.csv for the column set)

Output
  <Job>_Model.ifc     IFC2x3 Coordination View 2.0 — IfcColumn / IfcBeam / IfcMember / IfcPlate with
                      parametric AISC profiles, IfcGrid, IfcBuildingStorey per T/STL, material = grade,
                      property set BSI_Takeoff (PRELIM_MARK etc.), BaseQuantities (Length, NetWeight),
                      stable GUIDs (uuid5 of job_code|mark|piece) so PowerFab re-imports update by GUID.
  <Job>_Model_manifest.csv   mark / GUID / class / size / length ft-in / lbs — for reconciliation.

Conventions (document these on the Model Geometry tab)
  Coordinates in DECIMAL FEET from the job datum (job.json "datum"). +Z up.
  Columns:  (X1,Y1,Z1) = base plate centre at the base elevation, (X2,Y2,Z2) = same X/Y at T/STL.
            CP 5 (centre). ROT 0 = flanges parallel to global +X (web along global Y); degrees, CCW looking down.
  Beams:    (X1,Y1,Z1)->(X2,Y2,Z2) = work line at TOP OF STEEL, end-to-end (gridline-to-gridline or as measured).
            CP 8 (top centre) so the top flange sits at Z. ROT 0 = web vertical; right-hand rule about end1->end2.
  Plates:   (X1,Y1,Z1) = centre of the plate's bottom face; SIZE "PL t x W x L"; extruded +Z by t; ROT about Z.
  Units written to the IFC: millimetres / kilograms (what Tekla and PowerFab expect); imperial values ride in BSI_Takeoff.

Usage
  python3 build_ifc.py --job job.json --geom Job_ModelGeometry.csv --out Job_Model.ifc
"""
from __future__ import annotations
import argparse, csv, json, math, os, sys, uuid, datetime
import numpy as np
import ifcopenshell, ifcopenshell.api, ifcopenshell.guid
import ifcopenshell.api.project, ifcopenshell.api.root, ifcopenshell.api.unit, ifcopenshell.api.context
import ifcopenshell.api.aggregate, ifcopenshell.api.spatial, ifcopenshell.api.geometry, ifcopenshell.api.pset
import ifcopenshell.api.material, ifcopenshell.api.owner
import ifcopenshell.api.owner.settings as owner_settings

from .aisc_profiles import resolve

FT = 304.8          # mm per foot
IN = 25.4           # mm per inch
LB = 0.45359237     # kg per lb

TYPE_TO_CLASS = {
    "COLUMN": "IfcColumn", "POST": "IfcColumn", "COL": "IfcColumn",
    "BEAM": "IfcBeam", "GIRDER": "IfcBeam", "LINTEL": "IfcBeam", "HEADER": "IfcBeam", "JOIST": "IfcBeam",
    "BRACE": "IfcMember", "GIRT": "IfcMember", "PURLIN": "IfcMember", "STRUT": "IfcMember", "KICKER": "IfcMember",
    "MEMBER": "IfcMember", "RAIL": "IfcMember", "ANGLE": "IfcMember", "CHANNEL": "IfcMember",
    "PLATE": "IfcPlate", "BASEPLATE": "IfcPlate", "BP": "IfcPlate", "EMBED": "IfcPlate", "CAP": "IfcPlate",
}
COMMON_PSET = {"IfcColumn": "Pset_ColumnCommon", "IfcBeam": "Pset_BeamCommon",
               "IfcMember": "Pset_MemberCommon", "IfcPlate": "Pset_PlateCommon"}


# ----------------------------------------------------------------------------- helpers
def ft_in(x: float) -> str:
    """decimal feet -> 13'-6 5/8\" (nearest 1/8\")"""
    neg = x < 0
    x = abs(x)
    q = int(round(x * 96))          # eighths of an inch
    ft, rem = divmod(q, 96)
    inch, eighth = divmod(rem, 8)
    frac = {0: "", 1: " 1/8", 2: " 1/4", 3: " 3/8", 4: " 1/2", 5: " 5/8", 6: " 3/4", 7: " 7/8"}[eighth]
    s = f"{ft}'-{inch}{frac}\""
    return ("-" if neg else "") + s


def guid_for(job_code: str, kind: str, key: str) -> str:
    return ifcopenshell.guid.compress(uuid.uuid5(uuid.NAMESPACE_URL, f"bsi.ifc|{job_code}|{kind}|{key}").hex)


def f_or_none(v):
    try:
        if v is None or str(v).strip() == "":
            return None
        return float(v)
    except Exception:
        return None


def unit(v):
    n = np.linalg.norm(v)
    return v / n if n else v


def rot_about(axis, vec, deg):
    """Rodrigues rotation of vec about unit axis by deg."""
    a = math.radians(deg)
    axis = unit(np.asarray(axis, float))
    return vec * math.cos(a) + np.cross(axis, vec) * math.sin(a) + axis * np.dot(axis, vec) * (1 - math.cos(a))


def placement_matrix(p1_mm, p2_mm, rot_deg, is_column):
    """4x4 matrix: local Z = member axis (extrusion), local Y = 'up'/web direction, local X = flange direction."""
    p1 = np.asarray(p1_mm, float); p2 = np.asarray(p2_mm, float)
    z = unit(p2 - p1)
    if is_column:
        z = np.array([0.0, 0.0, 1.0]) if z[2] >= 0 else np.array([0.0, 0.0, -1.0])
        x = np.array([1.0, 0.0, 0.0])
    else:
        up = np.array([0.0, 0.0, 1.0])
        if abs(np.dot(z, up)) > 0.999:   # vertical member typed as beam/member
            up = np.array([0.0, 1.0, 0.0])
        y = unit(up - np.dot(up, z) * z)
        x = unit(np.cross(y, z))
    if rot_deg:
        x = rot_about(z, x, rot_deg)
    y = unit(np.cross(z, x))
    m = np.eye(4)
    m[:3, 0] = x; m[:3, 1] = y; m[:3, 2] = z; m[:3, 3] = p1
    return m


# ----------------------------------------------------------------------------- profiles
class ProfileFactory:
    def __init__(self, f):
        self.f = f
        self.cache = {}

    def _pos(self):
        return self.f.createIfcAxis2Placement2D(self.f.createIfcCartesianPoint((0.0, 0.0)), None)

    def get(self, size_text: str):
        """returns (profile_entity, resolved dict). Raises ValueError when the size cannot be resolved."""
        key = size_text.strip().upper()
        if key in self.cache:
            return self.cache[key]
        r = resolve(size_text)
        if not r:
            raise ValueError(f"cannot resolve size '{size_text}'")
        fam, d, label = r["family"], r["dims"], r["label"]
        f = self.f
        if fam in ("W", "HP", "M", "S"):
            fillet = max(0.0, (d["k"] or 0) - d["tf"]) if d.get("k") else None
            p = f.createIfcIShapeProfileDef("AREA", label, self._pos(), d["bf"] * IN, d["d"] * IN, d["tw"] * IN, d["tf"] * IN,
                                           fillet * IN if fillet else None)
        elif fam in ("C", "MC"):
            fillet = max(0.0, (d["k"] or 0) - d["tf"]) if d.get("k") else None
            p = f.createIfcUShapeProfileDef("AREA", label, self._pos(), d["d"] * IN, d["bf"] * IN, d["tw"] * IN, d["tf"] * IN,
                                           fillet * IN if fillet else None, None, None)
        elif fam in ("WT", "MT", "ST"):
            p = f.createIfcTShapeProfileDef("AREA", label, self._pos(), d["d"] * IN, d["bf"] * IN, d["tw"] * IN, d["tf"] * IN,
                                           None, None, None, None, None, None)
        elif fam == "L":
            fillet = max(0.0, (d["k"] or 0) - d["t"]) if d.get("k") else None
            p = f.createIfcLShapeProfileDef("AREA", label, self._pos(), d["d"] * IN, d["b"] * IN, d["t"] * IN,
                                           fillet * IN if fillet else None, None, None, None)
        elif fam == "HSS_RECT":
            t = d["t"] * IN
            p = f.createIfcRectangleHollowProfileDef("AREA", label, self._pos(), d["B"] * IN, d["Ht"] * IN, t, t, 2 * t)
        elif fam in ("HSS_ROUND", "PIPE"):
            p = f.createIfcCircleHollowProfileDef("AREA", label, self._pos(), d["OD"] * IN / 2.0, d["t"] * IN)
        elif fam == "PL":
            if not (d.get("t") and d.get("w") and d.get("l")):
                raise ValueError(f"plate '{size_text}' needs t x W x L")
            p = f.createIfcRectangleProfileDef("AREA", label, self._pos(), d["w"] * IN, d["l"] * IN)
        else:
            raise ValueError(f"unsupported family {fam} for '{size_text}'")
        self.cache[key] = (p, r)
        return self.cache[key]


# ----------------------------------------------------------------------------- main build
def build(job: dict, rows: list[dict], out_path: str, strict: bool = True) -> dict:
    code = job["job_code"]
    f = ifcopenshell.api.project.create_file(version="IFC2X3")

    # --- owner history (required by IFC2x3 IfcRoot)
    person = ifcopenshell.api.owner.add_person(f, identification="JD", family_name="Davis", given_name="Jeremy")
    org = ifcopenshell.api.owner.add_organisation(f, identification="BSI", name="Bohling Steel, Inc.")
    user = ifcopenshell.api.owner.add_person_and_organisation(f, person=person, organisation=org)
    app = ifcopenshell.api.owner.add_application(f, application_developer=org, version="1.0",
                                                 application_full_name="BSI Model Builder",
                                                 application_identifier="bsi_takeoff_ifc")
    owner_settings.get_user = lambda ifc: user
    owner_settings.get_application = lambda ifc: app

    # --- header
    f.header.file_description.description = ("ViewDefinition [CoordinationView_V2.0]",)
    f.header.file_name.name = os.path.basename(out_path)
    f.header.file_name.author = ("Jeremy Davis, Estimator",)
    f.header.file_name.organization = ("Bohling Steel, Inc.",)
    from .. import __version__
    f.header.file_name.originating_system = f"BSI Model Builder {__version__} (ifcopenshell {ifcopenshell.version})"
    f.header.file_name.authorization = "none"

    # --- project / units / contexts
    project = ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name=job["job"])
    project.GlobalId = guid_for(code, "project", code)
    project.Description = f"{job.get('rev','')} — {job.get('source','Bohling Steel takeoff')}".strip(" —")
    mm = ifcopenshell.api.unit.add_si_unit(f, unit_type="LENGTHUNIT", prefix="MILLI")
    m2 = ifcopenshell.api.unit.add_si_unit(f, unit_type="AREAUNIT")
    m3 = ifcopenshell.api.unit.add_si_unit(f, unit_type="VOLUMEUNIT")
    kg = ifcopenshell.api.unit.add_si_unit(f, unit_type="MASSUNIT", prefix="KILO")
    deg = ifcopenshell.api.unit.add_conversion_based_unit(f, name="degree")
    ifcopenshell.api.unit.assign_unit(f, units=[mm, m2, m3, kg, deg])
    model = ifcopenshell.api.context.add_context(f, context_type="Model")
    body = ifcopenshell.api.context.add_context(f, context_type="Model", context_identifier="Body",
                                                target_view="MODEL_VIEW", parent=model)
    plan = ifcopenshell.api.context.add_context(f, context_type="Plan")
    footprint = ifcopenshell.api.context.add_context(f, context_type="Plan", context_identifier="FootPrint",
                                                     target_view="PLAN_VIEW", parent=plan)

    # --- spatial structure
    site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name=job.get("site", job["job"]))
    site.GlobalId = guid_for(code, "site", code)
    bname = job.get("building") or job["job"]
    building = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuilding", name=bname)
    building.GlobalId = guid_for(code, "building", bname)
    building.Description = job.get("datum", {}).get("description", "")
    ifcopenshell.api.aggregate.assign_object(f, products=[site], relating_object=project)
    ifcopenshell.api.aggregate.assign_object(f, products=[building], relating_object=site)
    ifcopenshell.api.geometry.edit_object_placement(f, product=site, matrix=np.eye(4), is_si=False)
    ifcopenshell.api.geometry.edit_object_placement(f, product=building, matrix=np.eye(4), is_si=False)

    # storeys: from job.json; if none are given, derive them from the distinct beam T/STL levels
    storey_defs = [(s["name"], float(s["elev_ft"])) for s in job.get("storeys", [])]
    if not storey_defs:
        levels = set()
        for r in rows:
            if TYPE_TO_CLASS.get(r["TYPE"].strip().upper()) == "IfcBeam":
                for k in ("Z1", "Z2"):
                    z = f_or_none(r[k])
                    if z is not None:
                        levels.add(round(z, 3))
        base = min([f_or_none(r["Z1"]) for r in rows if f_or_none(r["Z1"]) is not None] or [0.0])
        storey_defs = [("BASE " + ft_in(base), base)] + [(f"T/STL {ft_in(z)}", z) for z in sorted(levels) if z > base + 0.02]
    storey_defs.sort(key=lambda t: t[1])
    storeys = []
    for name, elev_ft in storey_defs:
        st = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuildingStorey", name=name)
        st.GlobalId = guid_for(code, "storey", f"{elev_ft:.3f}")
        st.Elevation = elev_ft * FT
        m = np.eye(4); m[2, 3] = elev_ft * FT
        ifcopenshell.api.geometry.edit_object_placement(f, product=st, matrix=m, is_si=False)
        storeys.append((name, elev_ft, st))
    ifcopenshell.api.aggregate.assign_object(f, products=[s[2] for s in storeys], relating_object=building)

    def storey_for(z_ft: float, nearest: bool = False):
        """highest storey at or below z (members sit on the level they frame into); plates → nearest level"""
        if nearest:
            return min(storeys, key=lambda s: abs(s[1] - z_ft))[2]
        below = [s for s in storeys if s[1] <= z_ft + 0.05]
        return (below[-1] if below else storeys[0])[2]

    # --- grid
    grids = job.get("grids", {})
    xs = {k: float(v) for k, v in grids.get("X", {}).items()}
    ys = {k: float(v) for k, v in grids.get("Y", {}).items()}
    if xs and ys:
        allx = [f_or_none(r["X1"]) for r in rows] + [f_or_none(r["X2"]) for r in rows] + list(xs.values())
        ally = [f_or_none(r["Y1"]) for r in rows] + [f_or_none(r["Y2"]) for r in rows] + list(ys.values())
        allx = [v for v in allx if v is not None]; ally = [v for v in ally if v is not None]
        margin = 6.0
        x0, x1 = (min(allx) - margin) * FT, (max(allx) + margin) * FT
        y0, y1 = (min(ally) - margin) * FT, (max(ally) + margin) * FT
        uaxes, vaxes, curves = [], [], []
        for tag, xv in sorted(xs.items(), key=lambda kv: kv[1]):
            pl = f.createIfcPolyline([f.createIfcCartesianPoint((xv * FT, y0)), f.createIfcCartesianPoint((xv * FT, y1))])
            uaxes.append(f.createIfcGridAxis(str(tag), pl, True)); curves.append(pl)
        for tag, yv in sorted(ys.items(), key=lambda kv: kv[1]):
            pl = f.createIfcPolyline([f.createIfcCartesianPoint((x0, yv * FT)), f.createIfcCartesianPoint((x1, yv * FT))])
            vaxes.append(f.createIfcGridAxis(str(tag), pl, True)); curves.append(pl)
        grid = ifcopenshell.api.root.create_entity(f, ifc_class="IfcGrid", name="Structural grid")
        grid.GlobalId = guid_for(code, "grid", code)
        grid.UAxes = uaxes; grid.VAxes = vaxes
        shape = f.createIfcShapeRepresentation(footprint, "FootPrint", "GeometricCurveSet",
                                               [f.createIfcGeometricCurveSet(curves)])
        grid.Representation = f.createIfcProductDefinitionShape(None, None, [shape])
        ifcopenshell.api.spatial.assign_container(f, products=[grid], relating_structure=storeys[0][2])
        ifcopenshell.api.geometry.edit_object_placement(f, product=grid, matrix=np.eye(4), is_si=False)

    # --- members
    pf = ProfileFactory(f)
    materials = {}
    manifest, problems = [], []
    totals = {"IfcColumn": [0, 0.0], "IfcBeam": [0, 0.0], "IfcMember": [0, 0.0], "IfcPlate": [0, 0.0]}
    src = job.get("source", "Bohling Steel takeoff")
    for i, r in enumerate(rows, start=1):
        mark = (r.get("MARK") or f"M{i}").strip()
        piece = (r.get("PIECE") or "1").strip()
        typ = (r.get("TYPE") or "BEAM").strip().upper()
        cls = TYPE_TO_CLASS.get(typ)
        if not cls:
            problems.append(f"row {i} {mark}: unknown TYPE '{typ}'"); continue
        size = (r.get("SIZE") or "").strip()
        try:
            profile, res = pf.get(size)
        except ValueError as e:
            problems.append(f"row {i} {mark}: {e}"); continue
        p1 = [f_or_none(r["X1"]), f_or_none(r["Y1"]), f_or_none(r["Z1"])]
        p2 = [f_or_none(r["X2"]), f_or_none(r["Y2"]), f_or_none(r["Z2"])]
        rot = f_or_none(r.get("ROT")) or 0.0
        if cls == "IfcPlate":
            if None in p1:
                problems.append(f"row {i} {mark}: plate needs X1 Y1 Z1"); continue
            t_in = res["dims"]["t"]
            p2 = [p1[0], p1[1], p1[2] + t_in / 12.0]
        if None in p1 or None in p2:
            problems.append(f"row {i} {mark}: missing coordinates"); continue
        p1_mm = np.array(p1) * FT; p2_mm = np.array(p2) * FT
        length_mm = float(np.linalg.norm(p2_mm - p1_mm))
        if length_mm < 1.0:
            problems.append(f"row {i} {mark}: zero length"); continue
        length_ft = length_mm / FT
        cp = int(f_or_none(r.get("CP")) or (5 if cls in ("IfcColumn", "IfcPlate") else 8))
        plf = f_or_none(r.get("LB_FT")) or res["plf"]
        lbs = f_or_none(r.get("LBS"))
        if cls == "IfcPlate":
            d = res["dims"]; lbs_calc = d["t"] * d["w"] * d["l"] * 0.2836
        else:
            lbs_calc = (plf or 0.0) * length_ft
        if lbs is None:
            lbs = lbs_calc
        elif lbs_calc and abs(lbs - lbs_calc) > max(2.0, 0.01 * lbs_calc):
            problems.append(f"row {i} {mark}: LBS {lbs:.1f} vs lb/ft x length {lbs_calc:.1f} (check LB_FT or length)")

        e = ifcopenshell.api.root.create_entity(f, ifc_class=cls, name=f"{mark} {res['label']}")
        e.GlobalId = guid_for(code, cls, f"{mark}|{piece}")
        e.Tag = mark
        e.ObjectType = res["label"]
        e.Description = " ".join(x for x in [typ, (r.get("GRID") or "").strip(), (r.get("LEVEL") or "").strip()] if x)

        # container: columns & plates by base elevation, everything else by its T/STL (higher end)
        zc = p1[2] if cls in ("IfcColumn", "IfcPlate") else max(p1[2], p2[2])
        ifcopenshell.api.spatial.assign_container(f, products=[e], relating_structure=storey_for(zc, nearest=(cls == "IfcPlate")))

        # NOTE: add_profile_representation takes depth in SI metres and converts to project units (mm)
        rep = ifcopenshell.api.geometry.add_profile_representation(f, context=body, profile=profile,
                                                                   depth=length_mm / 1000.0, cardinal_point=cp)
        ifcopenshell.api.geometry.assign_representation(f, product=e, representation=rep)
        mtx = placement_matrix(p1_mm, p2_mm, rot, is_column=(cls in ("IfcColumn", "IfcPlate")))
        ifcopenshell.api.geometry.edit_object_placement(f, product=e, matrix=mtx, is_si=False)

        grade = (r.get("GRADE") or "").strip() or "A992"
        if grade not in materials:
            materials[grade] = ifcopenshell.api.material.add_material(f, name=grade)
        ifcopenshell.api.material.assign_material(f, products=[e], type="IfcMaterial", material=materials[grade])

        finish = (r.get("FINISH") or "").strip()
        common = ifcopenshell.api.pset.add_pset(f, product=e, name=COMMON_PSET[cls])
        ifcopenshell.api.pset.edit_pset(f, pset=common, properties={"Reference": res["label"], "LoadBearing": True,
                                                                     "IsExternal": finish.upper().startswith("GALV")})
        bsi = ifcopenshell.api.pset.add_pset(f, product=e, name="BSI_Takeoff")
        ifcopenshell.api.pset.edit_pset(f, pset=bsi, properties={
            "JOB": job["job"], "JOB_CODE": code, "REV": job.get("rev", ""), "PRELIM_MARK": mark, "MARK": mark,
            "PIECE": piece, "TYPE": typ, "SIZE": res["label"], "SIZE_AS_DRAWN": size, "GRADE": grade, "FINISH": finish,
            "SHEET": (r.get("SHEET") or "").strip(), "GRID": (r.get("GRID") or "").strip(),
            "LEVEL": (r.get("LEVEL") or "").strip(), "LENGTH_FT_IN": ft_in(length_ft), "LENGTH_FT": round(length_ft, 4),
            "LB_PER_FT": round(plf, 3) if plf else 0.0, "LBS": round(lbs, 1), "RFI": (r.get("RFI") or "").strip(),
            "NOTES": (r.get("NOTES") or "").strip(), "SOURCE": src})
        tk = ifcopenshell.api.pset.add_pset(f, product=e, name="Tekla Common")
        ifcopenshell.api.pset.edit_pset(f, pset=tk, properties={"Material": grade, "Profile": res["label"],
                                                                 "Finish": finish, "Phase": 1, "PRELIM_MARK": mark})
        qto = ifcopenshell.api.pset.add_qto(f, product=e, name="BaseQuantities")
        qto.Quantities = [f.createIfcQuantityLength("Length", "member length end to end", None, round(length_mm, 1)),
                          f.createIfcQuantityWeight("NetWeight", "lb/ft x length (takeoff weight)", None, round(lbs * LB, 3))]

        totals[cls][0] += 1; totals[cls][1] += lbs
        manifest.append({"MARK": mark, "PIECE": piece, "GUID": e.GlobalId, "CLASS": cls, "TYPE": typ, "SIZE": res["label"],
                         "GRADE": grade, "FINISH": finish, "LENGTH": ft_in(length_ft), "LENGTH_FT": round(length_ft, 4),
                         "LB_FT": plf, "LBS": round(lbs, 1), "X1": p1[0], "Y1": p1[1], "Z1": p1[2],
                         "X2": p2[0], "Y2": p2[1], "Z2": p2[2], "ROT": rot, "CP": cp, "SHEET": r.get("SHEET", ""),
                         "GRID": r.get("GRID", ""), "RFI": r.get("RFI", "")})

    if problems and strict:
        raise SystemExit("GEOMETRY PROBLEMS — fix before writing the IFC:\n  " + "\n  ".join(problems))

    # deterministic GUIDs on the relationship / property-set entities too, so two builds of the same
    # geometry are identical apart from timestamps (clean diffs; PowerFab matches elements by GUID anyway)
    for rel in f.by_type("IfcRelDefinesByProperties"):
        pdef = rel.RelatingPropertyDefinition
        key = f"{rel.RelatedObjects[0].GlobalId}|{pdef.Name}"
        pdef.GlobalId = guid_for(code, "pset", key)
        rel.GlobalId = guid_for(code, "relpset", key)
    for rel in f.by_type("IfcRelAssociatesMaterial"):
        rel.GlobalId = guid_for(code, "relmat", rel.RelatingMaterial.Name)
    for rel in f.by_type("IfcRelAggregates"):
        rel.GlobalId = guid_for(code, "relagg", rel.RelatingObject.GlobalId)
    for rel in f.by_type("IfcRelContainedInSpatialStructure"):
        rel.GlobalId = guid_for(code, "relcont", rel.RelatingStructure.GlobalId)
    f.write(out_path)
    man_path = os.path.splitext(out_path)[0] + "_manifest.csv"
    with open(man_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(manifest[0].keys()) if manifest else ["MARK"])
        w.writeheader(); w.writerows(manifest)
    return {"ifc": out_path, "manifest": man_path, "totals": totals, "problems": problems,
            "storeys": [(n, ft_in(e)) for n, e, _ in storeys], "pieces": len(manifest)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--geom", help="Model Geometry CSV")
    ap.add_argument("--xlsx", help="takeoff workbook — read the 'Model Geometry' tab instead of a CSV")
    ap.add_argument("--out", required=True)
    ap.add_argument("--lenient", action="store_true", help="write the IFC even if some rows fail (they are skipped)")
    a = ap.parse_args()
    with open(a.job) as fh:
        job = json.load(fh)
    if a.xlsx:
        from .geometry_tab import read_model_geometry_tab
        rows = read_model_geometry_tab(a.xlsx)
    elif a.geom:
        with open(a.geom, newline="") as fh:
            rows = [r for r in csv.DictReader(fh) if any((str(v) if v is not None else "").strip() for v in r.values())]
    else:
        raise SystemExit("give --geom <csv> or --xlsx <workbook>")
    res = build(job, rows, a.out, strict=not a.lenient)
    print(f"wrote {res['ifc']}  ({res['pieces']} pieces)")
    for cls, (n, lbs) in res["totals"].items():
        if n:
            print(f"  {cls:10s} {n:4d} pcs  {lbs:10,.0f} lb  {lbs/2000:7.2f} T")
    tot = sum(v[1] for v in res["totals"].values())
    print(f"  {'TOTAL':10s} {res['pieces']:4d} pcs  {tot:10,.0f} lb  {tot/2000:7.2f} T")
    print("  storeys:", ", ".join(f"{n} @ {e}" for n, e in res["storeys"]))
    if res["problems"]:
        print("  SKIPPED ROWS:"); [print("   ", p) for p in res["problems"]]


if __name__ == "__main__":
    main()
