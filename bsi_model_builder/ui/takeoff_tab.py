"""
The Takeoff page: drawings in → draft workbook + RFI log + scope letter + notes + IFC model.
Review happens in Excel; "Build documents from edited workbook" rebuilds the IFC (and re-issues the docs)
from the estimator's edited workbook + the takeoff JSON.
"""
from __future__ import annotations
import os, queue, threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from . import settings
from ..takeoff.credentials import get_api_key, set_api_key, key_source
from ..takeoff.providers import MODEL_CHOICES, DEFAULT_MODEL, DEFAULT_RATES

NAVY, BLUE, LIGHT, GREEN, RED = "#1F3864", "#2E75B6", "#EAF1F8", "#2E7D32", "#C62828"


class TakeoffTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.q: queue.Queue = queue.Queue()
        self.paths: dict = {}
        self.pdfs: list[str] = list(app.settings.get("takeoff_pdfs", []))
        self._build()
        self.after(150, self._poll)

    # ------------------------------------------------------------------ layout
    def _build(self):
        pad = {"padx": 4, "pady": 2}
        body = ttk.Panedwindow(self, orient="horizontal"); body.pack(fill="both", expand=True)
        left = ttk.Frame(body, padding=(0, 6, 8, 0), width=480); right = ttk.Frame(body)
        body.add(left, weight=0); body.add(right, weight=1)
        self.after(50, lambda: body.sashpos(0, 490))
        left.columnconfigure(0, weight=1)

        ttk.Label(left, text="1.  Job", style="H.TLabel").grid(row=0, column=0, sticky="w")
        g = ttk.Frame(left); g.grid(row=1, column=0, sticky="ew")
        g.columnconfigure(1, weight=1)
        self.v = {}
        for r, (key, label) in enumerate([("job", "Job name"), ("job_code", "Job code"), ("building", "Building"), ("rev", "Revision"), ("bid_due", "Bid due")]):
            ttk.Label(g, text=label).grid(row=r, column=0, sticky="w", **pad)
            self.v[key] = tk.StringVar(value=self.app.settings.get(f"takeoff_{key}", "REV 0" if key == "rev" else ""))
            e = ttk.Entry(g, textvariable=self.v[key]); e.grid(row=r, column=1, sticky="ew", **pad)
            if key == "job_code":
                e.bind("<KeyRelease>", lambda _e: setattr(self, "_code_touched", True))
        self.v["job"].trace_add("write", self._auto_code)

        ttk.Label(left, text="2.  Drawings — PDFs (structural, architectural, MEP, civil, specs)", style="H.TLabel").grid(row=2, column=0, sticky="w", pady=(10, 0))
        lf = ttk.Frame(left); lf.grid(row=3, column=0, sticky="nsew"); left.rowconfigure(3, weight=1)
        self.lst = tk.Listbox(lf, height=7, font=("Segoe UI", 9), selectmode="extended")
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.lst.yview); self.lst.configure(yscrollcommand=sb.set)
        self.lst.pack(side="left", fill="both", expand=True); sb.pack(side="left", fill="y")
        for p in self.pdfs:
            self.lst.insert("end", p)
        bb = ttk.Frame(left); bb.grid(row=4, column=0, sticky="ew", pady=2)
        ttk.Button(bb, text="Add PDFs…", command=self._add).pack(side="left")
        ttk.Button(bb, text="Add folder…", command=self._add_folder).pack(side="left", padx=4)
        ttk.Button(bb, text="Remove", command=self._remove).pack(side="left")
        ttk.Button(bb, text="Clear", command=self._clear).pack(side="left", padx=4)

        ttk.Label(left, text="3.  Output folder  (blank = next to the first PDF, in 'Bohling Takeoff')", style="H.TLabel").grid(row=5, column=0, sticky="w", pady=(10, 0))
        of = ttk.Frame(left); of.grid(row=6, column=0, sticky="ew")
        self.v_out = tk.StringVar(value=self.app.settings.get("takeoff_out", ""))
        ttk.Entry(of, textvariable=self.v_out).pack(side="left", fill="x", expand=True)
        ttk.Button(of, text="Browse…", command=self._browse_out, width=10).pack(side="left", padx=(4, 0))

        ttk.Label(left, text="4.  Claude API", style="H.TLabel").grid(row=7, column=0, sticky="w", pady=(10, 0))
        af = ttk.Frame(left); af.grid(row=8, column=0, sticky="ew")
        ttk.Label(af, text="Model").pack(side="left")
        self.v_model = tk.StringVar(value=self.app.settings.get("takeoff_model", DEFAULT_MODEL))
        ttk.Combobox(af, textvariable=self.v_model, values=MODEL_CHOICES, width=22).pack(side="left", padx=6)
        self.key_lbl = ttk.Label(af, text="", style="Sub.TLabel"); self.key_lbl.pack(side="left", padx=6)
        ttk.Button(af, text="API key…", command=self._key_dialog, width=10).pack(side="right")
        self._refresh_key()

        self.btn_run = ttk.Button(left, text="Run takeoff", style="Accent.TButton", command=self._run_clicked)
        self.btn_run.grid(row=9, column=0, sticky="ew", pady=(14, 4))
        self.v_notes = tk.StringVar(value="")
        ttk.Label(left, text="Job notes for the extraction (optional — e.g. 'bid base + Alt 1 only', 'galvanize everything')", style="Sub.TLabel").grid(row=10, column=0, sticky="w")
        ttk.Entry(left, textvariable=self.v_notes).grid(row=11, column=0, sticky="ew", pady=(0, 6))
        rb = ttk.Frame(left); rb.grid(row=12, column=0, sticky="ew")
        self.btn_open = ttk.Button(rb, text="Open output folder", command=self._open_out, state="disabled"); self.btn_open.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.btn_wb = ttk.Button(rb, text="Open workbook", command=self._open_wb, state="disabled"); self.btn_wb.pack(side="left", fill="x", expand=True)
        ttk.Button(left, text="Build documents + model from an edited workbook…", command=self._from_workbook).grid(row=13, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(left, text="Review the draft workbook in Excel, fix what needs fixing, then rebuild the IFC and re-issue the RFI log / scope letter from it.",
                  style="Sub.TLabel", wraplength=460).grid(row=14, column=0, sticky="w", pady=(2, 0))

        self.log = tk.Text(right, wrap="word", font=("Consolas", 9), state="disabled", padx=6, pady=4)
        ys = ttk.Scrollbar(right, orient="vertical", command=self.log.yview); self.log.configure(yscrollcommand=ys.set)
        self.log.pack(side="left", fill="both", expand=True); ys.pack(side="left", fill="y")
        self.log.tag_configure("pass", foreground=GREEN, font=("Consolas", 9, "bold"))
        self.log.tag_configure("fail", foreground=RED, font=("Consolas", 9, "bold"))
        self.log.tag_configure("h", foreground=NAVY, font=("Consolas", 9, "bold"))
        self._append(HOWTO, "h")

    # ------------------------------------------------------------------ helpers
    def _append(self, text, tag=None):
        self.log.configure(state="normal"); self.log.insert("end", text + "\n", tag); self.log.see("end"); self.log.configure(state="disabled")

    def _auto_code(self, *_):
        from ..core.jobfile import code_from_name
        if not getattr(self, "_code_touched", False):
            self.v["job_code"].set(code_from_name(self.v["job"].get()))

    def _refresh_key(self):
        self.key_lbl.configure(text=f"key: {key_source()}")

    def save_settings(self):
        s = self.app.settings
        s["takeoff_pdfs"] = list(self.lst.get(0, "end")); s["takeoff_out"] = self.v_out.get(); s["takeoff_model"] = self.v_model.get()
        for k, v in self.v.items():
            s[f"takeoff_{k}"] = v.get()

    def _add(self):
        ps = filedialog.askopenfilenames(title="Drawing PDFs", filetypes=[("PDF", "*.pdf"), ("All", "*.*")])
        for p in ps:
            if p not in self.lst.get(0, "end"):
                self.lst.insert("end", p)

    def _add_folder(self):
        d = filedialog.askdirectory(title="Folder of PDFs")
        if d:
            for fn in sorted(os.listdir(d)):
                if fn.lower().endswith(".pdf") and os.path.join(d, fn) not in self.lst.get(0, "end"):
                    self.lst.insert("end", os.path.join(d, fn))

    def _remove(self):
        for i in reversed(self.lst.curselection()):
            self.lst.delete(i)

    def _clear(self):
        self.lst.delete(0, "end")

    def _browse_out(self):
        d = filedialog.askdirectory(title="Output folder")
        if d:
            self.v_out.set(d)

    def _key_dialog(self):
        dlg = tk.Toplevel(self); dlg.title("Claude API key"); dlg.transient(self.winfo_toplevel()); dlg.grab_set()
        frm = ttk.Frame(dlg, padding=12); frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=("Paste the API key from console.anthropic.com (Settings → API keys). It is stored in Windows Credential Manager "
                             "under 'BSI Model Builder' and never written into a job folder."), wraplength=460).pack(anchor="w")
        v = tk.StringVar(value="")
        e = ttk.Entry(frm, textvariable=v, show="•", width=60); e.pack(fill="x", pady=8); e.focus_set()
        ttk.Label(frm, text=f"Current: {key_source()}", style="Sub.TLabel").pack(anchor="w")
        def save():
            try:
                where = set_api_key(v.get(), plain_file_fallback=False)
                self._append(f"API key saved ({where}).")
            except Exception as ex:
                if messagebox.askyesno("API key", f"Credential Manager not available ({ex}).\nStore the key in a plain file in the settings folder instead?", parent=dlg):
                    set_api_key(v.get(), plain_file_fallback=True); self._append("API key saved to the settings folder (plain file).")
                else:
                    return
            self._refresh_key(); dlg.destroy()
        def clear():
            set_api_key("", plain_file_fallback=True); self._refresh_key(); dlg.destroy()
        bb = ttk.Frame(frm); bb.pack(fill="x", pady=(8, 0))
        ttk.Button(bb, text="Save", style="Accent.TButton", command=save).pack(side="right")
        ttk.Button(bb, text="Remove key", command=clear).pack(side="right", padx=6)
        ttk.Button(bb, text="Cancel", command=dlg.destroy).pack(side="right")

    # ------------------------------------------------------------------ run
    def _run_clicked(self):
        pdfs = list(self.lst.get(0, "end"))
        if not pdfs:
            messagebox.showwarning("Takeoff", "Add at least one drawing PDF."); return
        missing = [p for p in pdfs if not os.path.isfile(p)]
        if missing:
            messagebox.showwarning("Takeoff", "Not found:\n" + "\n".join(missing[:5])); return
        if not self.v["job"].get().strip():
            messagebox.showwarning("Takeoff", "Enter the job name."); return
        key = get_api_key()
        if not key:
            messagebox.showwarning("Takeoff", "No API key — click 'API key…' first."); return
        out = self.v_out.get().strip() or os.path.join(os.path.dirname(pdfs[0]), "Bohling Takeoff")
        self.save_settings(); settings.save(self.app.settings)
        header = {k: v.get().strip() for k, v in self.v.items()}
        model = self.v_model.get().strip() or DEFAULT_MODEL
        notes = self.v_notes.get().strip()
        self.log.configure(state="normal"); self.log.delete("1.0", "end"); self.log.configure(state="disabled")
        self._append(f"Takeoff — {header['job']} ({header['job_code']}) — {len(pdfs)} file(s) — model {model}", "h")
        self.btn_run.configure(state="disabled")
        threading.Thread(target=self._do_run, args=(pdfs, header, key, model, out, notes), daemon=True).start()

    def _do_run(self, pdfs, header, key, model, out, notes):
        try:
            from ..takeoff.engine import run_takeoff
            from ..takeoff.model import Header
            from ..takeoff.providers import AnthropicProvider
            from ..takeoff.outputs import build_deliverables
            os.makedirs(out, exist_ok=True)
            provider = AnthropicProvider(key, model=model, cache_dir=os.path.join(out, ".api_cache"))
            h = Header(job=header["job"], job_code=header["job_code"], building=header["building"], rev=header["rev"] or "REV 0", bid_due=header["bid_due"])
            res = run_takeoff(pdfs, h, provider, out, progress=lambda m: self.q.put(("log", m)), job_notes=notes)
            for e in res.errors:
                self.q.put(("log", "WARN " + e.splitlines()[0]))
            self.q.put(("log", "building deliverables …"))
            paths = build_deliverables(res.takeoff, out, res.takeoff.header.job_code, progress=lambda m: self.q.put(("log", m)))
            paths["out_dir"] = out; paths["cost"] = res.cost
            self.q.put(("done", paths))
        except Exception as ex:
            import traceback
            self.q.put(("error", f"{type(ex).__name__}: {ex}\n{traceback.format_exc()}"))

    def _from_workbook(self):
        xlsx = filedialog.askopenfilename(title="Edited takeoff workbook", filetypes=[("Excel workbook", "*.xlsx *.xlsm")])
        if not xlsx:
            return
        d = os.path.dirname(xlsx)
        cands = [os.path.join(d, f) for f in os.listdir(d) if f.endswith("_takeoff.json")]
        tj = cands[0] if len(cands) == 1 else filedialog.askopenfilename(title="Matching takeoff JSON", initialdir=d, filetypes=[("Takeoff JSON", "*_takeoff.json")])
        if not tj:
            return
        self._append(f"Rebuilding from {os.path.basename(xlsx)} + {os.path.basename(tj)} …", "h")
        self.btn_run.configure(state="disabled")
        def work():
            try:
                from ..takeoff.outputs import build_from_workbook
                paths = build_from_workbook(xlsx, tj, d, progress=lambda m: self.q.put(("log", m)))
                paths["out_dir"] = d; paths["workbook"] = xlsx
                self.q.put(("done", paths))
            except Exception as ex:
                import traceback
                self.q.put(("error", f"{type(ex).__name__}: {ex}\n{traceback.format_exc()}"))
        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._append(payload, "fail" if payload.startswith(("ERROR", "WARN")) else None)
                elif kind == "done":
                    self.paths = payload; self.btn_run.configure(state="normal")
                    self.btn_open.configure(state="normal"); self.btn_wb.configure(state="normal" if payload.get("workbook") else "disabled")
                    ok = payload.get("ifc_ok")
                    self._append("DONE — " + ", ".join(os.path.basename(v) for k, v in payload.items() if isinstance(v, str) and os.path.isfile(v)), "pass")
                    if "ifc" in payload:
                        self._append("model check: " + ("PASS" if ok else "FAIL — see the Model page / check file"), "pass" if ok else "fail")
                    if payload.get("cost") is not None:
                        self._append(f"API cost this run ≈ ${payload['cost']:.2f} (cached stages are free on re-runs)")
                    self.app.status.configure(text=f"Takeoff written to {payload.get('out_dir')}")
                elif kind == "error":
                    self.btn_run.configure(state="normal"); self._append(payload, "fail"); self.app.status.configure(text="Takeoff failed — see the log.")
        except queue.Empty:
            pass
        self.after(150, self._poll)

    def _open_out(self):
        from .app import open_path
        if self.paths.get("out_dir"):
            open_path(self.paths["out_dir"])

    def _open_wb(self):
        from .app import open_path
        if self.paths.get("workbook"):
            open_path(self.paths["workbook"])


