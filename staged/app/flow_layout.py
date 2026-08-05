"""A row of controls that WRAPS when the window narrows, instead of vanishing.

THE BUG THIS FIXES. Tk's `pack` does not wrap. A row built as a series of
`pack(side="left")` and `pack(side="right")` calls lays out fine at the width it
was designed at, and when the window is narrowed pack simply stops allocating
space to the widgets that no longer fit. They are not clipped, not scrolled to,
not shrunk - they are silently absent. A student who narrows a window to fit it
beside their data loses buttons with no indication that anything happened, and
the tool looks like it lost a feature rather than a few pixels.

It is worth being precise about why this is worse than clipping: a clipped
button is visibly cut off, so the user knows to widen the window. A packed-away
button leaves a tidy, complete-looking row. Nothing signals loss.

FlowFrame lays its children out left to right and starts a new row when the
next one will not fit, recomputing on every resize. Nothing is ever hidden; the
frame grows taller instead.

    bar = FlowFrame(parent)
    bar.pack(fill="x")
    bar.add(ttk.Button(bar, text="Load"))
    bar.add(ttk.Label(bar, text="Filter"))

Children must be created with the FlowFrame as their master, and added with
`add()` rather than packed or gridded - mixing geometry managers in one
container is what produced the original problem.
"""
from __future__ import annotations

try:
    import tkinter as tk
    from tkinter import ttk
    _BASE = ttk.Frame
except ImportError:                                        # pragma: no cover
    tk = ttk = None
    _BASE = object


class FlowFrame(_BASE):
    """A frame whose children wrap onto further rows as the width shrinks."""

    def __init__(self, master=None, hgap=6, vgap=6, **kw):
        if ttk is None:                                    # pragma: no cover
            raise RuntimeError("tkinter is not available")
        super().__init__(master, **kw)
        self._items = []
        self._hgap = int(hgap)
        self._vgap = int(vgap)
        self._last_width = -1
        self.bind("<Configure>", self._on_configure)

    # -- building ----------------------------------------------------------
    def add(self, widget, padx=None, pady=None):
        """Add a widget to the flow. Returns it, so calls can be chained."""
        self._items.append({"w": widget,
                            "padx": self._hgap if padx is None else int(padx),
                            "pady": self._vgap if pady is None else int(pady)})
        self._relayout(force=True)
        return widget

    def add_all(self, widgets):
        for w in widgets:
            self.add(w)
        return widgets

    # -- layout ------------------------------------------------------------
    def _on_configure(self, event):
        # Only re-lay-out when the WIDTH actually changed. A <Configure> also
        # fires for height changes - including the ones this method causes by
        # resizing the frame - and reacting to those is an endless loop that
        # presents as the window flickering and pinning a core.
        if event.width == self._last_width:
            return
        self._last_width = event.width
        self._relayout()

    def _relayout(self, force=False):
        if not self._items:
            return
        width = self.winfo_width()
        if width <= 1:
            # Not mapped yet. Laying out against a width of 1 would stack every
            # child on its own row and leave the frame enormous until the first
            # real resize, so defer to when a width exists.
            if force:
                self.after_idle(lambda: self._relayout())
            return

        x = y = 0
        row_h = 0
        for item in self._items:
            w = item["w"]
            ww = max(w.winfo_reqwidth(), 1)
            wh = max(w.winfo_reqheight(), 1)
            if x > 0 and x + ww > width:          # does not fit - new row
                x = 0
                y += row_h + item["pady"]
                row_h = 0
            w.place(x=x, y=y, width=ww, height=wh)
            x += ww + item["padx"]
            row_h = max(row_h, wh)

        total = y + row_h
        if total > 0 and self.winfo_reqheight() != total:
            # The frame must claim the height its rows need, or a parent packed
            # with fill="x" gives it one row's worth and the wrapped rows are
            # invisible - the same failure in a different place.
            self.configure(height=total)
            self.pack_propagate(False)
            self.grid_propagate(False)

    def rows(self):
        """How many rows the children currently occupy. For tests."""
        if not self._items:
            return 0
        ys = {self._items[0]["w"].winfo_y()}
        for item in self._items[1:]:
            ys.add(item["w"].winfo_y())
        return len(ys)


def set_minimum_size(window, width=760, height=520):
    """Stop a window being narrowed past the point where it makes sense.

    Complements FlowFrame rather than replacing it: wrapping keeps every
    control reachable, and a floor keeps the layout legible. Without the floor
    a determined drag turns a toolbar into a single vertical column of buttons,
    which is reachable and useless.
    """
    try:
        window.minsize(int(width), int(height))
    except Exception:                                      # pragma: no cover
        pass
    return window
