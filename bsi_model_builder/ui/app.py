"""
BSI Model Builder — desktop window (Tkinter, no browser, no server).

Left: inputs (job file, geometry workbook / CSV, output folder, options) and the Build button.
Right: Log · Check report · Views · About.
"""
from __future__ import annotations
import os, queue, subprocess, sys, threading, webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from .. import __version__, __app_name__
from . import settings
from .jobeditor import JobEditor
from ..core.jobfile import load_job, save_job, new_job

NAVY, BLUE, LIGHT, GOLD, GREEN, RED = "#1F3864", "#2E75B6", "#EAF1F8", "#FFE699", "#2E7D32", "#C62828"


def open_path(p: str):
    try:
        if sys.platform.startswith("win"):
            os.startfile(p)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", p])
        else:
            subprocess.Popen(["xdg-open", p])
    except Exception as ex:
        messagebox.showerror(__app_name__, f"Could not open {p}\n{ex}")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{__app_name__} {__version__}")
        self.minsize(1100, 680)
        self.settings = settings.load()
        self.q: queue.Queue = queue.Queue()
        self.result = None
        self.job = None
        self._style()
        self._build()
        try:
            ico = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_icon.png")
            self._icon = tk.PhotoImage(file=ico); self.iconphoto(True, self._icon)
        except Exception:
            pass
        self.after(150, self._poll)
        try:
            self.geometry(self.settings.get("geometry", "1240x760"))
        except Exception:
            pass
        self.protocol("WM_DELETE_WINDOW", self._close)

    # ------------------------------------------------------------------ layout
    def _style(self):
        s = ttk.Style(self)
        try:
            s.theme_use("vista" if sys.platform.startswith("win") else "clam")
        except Exception:
            pass
        s.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), foreground="white", background=NAVY, padding=8)
        s.map("Accent.TButton", background=[("active", BLUE), ("disabled", "#9AA5B1")], foreground=[("disabled", "white")])
        s.configure("Title.TLabel", font=("Segoe UI", 15, "bold"), foreground=NAVY)
        s.configure("Sub.TLabel", font=("Segoe UI", 9), foreground="#555")
        s.configure("H.TLabel", font=("Segoe UI", 10, "bold"), foreground=NAVY)
        s.configure("Status.TLabel", background=LIGHT, padding=4)

    def _build(self):
        top = ttk.Frame(self, padding=(12, 10, 12, 4)); top.pack(fill="x")
        ttk.Label(top, text=__app_name__, style="Title.TLabel").pack(side="left")
        ttk.Label(top, text="   takeoff geometry → IFC model for Tekla PowerFab and the detailer", style="Sub.TLabel").pack(side="left", pady=(6, 0))
        ttk.Button(top, text="Help", command=self._help).pack(side="right")

        body = ttk.Panedwindow(self, orient="horizontal"); body.pack(fill="both", expand=True, padx=12, pady=6)
        left = ttk.Frame(body, padding=(0, 0, 8, 0), width=470); right = ttk.Frame(body)
        body.add(left, weight=0); body.add(right, weight=1)
        self.after(50, lambda: body.sashpos(0, 480))

        # ---- inputs
        ttk.Label(left, text="1.  Job file", style="H.TLabel").grid(row=0, column=0, sticky="w", pady=(2, 0))
        self.v_job = tk.StringVar(value=self.settings.get("job", ""))
        self._pathrow(left, 1, self.v_job, self._browse_job, extra=[("Setup…", self._edit_job)])
        ttk.Label(left, text="2.  Geometry — takeoff workbook (Model Geometry tab) or CSV", style="H.TLabel").grid(row=2, column=0, sticky="w", pady=(10, 0))
        self.v_geom = tk.StringVar(value=self.settings.get("geom", ""))
        self._pathrow(left, 3, self.v_geom, self._browse_geom, extra=[("Template…", self._template)])
        ttk.Label(left, text="3.  Output folder  (blank = next to the geometry file)", style="H.TLabel").grid(row=4, column=0, sticky="w", pady=(10, 0))
        self.v_out = tk.StringVar(value=self.settings.get("out", ""))
        self._pathrow(left, 5, self.v_out, self._browse_out, folder=True)

        opts = ttk.Frame(left); opts.grid(row=6, column=0, sticky="w", pady=(10, 0))
        self.v_tab = tk.BooleanVar(value=self.settings.get("tab", True))
        self.v_lenient = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="Also write a workbook copy carrying the Model Geometry tab", variable=self.v_tab).pack(anchor="w")
        ttk.Checkbutton(opts, text="Lenient — skip rows that fail instead of stopping", variable=self.v_lenient).pack(anchor="w")

        self.btn_build = ttk.Button(left, text="Build model", style="Accent.TButton", command=self._build_clicked)
        self.btn_build.grid(row=7, column=0, sticky="ew", pady=(16, 6))
        row = ttk.Frame(left); row.grid(row=8, column=0, sticky="ew")
        self.btn_open = ttk.Button(row, text="Open output folder", command=self._open_out, state="disabled"); self.btn_open.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.btn_ifc = ttk.Button(row, text="Open IFC", command=self._open_ifc, state="disabled"); self.btn_ifc.pack(side="left", fill="x", expand=True)
        ttk.Button(left, text="Re-check an existing IFC…", command=self._recheck).grid(row=9, column=0, sticky="ew", pady=(6, 0))

        self.summary = tk.Text(left, height=9, width=40, wrap="word", state="disabled", relief="flat", background=LIGHT, font=("Consolas", 9))
        self.summary.grid(row=10, column=0, sticky="nsew", pady=(14, 0))
        left.rowconfigure(10, weight=1); left.columnconfigure(0, weight=1)

        # ---- right: notebook
        self.nb = ttk.Notebook(right); self.nb.pack(fill="both", expand=True)
        self.log = self._textpage("Log")
        self.rep = self._textpage("Check report")
        self.views_frame = ttk.Frame(self.nb); self.nb.add(self.views_frame, text="Views")
        self.views_label = ttk.Label(self.views_frame, text="Plan / elevations / isometric appear here after a build.", anchor="center")
        self.views_label.pack(fill="both", expand=True)
        self.views_frame.bind("<Configure>", lambda e: self._show_png())
        about = self._textpage("About", wrap="word")
        self._set(about, ABOUT_TEXT)

        self.status = ttk.Label(self, text="Ready.", style="Status.TLabel", anchor="w"); self.status.pack(fill="x", side="bottom")

    def _pathrow(self, parent, row, var, browse, extra=(), folder=False):
        f = ttk.Frame(parent); f.grid(row=row, column=0, sticky="ew", pady=2)
        e = ttk.Entry(f, textvariable=var, width=30); e.pack(side="left", fill="x", expand=True)
        ttk.Button(f, text="Browse…", command=browse, width=10).pack(side="left", padx=(4, 0))
        for label, cmd in extra:
            ttk.Button(f, text=label, command=cmd, width=11).pack(side="left", padx=(4, 0))

    def _textpage(self, title, wrap="none"):
        fr = ttk.Frame(self.nb); self.nb.add(fr, text=title)
        t = tk.Text(fr, wrap=wrap, font=("Consolas", 9), state="disabled", padx=6, pady=4)
        ys = ttk.Scrollbar(fr, orient="vertical", command=t.yview); xs = ttk.Scrollbar(fr, orient="horizontal", command=t.xview)
        t.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        t.grid(row=0, column=0, sticky="nsew"); ys.grid(row=0, column=1, sticky="ns"); xs.grid(row=1, column=0, sticky="ew")
        fr.rowconfigure(0, weight=1); fr.columnconfigure(0, weight=1)
        t.tag_configure("pass", foreground=GREEN, font=("Consolas", 9, "bold"))
        t.tag_configure("fail", foreground=RED, font=("Consolas", 9, "bold"))
        t.tag_configure("warn", foreground="#B26A00")
        return t

    # ------------------------------------------------------------------ helpers
    def _set(self, widget, text, tag=None):
        widget.configure(state="normal"); widget.delete("1.0", "end"); widget.insert("1.0", text, tag); widget.configure(state="disabled")

    def _append(self, widget, text, tag=None):
        widget.configure(state="normal"); widget.insert("end", text + "\n", tag); widget.see("end"); widget.configure(state="disabled")

    def _save_settings(self):
        self.settings.update({"job": self.v_job.get(), "geom": self.v_geom.get(), "out": self.v_out.get(),
                              "tab": self.v_tab.get(), "geometry": self.geometry()})
        settings.save(self.settings)

    def _close(self):
        self._save_settings(); self.destroy()

    def _initial_dir(self, var):
        p = var.get().strip()
        if p and os.path.exists(os.path.dirname(p) if os.path.isfile(p) else p):
            return os.path.dirname(p) if os.path.isfile(p) else p
        for other in (self.v_geom, self.v_job, self.v_out):
            q = other.get().strip()
            if q and os.path.exists(q):
                return os.path.dirname(q) if os.path.isfile(q) else q
        return os.path.expanduser("~")

    # ------------------------------------------------------------------ actions
    def _browse_job(self):
        p = filedialog.askopenfilename(title="Job file", initialdir=self._initial_dir(self.v_job), filetypes=[("Job file", "*.json"), ("All", "*.*")])
        if p:
            self.v_job.set(p)

    def _browse_geom(self):
        p = filedialog.askopenfilename(title="Geometry — takeoff workbook or CSV", initialdir=self._initial_dir(self.v_geom),
                                       filetypes=[("Workbook or CSV", "*.xlsx *.xlsm *.csv"), ("Excel workbook", "*.xlsx *.xlsm"), ("CSV", "*.csv"), ("All", "*.*")])
        if p:
            self.v_geom.set(p)
            # pick up a job.json sitting next to it
            d = os.path.dirname(p)
            if not self.v_job.get().strip():
                for fn in sorted(os.listdir(d)):
                    if fn.lower().endswith("_job.json") or fn.lower() == "job.json":
                        self.v_job.set(os.path.join(d, fn)); break

    def _browse_out(self):
        p = filedialog.askdirectory(title="Output folder", initialdir=self._initial_dir(self.v_out))
        if p:
            self.v_out.set(p)

    def _new_job(self):
        def saved(job):
            d = self._initial_dir(self.v_geom)
            p = filedialog.asksaveasfilename(title="Save job file", initialdir=d, initialfile=f"{job['job_code']}_job.json",
                                             defaultextension=".json", filetypes=[("Job file", "*.json")])
            if p:
                save_job(job, p); self.v_job.set(p); self._append(self.log, f"saved {p}")
        JobEditor(self, new_job(), on_save=saved)

    def _edit_job(self):
        p = self.v_job.get().strip()
        if not p or not os.path.isfile(p):
            self._new_job(); return
        try:
            job = load_job(p)
        except Exception as ex:
            messagebox.showerror(__app_name__, f"Could not read {p}\n{ex}"); return
        JobEditor(self, job, on_save=lambda j: (save_job(j, p), self._append(self.log, f"saved {p}")))

    def _template(self):
        d = filedialog.askdirectory(title="Folder for the template", initialdir=self._initial_dir(self.v_geom))
        if not d:
            return
        from ..cli import cmd_template
        import types
        cmd_template(types.SimpleNamespace(out=d, name="New job"))
        self._append(self.log, f"template written in {d}: NEWJOB_job.json, NEWJOB_ModelGeometry.xlsx / .csv — fill the Model Geometry tab, edit the job file, then Build.")
        self.v_geom.set(os.path.join(d, "NEWJOB_ModelGeometry.xlsx")); self.v_job.set(os.path.join(d, "NEWJOB_job.json"))
        open_path(d)

    def _recheck(self):
        p = filedialog.askopenfilename(title="IFC to check", initialdir=self._initial_dir(self.v_geom), filetypes=[("IFC", "*.ifc"), ("All", "*.*")])
        if not p:
            return
        geom = self.v_geom.get().strip() or None
        self._run_bg(lambda: self._do_check(p, geom))

    def _build_clicked(self):
        job, geom = self.v_job.get().strip(), self.v_geom.get().strip()
        if not job or not os.path.isfile(job):
            messagebox.showwarning(__app_name__, "Pick a job file (or create one with New…)."); return
        if not geom or not os.path.isfile(geom):
            messagebox.showwarning(__app_name__, "Pick the takeoff workbook or the geometry CSV."); return
        out = self.v_out.get().strip() or None
        self._save_settings()
        self._set(self.log, ""); self._set(self.rep, ""); self._set(self.summary, "")
        self.nb.select(0)
        tab, lenient = bool(self.v_tab.get()), bool(self.v_lenient.get())   # read Tk vars on the main thread
        self._run_bg(lambda: self._do_build(job, geom, out, tab, lenient))

    # ------------------------------------------------------------------ background work
    def _run_bg(self, fn):
        self.btn_build.configure(state="disabled"); self.status.configure(text="Working…")
        threading.Thread(target=fn, daemon=True).start()

    def _do_build(self, job, geom, out, tab, lenient):
        from ..core.pipeline import run
        res = run(job, geom, out_dir=out, strict=not lenient, write_tab=tab, progress=lambda m: self.q.put(("log", m)))
        self.q.put(("done", res))

    def _do_check(self, ifc, geom):
        from ..core.check_ifc import check
        from ..core.pipeline import load_geometry, RunResult
        try:
            rows = None
            if geom:
                try:
                    rows = load_geometry(geom)[0]
                except Exception as ex:
                    self.q.put(("log", f"geometry not read ({ex}) — checking the IFC on its own"))
            self.q.put(("log", f"checking {ifc} …"))
            r = check(ifc, rows)
            res = RunResult(ok=r.ok, ifc=ifc, png=r.png, out_dir=os.path.dirname(ifc), pieces=r.pieces, totals=r.totals, check=r)
        except Exception as ex:
            import traceback
            res = RunResult(error=f"{type(ex).__name__}: {ex}\n{traceback.format_exc()}")
        self.q.put(("done", res))

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._append(self.log, payload); self.status.configure(text=payload)
                elif kind == "done":
                    self._finish(payload)
        except queue.Empty:
            pass
        self.after(150, self._poll)

    def _finish(self, res):
        self.result = res
        self.btn_build.configure(state="normal")
        if res.error:
            self._append(self.log, res.error, "fail"); self._set(self.summary, res.summary())
            self.status.configure(text="Build failed — see the Log."); self.nb.select(0)
            messagebox.showerror(__app_name__, res.error.splitlines()[0][:300]); return
        self._set(self.summary, res.summary() + (f"\n\n{res.elapsed:.1f} s" if res.elapsed else ""))
        if res.check:
            self._set(self.rep, res.check.report)
            # colour the verdict lines
            self.rep.configure(state="normal")
            for tag, needle in (("fail", "FAIL"), ("warn", "WARN")):
                idx = "1.0"
                while True:
                    idx = self.rep.search(needle, idx, stopindex="end")
                    if not idx:
                        break
                    self.rep.tag_add(tag, idx, f"{idx} lineend"); idx = f"{idx} lineend"
            last = self.rep.search("RESULT:", "1.0", stopindex="end")
            if last:
                self.rep.tag_add("pass" if res.check.ok else "fail", last, f"{last} lineend")
            self.rep.configure(state="disabled")
        for p in res.build_problems:
            self._append(self.log, "skipped: " + p, "warn")
        verdict = "PASS" if res.ok else "FAIL"
        self._append(self.log, f"RESULT: {verdict}", "pass" if res.ok else "fail")
        self.status.configure(text=f"{verdict} — {res.pieces} pieces, {res.grand_lbs/2000:.2f} T → {res.out_dir}")
        self.btn_open.configure(state="normal" if res.out_dir else "disabled")
        self.btn_ifc.configure(state="normal" if res.ifc else "disabled")
        self._show_png()
        self.nb.select(2 if res.ok else 1)

    def _show_png(self):
        res = self.result
        if not res or not res.png or not os.path.isfile(res.png):
            return
        try:
            from PIL import Image, ImageTk
            w = max(200, self.views_frame.winfo_width() - 8); h = max(200, self.views_frame.winfo_height() - 8)
            im = Image.open(res.png); im.thumbnail((w, h))
            self._photo = ImageTk.PhotoImage(im)
            self.views_label.configure(image=self._photo, text="")
        except Exception as ex:
            self.views_label.configure(text=f"views at {res.png}\n({ex})", image="")

    def _open_out(self):
        if self.result and self.result.out_dir:
            open_path(self.result.out_dir)

    def _open_ifc(self):
        if self.result and self.result.ifc:
            open_path(self.result.ifc)

    def _help(self):
        self.nb.select(3)


