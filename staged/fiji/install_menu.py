"""
install_fiji_menu.py
====================
Set up a Plugins > AGVGLab submenu in Fiji, so your tools live in the menu
instead of being dragged in every time.

It finds Fiji, creates Fiji.app/plugins/AGVGLab, and copies the lab tool files
into it. After a Fiji restart they appear under Plugins > AGVGLab.

Honest about the two kinds of tool:
  - Macros (.ijm) work as soon as they are in that folder. Guaranteed.
  - Java plugins (.java) appear only if your Fiji compiles them at startup;
    if they do not show up after a restart, they need to be built into a jar,
    which is a follow-up we do against your actual Fiji.

If Fiji is not found automatically, Browse to your ImageJ-win64.exe (inside your
Fiji.app folder). Launch by double-clicking Install_AGVGLab_Menu.bat.
"""
from __future__ import annotations

import os
import sys
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent

FIJI_EXE_CANDIDATES = [
    r"C:\Fiji.app\ImageJ-win64.exe",
    r"C:\Program Files\Fiji.app\ImageJ-win64.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Fiji.app\ImageJ-win64.exe"),
    os.path.expandvars(r"%USERPROFILE%\Fiji.app\ImageJ-win64.exe"),
    os.path.expandvars(r"%USERPROFILE%\Desktop\Fiji.app\ImageJ-win64.exe"),
]

# Tools to place in the AGVGLab submenu. Each: menu label -> (filename, search
# dirs relative to the Lab tools folder, kind). ImageJ wants an underscore in a
# menu file name; these already have one.
#
# Paths are relative to this file (staged/fiji/). The historical entries
# pointed at a RGBCaMP_Tracker/ layout that the reorganisation replaced, so
# this installer found NOTHING and quietly created an empty menu folder - the
# copies already in Fiji were put there some other way and had gone stale. Keep
# the old locations in the search list so an older checkout still resolves.
TOOLS = [
    ("Myocyte Morphometry", "Myocyte_Morphometry.ijm",
     ["../tools/morphology", "."], "macro"),
    ("RGBCaMP Extractor", "WormRGBCaMPMap_v1.java",
     ["../tools/rgbcamp/fiji",
      "RGBCaMP_Tracker", "RGBCaMP_Tracker/pipeline", "RGBCaMP_Tracker/src", "."],
     "plugin"),
    # Kinematics extractor is a patch to be applied and built first, so it is
    # not listed here yet. Add it once it is a standalone plugin.
]


def find_fiji_app():
    for c in FIJI_EXE_CANDIDATES:
        if c and os.path.exists(c):
            return Path(c).parent          # Fiji.app holds ImageJ-win64.exe
    return None


def find_tool_file(filename, search):
    for rel in search:
        cand = (HERE / rel / filename)
        if cand.exists():
            return cand.resolve()
    return None


def install(fiji_app: Path):
    target = Path(fiji_app) / "plugins" / "AGVGLab"
    target.mkdir(parents=True, exist_ok=True)
    installed, missing, notes = [], [], []
    for label, fname, search, kind in TOOLS:
        src = find_tool_file(fname, search)
        if src is None:
            missing.append(f"{label} ({fname})")
            continue
        shutil.copy2(src, target / fname)
        installed.append(f"{label}  [{kind}]")
        if kind == "plugin":
            notes.append(f"{label} is a Java plugin; if it does not appear after "
                         "restarting Fiji, it needs to be built into a jar.")
    return target, installed, missing, notes


def _run_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    root = tk.Tk()
    root.title("Install AGVGLab Fiji menu")
    root.geometry("560x360")

    ttk.Label(root, text="Add your tools to Fiji's Plugins menu",
              font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=14, pady=(12, 2))
    ttk.Label(root, text="Creates Plugins > AGVGLab so you stop dragging tools in. "
                         "Run once per computer, then restart Fiji.",
              font=("Segoe UI", 9), wraplength=520, justify="left").pack(anchor="w", padx=14)

    fiji = find_fiji_app()
    fiji_var = tk.StringVar(value=str(fiji) if fiji else "(Fiji not found: click Browse)")

    row = ttk.Frame(root); row.pack(fill="x", padx=14, pady=10)
    ttk.Label(row, text="Fiji.app:", font=("Segoe UI", 9)).pack(side="left")
    ttk.Label(row, textvariable=fiji_var, font=("Segoe UI", 9), foreground="#333",
              wraplength=340).pack(side="left", padx=6)

    def _browse():
        p = filedialog.askopenfilename(title="Find ImageJ-win64.exe inside your Fiji.app",
                                       filetypes=[("ImageJ", "ImageJ-win64.exe"), ("All", "*.*")])
        if p:
            fiji_var.set(str(Path(p).parent))

    ttk.Button(row, text="Browse...", command=_browse).pack(side="left")

    out = tk.Text(root, height=10, width=64, wrap="word", font=("Consolas", 9),
                  state="disabled", bd=1, relief="solid")
    out.pack(fill="both", expand=True, padx=14, pady=(4, 8))

    def _do_install():
        fp = fiji_var.get()
        if not fp or not Path(fp).exists() or not (Path(fp) / "plugins").exists():
            messagebox.showerror("Install", "That does not look like a Fiji.app folder "
                                 "(no plugins folder). Browse to your ImageJ-win64.exe.")
            return
        target, installed, missing, notes = install(Path(fp))
        lines = [f"Installed into:\n{target}\n"]
        if installed:
            lines.append("Added:\n  " + "\n  ".join(installed))
        if missing:
            lines.append("\nNot found (skipped):\n  " + "\n  ".join(missing))
        lines.append("\nNow restart Fiji. The tools appear under Plugins > AGVGLab.")
        if notes:
            lines.append("\nNote:\n  " + "\n  ".join(notes))
        out.config(state="normal"); out.delete("1.0", "end")
        out.insert("1.0", "\n".join(lines)); out.config(state="disabled")

    ttk.Button(root, text="Install into Fiji", command=_do_install).pack(anchor="w", padx=14, pady=(0, 12))
    root.mainloop()


def main():
    try:
        _run_gui()
    except Exception:
        import traceback
        (HERE / "install_fiji_menu.log").write_text(traceback.format_exc(), encoding="utf-8")


if __name__ == "__main__":
    main()
