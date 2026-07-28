"""In-panel prompts: a value dialog rendered *inside* a tool's control panel
instead of a floating pop-up window.

Motivation
----------
``tkinter.simpledialog.ask*`` opens a separate ``Toplevel``.  On Windows those
pop-ups frequently draw *behind* the parent window (especially when the parent
was just raised), so the user has to hunt for them; and because they are created
and destroyed for every question, a sequence of them flashes windows in and out.

``InlinePrompt`` renders the same question (title, prompt text, an entry, OK /
Cancel) as a small framed strip that lives in a host frame you provide -- e.g.
the top of a "Controls" column.  It blocks exactly like ``simpledialog`` (returns
the value, or ``None`` on cancel), so it is a drop-in replacement, but it never
hides behind anything and it keeps its place in the layout.

The component is intentionally self-contained and tool-agnostic so it can later
be adopted by other modules; for now only the pharyngeal pumping tool uses it.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class InlinePrompt:
    """A reusable, blocking in-panel prompt.

    Parameters
    ----------
    host:
        The container widget the prompt packs itself into while active (its
        "control part of the main window").
    root:
        The widget whose ``wait_variable`` drives the modal wait.  Defaults to
        ``host``; pass the toplevel/root when the host is a deeply nested frame.
    """

    def __init__(self, host, root=None):
        self.host = host
        self.root = root or host
        self._done = tk.IntVar(master=self.root, value=0)
        self._var = tk.StringVar(master=self.root, value="")
        self._error = tk.StringVar(master=self.root, value="")
        self._frame = None
        self._entry = None
        self._value = None
        # per-question validation context
        self._kind = "float"
        self._minvalue = None
        self._maxvalue = None

    # -- public API ---------------------------------------------------------
    def ask_float(self, title, prompt, *, initialvalue=None,
                  minvalue=None, maxvalue=None):
        return self._ask(title, prompt, initialvalue, minvalue, maxvalue,
                         kind="float")

    def ask_integer(self, title, prompt, *, initialvalue=None,
                    minvalue=None, maxvalue=None):
        return self._ask(title, prompt, initialvalue, minvalue, maxvalue,
                         kind="int")

    def ask_string(self, title, prompt, *, initialvalue=None):
        return self._ask(title, prompt, initialvalue, None, None, kind="str")

    # -- internals ----------------------------------------------------------
    def _ask(self, title, prompt, initialvalue, minvalue, maxvalue, kind):
        self._value = None
        self._kind = kind
        self._minvalue = minvalue
        self._maxvalue = maxvalue
        self._error.set("")
        self._var.set("" if initialvalue is None else str(initialvalue))
        self._build(title, prompt)
        try:
            self._entry.focus_set()
            self._entry.selection_range(0, "end")
        except Exception:
            pass
        # Redirect all app events to this strip so the rest of the window stays
        # put and cannot be re-entered while the question is open -- modality
        # without a separate window.
        try:
            self.host.update_idletasks()
            self._frame.grab_set()
        except Exception:
            pass
        self._done.set(0)
        self.root.wait_variable(self._done)
        self._teardown()
        return self._value

    def _build(self, title, prompt):
        if self._frame is not None:
            self._teardown()
        frame = ttk.LabelFrame(self.host, text=str(title))
        frame.pack(side="top", fill="x", padx=6, pady=(6, 4))
        ttk.Label(frame, text=str(prompt), wraplength=232,
                  justify="left").pack(anchor="w", padx=6, pady=(4, 3))
        entry = ttk.Entry(frame, textvariable=self._var, width=18)
        entry.pack(fill="x", padx=6, pady=(0, 2))
        entry.bind("<Return>", lambda _e: self._accept())
        entry.bind("<Escape>", lambda _e: self._cancel())
        err = ttk.Label(frame, textvariable=self._error, foreground="#b00020",
                        wraplength=232, justify="left")
        err.pack(anchor="w", padx=6)
        row = ttk.Frame(frame)
        row.pack(fill="x", padx=6, pady=(3, 6))
        ttk.Button(row, text="OK", command=self._accept).pack(side="left")
        ttk.Button(row, text="Cancel", command=self._cancel).pack(
            side="right")
        self._frame = frame
        self._entry = entry

    def _teardown(self):
        try:
            self._frame.grab_release()
        except Exception:
            pass
        if self._frame is not None:
            try:
                self._frame.destroy()
            except Exception:
                pass
        self._frame = None
        self._entry = None

    def _accept(self):
        raw = self._var.get().strip()
        if self._kind == "str":
            self._value = raw
            self._done.set(1)
            return
        if raw == "":
            self._error.set("Enter a value.")
            return
        try:
            number = float(raw)
        except ValueError:
            self._error.set("Enter a number.")
            return
        if self._kind == "int":
            number = int(round(number))
        if self._minvalue is not None and number < self._minvalue:
            self._error.set(f"Must be at least {self._minvalue:g}.")
            return
        if self._maxvalue is not None and number > self._maxvalue:
            self._error.set(f"Must be at most {self._maxvalue:g}.")
            return
        self._value = number
        self._done.set(1)

    def _cancel(self):
        self._value = None
        self._done.set(1)
