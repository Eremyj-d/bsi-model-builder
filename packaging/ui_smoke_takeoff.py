"""Headless smoke of the Takeoff page: open the window, switch to the Takeoff page, screenshot; open the key dialog, screenshot."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tkinter import messagebox
messagebox.showerror = messagebox.showwarning = lambda *a, **k: print("MESSAGEBOX", a)
from bsi_model_builder.ui.app import App
out = sys.argv[1]; os.makedirs(out, exist_ok=True)
app = App(); app.geometry("1240x760+0+0"); app.update()
def shot(n): app.update(); app.update_idletasks(); os.system(f"import -window root {os.path.join(out, n)} 2>/dev/null")
app.pages.select(1); app.takeoff.v["job"].set("Sample Shell Building"); app.takeoff.lst.insert("end", "C:/Bids/Sample/SAMPLE_Structural.pdf"); app.update(); time.sleep(0.3)
shot("ui_takeoff_01.png")
app.takeoff._key_dialog(); app.update(); time.sleep(0.3); shot("ui_takeoff_02_key.png")
for w in app.winfo_children():
    if w.winfo_class() == "Toplevel": w.destroy()
app.takeoff._run_clicked()   # no key → warning path (prints MESSAGEBOX)
app.update(); app.destroy(); print("ok")