ABOUT_TEXT = f"""{__app_name__} {__version__}
Bohling Steel, Inc. — estimating

WHAT IT DOES
  Reads the Model Geometry table of a BSI takeoff (the workbook tab, or the CSV) and writes
  <Job>_Model.ifc — an IFC2x3 structural steel model with parametric AISC profiles — plus a manifest,
  a check report and plan / elevation / isometric views. The IFC imports into Tekla PowerFab Estimating
  and Advance Bill (map PRELIM_MARK → Reference #) and goes to the detailer as the reference model.

THE MODEL GEOMETRY TABLE  (one row per piece)
  MARK PIECE TYPE SIZE GRADE FINISH SHEET GRID LEVEL  X1 Y1 Z1  X2 Y2 Z2  ROT CP LB_FT LBS RFI NOTES
  Coordinates in DECIMAL FEET from the job datum (+Z up).  TYPE = COLUMN / POST / BEAM / GIRDER / LINTEL /
  BRACE / GIRT / PURLIN / STRUT / KICKER / PLATE / BASEPLATE / CAP / EMBED.
  Columns: base-plate centre at the base elevation → T/STL; CP 5; ROT 0 = flanges parallel to +X.
  Beams:   work line at TOP OF STEEL end to end; CP 8 (top centre); ROT 0 = web vertical.
  Plates:  centre of the bottom face; SIZE "PL t x W x L"; extruded +Z by t.
  SIZE as written on the drawings (W14x38, HSS5x5x5/16, HSS9.625x.500, L6x6x5/16, C12x20.7, PIPE 6 SCH 80).

THE JOB FILE
  Name, job code (seeds every GUID — keep it constant so PowerFab re-imports update instead of duplicate),
  revision, datum text, grid coordinates, storeys.  Setup… on the main window (new file when blank).

OUTPUTS  (in the output folder)
  <Job>_Model.ifc · <Job>_Model_manifest.csv · <Job>_Model_views.png · <Job>_Model_check.txt ·
  <Job>_ModelGeometry.csv (when the input was a workbook) · <Job>_Takeoff+Model.xlsx (option)

THE CHECK
  Re-opens the IFC and re-derives every end point from the file itself: schema validation, end points and
  lengths within 1/16" of the table, cardinal points, PRELIM_MARK + material on every piece, totals.
  Deliver only on RESULT: PASS.

SCOPE
  Main members and the plates that sit at a known place on a member (base, cap, bearing). Connection
  plates, anchor rods and bolts stay in the workbook / manual-entry list.

PHASE 2 (planned)
  Takeoff from drawings inside this app through the Claude API — drawings in, workbook + Model Geometry out,
  estimator review, then Build. Not in this release.

Built with ifcopenshell, openpyxl, numpy, matplotlib. AISC Shapes Database v16.0 data via the Apache-2.0
steelpy package.
"""


def main():
    app = App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    main()
