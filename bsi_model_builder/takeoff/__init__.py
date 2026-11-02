"""
Phase 2 placeholder — takeoff from drawings through the Claude API.

Planned interface (not implemented in 0.1):
    from bsi_model_builder.takeoff import DrawingTakeoff
    t = DrawingTakeoff(api_key=..., model="claude-...")
    result = t.run(pdf_paths=[...], job=job_dict, progress=callback)
    # result.workbook_path  (11-tab BSI workbook + Model Geometry tab)
    # result.geometry_rows  (feeds core.pipeline.run)
    # result.rfi_items, result.scope_items

The drawing reading that Claude does today is bespoke per job (grid calibration, label/line matching,
section-cut application). Phase 2 turns the repeatable part of that into prompts + a fixed output schema,
with the estimator reviewing the Model Geometry tab before the IFC is built.
"""
AVAILABLE = False
