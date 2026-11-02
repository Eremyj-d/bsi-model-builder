"""
Headless UI smoke test (xvfb): open the window, set the inputs, click Build, wait for the result,
screenshot each tab. Run:  xvfb-run -a python3.12 packaging/ui_smoke.py <out_dir>
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bsi_model_builder.ui import app as appmod
from bsi_model_builder.ui.app import App
from tkinter import messagebox
messagebox.showerror = lambda *a, **k: print('MESSAGEBOX', a)   # no modals under xvfb
messagebox.showwarning = lambda *a, **k: print('MESSAGEBOX', a)
from bsi_model_builder.selftest import sample_paths

out = sys.argv[1] if len(sys.argv) > 1 else "."
os.makedirs(out, exist_ok=True)
job, geom = sample_paths()

app = App()
app.geometry("1240x760+0+0")
app.v_job.set(job); app.v_geom.set(geom); app.v_out.set(out); app.v_tab.set(True)
app.update()


def shot(name):
    app.update(); app.update_idletasks()
    os.system(f"import -window root {os.path.join(out, name)} 2>/dev/null || scrot {os.path.join(out, name)} 2>/dev/null")


shot("ui_01_ready.png")
app._build_clicked()
t0 = time.time()
while app.result is None and time.time() - t0 < 120:
    app.update(); time.sleep(0.05)
app.update(); time.sleep(0.5); app.update()
print("result ok:", app.result.ok if app.result else None, "| pieces:", app.result.pieces if app.result else None)
app.nb.select(0); shot("ui_02_log.png")
app.nb.select(1); shot("ui_03_check.png")
app.nb.select(2); app.update(); app._show_png(); shot("ui_04_views.png")
app.nb.select(3); shot("ui_05_about.png")
# job editor
from bsi_model_builder.ui.jobeditor import JobEditor
from bsi_model_builder.core.jobfile import load_job
ed = JobEditor(app, load_job(job)); ed.geometry("760x640+100+40"); app.update(); time.sleep(0.3); shot("ui_06_jobeditor.png"); ed.destroy()
app.destroy()
print("screens in", out)
