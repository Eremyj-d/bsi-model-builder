# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — run from the repo root:  pyinstaller packaging/BSI_Model_Builder.spec
import os, sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
datas, binaries, hiddenimports = [], [], []
for pkg in ("ifcopenshell", "matplotlib", "PIL", "numpy", "openpyxl"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h
hiddenimports += collect_submodules("bsi_model_builder") + ["_pytest", "_pytest.assertion", "_pytest.assertion.rewrite", "pytest"]
datas += [
    (os.path.join(ROOT, "bsi_model_builder", "data"), os.path.join("bsi_model_builder", "data")),
    (os.path.join(ROOT, "bsi_model_builder", "ui", "app_icon.png"), os.path.join("bsi_model_builder", "ui")),
    (os.path.join(ROOT, "bsi_model_builder", "ui", "app_icon.ico"), os.path.join("bsi_model_builder", "ui")),
]
block_cipher = None

a = Analysis([os.path.join(ROOT, "packaging", "launcher.py")],
             pathex=[ROOT], binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             hookspath=[], runtime_hooks=[], excludes=["tkinter.test", "test", "unittest"],
             noarchive=False, cipher=block_cipher)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
ICON = os.path.join(ROOT, "bsi_model_builder", "ui", "app_icon.ico")
# windowed app (double-click) + console twin for the command line / CI selftest, sharing one bundle folder
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="BSI_Model_Builder",
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False, icon=ICON)
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name="BSI_Model_Builder_cli",
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=True, icon=ICON)
coll = COLLECT(exe, cli, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name="BSI_Model_Builder")
