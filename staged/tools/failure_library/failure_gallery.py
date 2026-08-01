"""Browse the WINK failure library.

A failure entry is a folder holding before.png (the module's automatic result),
after.png (the human-corrected result), and meta.json describing the correction.
Modules write these whenever a person fixes an automatic result, so the lab can
look across many failures, see *why* the detector was wrong, and improve it.

Point the library root at wherever the pairs accumulate (e.g. the myocyte
morphometry output folder, or a shared drive folder that pools several students'
outputs); the gallery finds every meta.json underneath it.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))
from process_ui import CockpitApp
from render_failure_queue import find_breadcrumbs, render_one


def discover_entries(root: str | Path) -> list[dict]:
    """Find every failure entry beneath ``root``.

    Two schemas are supported: an older before.png/after.png pair, and the
    current single corrected.png (``meta["image"]``) plus auto-vs-corrected
    numbers in meta.json. Either is accepted as long as its image file(s) exist.
    """
    entries = []
    for meta_path in Path(root).rglob("meta.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        folder = meta_path.parent
        before = folder / meta["before"] if meta.get("before") else None
        after = folder / meta["after"] if meta.get("after") else None
        single = folder / meta["image"] if meta.get("image") else None
        if before is not None and after is not None and before.exists() and after.exists():
            entries.append({"dir": folder, "meta": meta,
                            "before": before, "after": after})
        elif single is not None and single.exists():
            entries.append({"dir": folder, "meta": meta,
                            "before": None, "after": single})
    entries.sort(key=lambda e: str(e["meta"].get("captured", "")) + str(e["dir"]))
    return entries


class App(CockpitApp):
    def __init__(self):
        super().__init__("WINK Failure Library", geometry="1240x820",
                         process_title="Failure library")
        self.root_var = tk.StringVar(value=(sys.argv[1] if len(sys.argv) > 1 else ""))
        self.tool_filter = tk.StringVar(value="all")
        self.entries: list[dict] = []
        self.filtered: list[dict] = []
        self.index = 0
        self._build_controls()
        self._build_center()
        if self.root_var.get().strip():
            self._load()

    def _build_controls(self):
        c = self.controls
        row = ttk.Frame(c); row.pack(fill="x", pady=2)
        ttk.Label(row, text="Library root", width=13).pack(side="left")
        ttk.Entry(row, textvariable=self.root_var).pack(side="right", fill="x", expand=True)
        ttk.Button(c, text="Choose folder...", command=self._choose).pack(fill="x", pady=(0, 4))
        ttk.Button(c, text="Load / refresh", command=self._load).pack(fill="x", pady=2)
        ttk.Button(c, text="Render pending breadcrumbs...",
                   command=self._render_pending).pack(fill="x", pady=(6, 2))
        fr = ttk.Frame(c); fr.pack(fill="x", pady=6)
        ttk.Label(fr, text="Tool", width=13).pack(side="left")
        self.tool_box = ttk.Combobox(fr, textvariable=self.tool_filter,
                                     state="readonly", values=("all",))
        self.tool_box.pack(side="right", fill="x", expand=True)
        self.tool_box.bind("<<ComboboxSelected>>", lambda _e: self._apply_filter())
        nav = ttk.Frame(c); nav.pack(fill="x", pady=6)
        ttk.Button(nav, text="< Prev", command=lambda: self._step(-1)).pack(side="left")
        ttk.Button(nav, text="Next >", command=lambda: self._step(1)).pack(side="right")
        self.count_label = ttk.Label(c, text="No entries loaded.")
        self.count_label.pack(fill="x", pady=2)
        ttk.Button(c, text="Open this entry's folder",
                   command=self._open_folder).pack(fill="x", pady=2)
        self.bind("<Left>", lambda _e: self._step(-1))
        self.bind("<Right>", lambda _e: self._step(1))

    def _render_pending(self):
        """Turn queued breadcrumbs (plain JSON, written by the Fiji macro) into
        library entries. Pure Python (PIL/numpy); never touches Fiji, so this
        is safe to run any time, including while a Fiji session is open
        elsewhere - it only reads files the macro already finished writing."""
        library_root = self.root_var.get().strip()
        if not library_root:
            messagebox.showerror(
                "Render pending breadcrumbs",
                "Choose or load a library root first (that's where entries are written).",
                parent=self)
            return
        scan_root = filedialog.askdirectory(
            parent=self,
            title="Choose the folder to search for failure_queue breadcrumbs "
                  "(a session output folder, or a parent that holds several)")
        if not scan_root:
            return
        messagebox.showinfo(
            "Locate the source images",
            "Next, choose the folder that holds the original recordings (searched "
            "by filename if an image isn't found next to its own breadcrumb).",
            parent=self)
        image_root = filedialog.askdirectory(
            parent=self, title="Choose the folder holding the source images")
        self.set_status("Scanning for breadcrumbs...")
        self.update_idletasks()
        breadcrumbs = find_breadcrumbs(scan_root)
        if not breadcrumbs:
            messagebox.showinfo("Render pending breadcrumbs",
                               f"No failure_queue breadcrumbs found under:\n{scan_root}", parent=self)
            return
        ok_count = 0
        problems = []
        for path in breadcrumbs:
            ok, detail = render_one(path, Path(library_root), extra_image_root=image_root or None)
            if ok:
                ok_count += 1
                try:
                    path.unlink()
                except Exception:
                    pass
            else:
                problems.append(f"{path.name}: {detail}")
            self.log("Render breadcrumb", path.name, status="done" if ok else "warning")
        self.refresh_hood()
        summary = f"Rendered {ok_count}/{len(breadcrumbs)} breadcrumb(s) into the library."
        if problems:
            summary += "\n\nSkipped:\n" + "\n".join(problems[:10])
            if len(problems) > 10:
                summary += f"\n...and {len(problems) - 10} more."
        messagebox.showinfo("Render pending breadcrumbs", summary, parent=self)
        self._load()

    def _build_center(self):
        ttk.Label(self.center,
                  text="Failure library: where a module was wrong, and the human fix",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=6, pady=(6, 2))
        self.fig = Figure(figsize=(7.6, 4.2), dpi=100)
        self.ax_before = self.fig.add_subplot(121)
        self.ax_after = self.fig.add_subplot(122)
        for ax, title in ((self.ax_before, "Before (module)"),
                          (self.ax_after, "After (corrected)")):
            ax.set_axis_off(); ax.set_title(title, fontsize=10)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.center)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=6, pady=(0, 4))
        self.canvas.draw()
        self.meta_text = tk.Text(self.center, height=9, wrap="word")
        self.meta_text.pack(fill="x", padx=6, pady=(0, 6))

    def _choose(self):
        folder = filedialog.askdirectory(
            parent=self,
            title="Choose the library root (a folder containing failure entries)")
        if folder:
            self.root_var.set(folder); self._load()

    def _load(self):
        root = self.root_var.get().strip()
        if not root or not Path(root).is_dir():
            messagebox.showerror("Failure library", "Choose a valid folder.", parent=self)
            return
        self.set_status("Scanning for before/after pairs...")
        self.update_idletasks()
        self.entries = discover_entries(root)
        tools = sorted({e["meta"].get("tool", "unknown") for e in self.entries})
        self.tool_box.configure(values=["all"] + tools)
        self.log("Loaded library",
                 f"{len(self.entries)} entries from {Path(root).name}", status="done")
        self._apply_filter()

    def _apply_filter(self):
        chosen = self.tool_filter.get()
        self.filtered = [e for e in self.entries
                         if chosen == "all" or e["meta"].get("tool") == chosen]
        self.index = 0
        self._show()

    def _step(self, delta):
        if not self.filtered:
            return
        self.index = (self.index + delta) % len(self.filtered)
        self._show()

    def _show(self):
        if not self.filtered:
            self.count_label.config(text="No matching entries.")
            for ax, title in ((self.ax_before, "Before (module)"),
                              (self.ax_after, "After (corrected)")):
                ax.clear(); ax.set_axis_off(); ax.set_title(title, fontsize=10)
            self.meta_text.delete("1.0", "end")
            self.canvas.draw()
            return
        entry = self.filtered[self.index]
        self.count_label.config(text=f"Entry {self.index + 1} of {len(self.filtered)}")
        after_title = "After (corrected)" if entry["before"] is not None else "Corrected"
        for ax, path, title in ((self.ax_before, entry["before"], "Before (module)"),
                                (self.ax_after, entry["after"], after_title)):
            ax.clear()
            if path is None:
                ax.text(0.5, 0.5, "Before image not captured\n(see values below)",
                       ha="center", va="center", fontsize=9, color="#888888")
            else:
                try:
                    ax.imshow(np.asarray(Image.open(path)))
                except Exception as exc:
                    ax.text(0.5, 0.5, f"(image error)\n{exc}", ha="center", va="center", fontsize=8)
            ax.set_axis_off(); ax.set_title(title, fontsize=10)
        self.canvas.draw()
        meta = entry["meta"]
        lines = [f"{key}: {meta[key]}" for key in meta if key not in ("before", "after", "image")]
        self.meta_text.delete("1.0", "end")
        self.meta_text.insert("1.0", "\n".join(lines))

    def _open_folder(self):
        if not self.filtered:
            return
        try:
            os.startfile(str(self.filtered[self.index]["dir"]))
        except Exception as exc:
            messagebox.showerror("Open folder", str(exc), parent=self)


if __name__ == "__main__":
    App().mainloop()
