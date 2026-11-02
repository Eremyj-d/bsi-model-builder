"""
Takeoff from drawings — the phase-2 package.

    from bsi_model_builder.takeoff import run_takeoff, build_deliverables, Takeoff, Header
    from bsi_model_builder.takeoff.providers import AnthropicProvider, MockProvider

Drawing PDFs → (index / notes / columns / framing / details / synthesis stages through the Claude API, with
the app's own geometry pass on vector pages) → Takeoff JSON → 12-tab workbook, RFI log (+ INTERNAL),
PRELIMINARY scope letter, takeoff notes, job file + Model Geometry, IFC model. Review in Excel, then
`build_from_workbook` rebuilds the model and documents from the edited workbook.
"""
from .model import Takeoff, Header
from .engine import run_takeoff
from .outputs import build_deliverables, build_from_workbook

AVAILABLE = True