HOWTO = """TAKEOFF FROM DRAWINGS — how it works
1. Enter the job, add the drawing PDFs (every discipline you have — S, A, M/E/P, civil, the project manual), pick the model, set the API key once.
2. Run takeoff. The app indexes the set, reads the notes, takes off the columns, each framing sheet (with its own geometry pass on vector pages), every detail / arch / MEP sheet, then writes the RFI log and scope content. Each stage is cached — re-running the same set costs nothing; a changed sheet re-runs only its stage.
3. Outputs in the output folder: <Job>_Takeoff.xlsx (12 tabs incl. Model Geometry), <Job>_RFI_Log_BohlingSteel.docx (+ _INTERNAL), <Job>_Steel_Scope_BohlingSteel.docx (PRELIMINARY), <Job>_takeoff_notes.md, <Job>_takeoff.json, <Job>_job.json, <Job>_Model.ifc + check + views.
4. Review in Excel: every number came from a count or a dimension; anything the reader could not settle is flagged with a BSI-xx RFI on the row and in the Summary FLAGS table. Fix what needs fixing in the workbook.
5. 'Build documents + model from an edited workbook' rebuilds the IFC from your edited Model Geometry tab and re-issues the RFI log / scope letter from the takeoff JSON.
Costs: shown per stage in this log (estimate from the rate table in settings). A typical 100–150-sheet set is a few dollars per full run at current prices.
"""
