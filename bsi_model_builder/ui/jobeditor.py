"""Job file editor dialog — name / code / rev / datum / grids / storeys, saved as job.json."""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox
from ..core.jobfile import new_job, validate_job, code_from_name, DEFAULT_DATUM

NAVY = "#1F3864"


def _parse_pairs(text: str, what: str) -> dict:
    """'1 = 0\\n2 = 25.5' or '1=0, 2=25.5' -> {'1': 0.0, '2': 25.5}; feet-inches like 25'-6 1/2\" accepted"""
    out = {}
    for chunk in text.replace(",", "\n").splitlines():
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise ValueError(f"{what}: '{chunk}' needs tag = feet")
        tag, val = chunk.split("=", 1)
        out[tag.strip()] = parse_feet(val.strip())
    return out


def parse_feet(s: str) -> float:
    """'25.5' | '25' | \"25'-6\" | \"25'-6 1/2\\\"\" | '-2'-0\"' -> decimal feet"""
    s = s.strip().replace('"', "").replace("”", "").replace("’", "'")
    if not s:
        raise ValueError("blank number")
    neg = s.startswith("-")
    if neg:
        s = s[1:].strip()
    if "'" in s:
        ft, _, rest = s.partition("'")
        rest = rest.strip().lstrip("-").strip()
        inches = 0.0
        if rest:
            parts = rest.split()
            inches = float(parts[0]) if parts[0].replace(".", "", 1).isdigit() else 0.0
            frac = parts[1] if len(parts) > 1 else ("" if "/" not in parts[0] else parts[0])
            if "/" in frac:
                n, d = frac.split("/"); inches += float(n) / float(d)
                if len(parts) == 1:
                    inches = float(n) / float(d)
        v = float(ft or 0) + inches / 12.0
    else:
        v = float(s)
    return -v if neg else v


class JobEditor(tk.Toplevel):
    def __init__(self, master, job: dict | None = None, on_save=None):
        super().__init__(master)
        self.title("Job setup")
        self.resizable(True, True)
        self.job = dict(job) if job else new_job()
        self.on_save = on_save
        self.result = None
        self.transient(master); self.grab_set()
        self._build()
        self.geometry("760x640")

    def _build(self):
        pad = {"padx": 8, "pady": 3}
        frm = ttk.Frame(self, padding=10); frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)
        self.vars = {}
        rows = [("job", "Job name"), ("job_code", "Job code (seeds the GUIDs — keep it constant across revisions)"),
                ("building", "Building (optional)"), ("rev", "Takeoff revision"), ("date", "Date"), ("source", "Source (workbook / drawing set)")]
        r = 0
        for key, label in rows:
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", **pad)
            v = tk.StringVar(value=str(self.job.get(key, "") or ""))
            e = ttk.Entry(frm, textvariable=v); e.grid(row=r, column=1, sticky="ew", **pad)
            self.vars[key] = v; r += 1
        self.vars["job"].trace_add("write", self._auto_code)
        ttk.Label(frm, text="Datum — where 0,0,0 is and which way +X / +Y point").grid(row=r, column=0, columnspan=2, sticky="w", **pad); r += 1
        self.datum = tk.Text(frm, height=4, wrap="word"); self.datum.grid(row=r, column=0, columnspan=2, sticky="ew", **pad)
        self.datum.insert("1.0", self.job.get("datum", {}).get("description", DEFAULT_DATUM)); r += 1

        gl = ttk.Frame(frm); gl.grid(row=r, column=0, columnspan=2, sticky="nsew", **pad); frm.rowconfigure(r, weight=1); r += 1
        for i in range(3):
            gl.columnconfigure(i, weight=1)
        gl.rowconfigure(1, weight=1)
        ttk.Label(gl, text="Grids along +X (numbered)  —  tag = feet, one per line").grid(row=0, column=0, sticky="w")
        ttk.Label(gl, text="Grids along +Y (lettered)").grid(row=0, column=1, sticky="w")
        ttk.Label(gl, text="Storeys  —  name = feet  (blank = derive from beam T/STL)").grid(row=0, column=2, sticky="w")
        self.gx = tk.Text(gl, width=22, height=10); self.gx.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        self.gy = tk.Text(gl, width=22, height=10); self.gy.grid(row=1, column=1, sticky="nsew", padx=(0, 6))
        self.st = tk.Text(gl, width=30, height=10); self.st.grid(row=1, column=2, sticky="nsew")
        g = self.job.get("grids", {})
        self.gx.insert("1.0", "\n".join(f"{k} = {v}" for k, v in (g.get("X") or {}).items()))
        self.gy.insert("1.0", "\n".join(f"{k} = {v}" for k, v in (g.get("Y") or {}).items()))
        self.st.insert("1.0", "\n".join(f"{s.get('name')} = {s.get('elev_ft')}" for s in (self.job.get("storeys") or [])))
        ttk.Label(frm, text="Feet may be typed as 25.5 or 25'-6\" or 25'-6 1/2\".", foreground="#555").grid(row=r, column=0, columnspan=2, sticky="w", **pad); r += 1

        btns = ttk.Frame(frm); btns.grid(row=r, column=0, columnspan=2, sticky="e", **pad)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="Save", command=self._save, style="Accent.TButton").pack(side="right", padx=4)

    def _auto_code(self, *_):
        if not self.vars["job_code"].get().strip() or getattr(self, "_code_auto", True):
            self._code_auto = True
            self.vars["job_code"].set(code_from_name(self.vars["job"].get()))

    def _save(self):
        try:
            job = dict(self.job)
            for k, v in self.vars.items():
                job[k] = v.get().strip()
            job["datum"] = {"description": self.datum.get("1.0", "end").strip() or DEFAULT_DATUM}
            job["grids"] = {"X": _parse_pairs(self.gx.get("1.0", "end"), "X grids"),
                            "Y": _parse_pairs(self.gy.get("1.0", "end"), "Y grids")}
            job["storeys"] = [{"name": k, "elev_ft": v} for k, v in _parse_pairs(self.st.get("1.0", "end"), "storeys").items()]
        except ValueError as ex:
            messagebox.showerror("Job setup", str(ex), parent=self); return
        probs = validate_job(job)
        if probs:
            messagebox.showerror("Job setup", "\n".join(probs), parent=self); return
        self.result = job
        if self.on_save:
            self.on_save(job)
        self.destroy()
