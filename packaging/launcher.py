"""PyInstaller entry point — same as `python -m bsi_model_builder`."""
import os, sys
os.environ.setdefault("MPLBACKEND", "Agg")          # matplotlib renders to PNG only; Tk stays on the main thread
from bsi_model_builder.__main__ import main

if __name__ == "__main__":
    sys.exit(main() or 0)
