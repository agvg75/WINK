"""Reusable, fast movie navigator for selecting disjoint analysis ranges."""
from __future__ import annotations

from collections import OrderedDict
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import numpy as np


class FrameRangeSelector(tk.Toplevel):
    """Select one or more source-frame ranges while keeping original timing.

    The preview is deliberately downsampled and cached.  This window is for
    deciding where/when to analyze, not for pixel-precise scoring.
    """

    def __init__(self, parent, movie, title="Choose frames to analyze"):
        super().__init__(parent)
        self.title(title)
        self.movie = movie
        self.count = int(movie.n_frames)
        self.index = tk.IntVar(value=1)
        self.preview_max = tk.IntVar(value=720)
        self.start = None
        self.ranges = []
        self.result = None
        self._photo = None
        self._cache = OrderedDict()
        self._draw_job = None

        self.geometry("1040x780")
        self.minsize(760, 560)
        self.protocol("WM_DELETE_WINDOW", self.cancel)

        self.image = ttk.Label(self)
        self.image.pack(fill="both", expand=True, padx=8, pady=8)

        nav = ttk.Frame(self)
        nav.pack(fill="x", padx=8)
        ttk.Button(nav, text="<", command=lambda: self.step(-1)).pack(side="left")
        self.scale = tk.Scale(
            nav, from_=1, to=max(1, self.count), orient="horizontal",
            variable=self.index, command=lambda _=None: self.schedule_draw(),
            length=650)
        self.scale.pack(side="left", fill="x", expand=True)
        ttk.Button(nav, text=">", command=lambda: self.step(1)).pack(side="left")
        ttk.Button(nav, text="Jump...", command=self.jump).pack(side="left", padx=4)
        ttk.Label(nav, text="Preview max px").pack(side="left", padx=(8, 2))
        ttk.Entry(nav, textvariable=self.preview_max, width=6).pack(side="left")

        controls = ttk.Frame(self)
        controls.pack(fill="x", padx=8, pady=5)
        ttk.Button(controls, text="Mark start", command=self.mark_start).pack(side="left")
        ttk.Button(controls, text="Mark end + add range", command=self.mark_end).pack(side="left", padx=4)
        ttk.Button(controls, text="Delete selected", command=self.delete).pack(side="left")
        ttk.Button(controls, text="Analyze full movie", command=self.full).pack(side="right")

        self.tree = ttk.Treeview(
            self, columns=("start", "end", "frames"), show="headings", height=5)
        for column, title_text in (
            ("start", "Start frame"),
            ("end", "End frame"),
            ("frames", "Frames analyzed"),
        ):
            self.tree.heading(column, text=title_text)
            self.tree.column(column, width=150)
        self.tree.pack(fill="x", padx=8, pady=5)

        self.status = tk.StringVar(
            value="Add one or more ranges. Gaps are skipped but original "
                  "frame numbers and elapsed time are retained.")
        ttk.Label(self, textvariable=self.status, wraplength=980).pack(fill="x", padx=8)

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=8, pady=8)
        ttk.Button(bottom, text="Cancel", command=self.cancel).pack(side="right")
        ttk.Button(bottom, text="Accept ranges", command=self.accept).pack(side="right", padx=5)

        self.bind("<Left>", lambda _e: self.step(-1))
        self.bind("<Right>", lambda _e: self.step(1))
        self.bind("<Prior>", lambda _e: self.step(-10))
        self.bind("<Next>", lambda _e: self.step(10))
        self.bind("<Home>", lambda _e: self.goto(1))
        self.bind("<End>", lambda _e: self.goto(self.count))
        self.bind("<Return>", lambda _e: self.jump())
        self.draw()

    def schedule_draw(self):
        if self._draw_job is not None:
            try:
                self.after_cancel(self._draw_job)
            except Exception:
                pass
        self._draw_job = self.after(35, self.draw)

    def _preview_image(self, i):
        from PIL import Image

        max_px = max(256, int(self.preview_max.get() or 720))
        key = (int(i), max_px)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached

        frame = np.asarray(self.movie.get_frame(i))
        if frame.ndim == 2:
            lo, hi = np.percentile(frame, [.2, 99.8])
            frame = np.uint8(np.clip((frame - lo) * 255 / max(hi - lo, 1), 0, 255))
            img = Image.fromarray(frame)
        else:
            img = Image.fromarray(np.uint8(np.clip(frame[..., :3], 0, 255)))
        img.thumbnail((max_px, max_px))
        self._cache[key] = img.copy()
        while len(self._cache) > 24:
            self._cache.popitem(last=False)
        return img

    def draw(self):
        from PIL import ImageTk

        i = max(0, min(self.count - 1, int(self.index.get()) - 1))
        img = self._preview_image(i)
        self._photo = ImageTk.PhotoImage(img, master=self)
        self.image.configure(image=self._photo)
        pending = f"Pending range start: {self.start}." if self.start else \
            "Mark a start, navigate, then mark the end."
        self.status.set(
            f"Source frame {i + 1}/{self.count}. {pending} "
            "Keys: Left/Right=1 frame, PgUp/PgDn=10, Home/End, Enter=jump.")

    def step(self, delta):
        self.goto(self.index.get() + int(delta))

    def goto(self, value):
        self.index.set(max(1, min(self.count, int(value))))
        self.draw()

    def jump(self):
        value = simpledialog.askinteger(
            "Jump", "Source frame number (1-based):",
            initialvalue=self.index.get(), minvalue=1, maxvalue=self.count,
            parent=self)
        if value:
            self.goto(value)

    def mark_start(self):
        self.start = int(self.index.get())
        self.draw()

    def mark_end(self):
        if self.start is None:
            messagebox.showwarning("Frame range", "Mark a start first.", parent=self)
            return
        a, b = sorted((self.start, int(self.index.get())))
        self.ranges.append((a, b))
        self.ranges = self._merge(self.ranges)
        self.start = None
        self.refresh()
        self.draw()

    @staticmethod
    def _merge(ranges):
        merged = []
        for a, b in sorted(ranges):
            if merged and a <= merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        return merged

    def refresh(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for i, (a, b) in enumerate(self.ranges):
            self.tree.insert("", "end", iid=str(i), values=(a, b, b - a + 1))

    def delete(self):
        selection = self.tree.selection()
        if selection:
            del self.ranges[int(selection[0])]
            self.refresh()

    def full(self):
        self.result = [(0, self.count - 1)]
        self.destroy()

    def accept(self):
        if not self.ranges:
            messagebox.showwarning(
                "Frame ranges",
                "Add at least one range or choose Analyze full movie.",
                parent=self)
            return
        self.result = [(a - 1, b - 1) for a, b in self.ranges]
        self.destroy()

    def cancel(self):
        self.result = None
        self.destroy()


def select_frame_ranges(parent, movie, title="Choose frames to analyze"):
    window = FrameRangeSelector(parent, movie, title)
    parent.wait_window(window)
    return window.result
