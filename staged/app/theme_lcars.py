"""An LCARS-inspired theme for WINK. Optional, centralised, and reversible.

Andres asked for the interface to be "a bit more StarTrekkie". This is that,
done as ONE theme module rather than colours sprinkled through fifteen tools -
which is also the honest answer to his other observation, that the interface
would benefit from a designer. Coherence is most of what a designer supplies,
and coherence means one place that decides.

WHAT IS BORROWED AND WHAT IS NOT. The palette, the condensed uppercase
lettering and the elbow are LCARS. The black field behind everything is not:
real LCARS is black because it was a lit prop on a dark set, and a black
background under dense scientific tables and long explanatory text costs
readability for no benefit. So the theme uses a very dark neutral field with
LCARS panels on it, which reads as the same language without fighting the
content.

DEFAULT OFF, AND PERSISTED. A lab tool that looks like a toy can undercut it in
front of people whose opinion matters - a committee, a reviewer, a visiting
speaker - and that judgement belongs to Andres, per session, not to this file.
`load_preference()` remembers the choice; `apply(root, enabled=False)` restores
the ordinary look completely.

NOTHING HERE CHANGES BEHAVIOUR. It sets ttk styles and colours only. If the
theme fails to load for any reason the tools run exactly as before, which is
why every call is guarded: an interface that will not start because a colour
scheme failed is a far worse outcome than a plain-looking one.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# The canonical-ish LCARS palette, by the names the fan community uses.
GOLDEN_TANOI = "#FFCC66"      # the workhorse - primary panels and headers
ATOMIC_TANGERINE = "#FF9966"  # secondary panels
NEON_CARROT = "#FF9933"       # emphasis
LILAC = "#CC99CC"             # tertiary panels, section headers
PERIWINKLE = "#9999FF"        # informational
ANODIZED_BLUE = "#99CCFF"     # quiet informational, links
BAHAMA_BLUE = "#4477AA"       # selected states
SUNFLOWER = "#FFCC00"         # warnings that are not errors
MARS = "#CC6666"              # refusals, errors, destructive actions
EGGPLANT = "#664466"          # inactive panels

# Not LCARS, deliberately - see the module docstring.
FIELD = "#12131A"             # the very dark neutral everything sits on
FIELD_RAISED = "#1C1E28"      # panels and entry fields
INK = "#0A0A0C"               # text ON a bright panel
PAPER = "#E8E9F0"             # body text on the dark field
MUTED = "#8A8FA6"             # secondary text

# Condensed, slightly wide-tracked lettering is most of the LCARS look.
# Bahnschrift ships with Windows 10 and later; the rest are fallbacks.
FONT_STACK = ("Bahnschrift SemiCondensed", "Bahnschrift", "Arial Narrow",
              "Segoe UI", "TkDefaultFont")

PREF_PATH = Path(os.environ.get(
    "WINK_THEME_PREF",
    Path(os.environ.get("LOCALAPPDATA", ".")) / "LabTools" / "theme.json"))


def available_font(root=None):
    """The first font in the stack this machine actually has."""
    try:
        from tkinter import font as tkfont
        have = set(tkfont.families(root))
        for name in FONT_STACK:
            if name in have:
                return name
    except Exception:                                      # pragma: no cover
        pass
    return "TkDefaultFont"


def load_preference():
    """True if the LCARS theme should be on. Default OFF."""
    try:
        with open(PREF_PATH, encoding="utf-8-sig") as fh:
            return bool(json.load(fh).get("lcars", False))
    except Exception:
        return False


def save_preference(enabled):
    try:
        PREF_PATH.parent.mkdir(parents=True, exist_ok=True)
        PREF_PATH.write_text(json.dumps({"lcars": bool(enabled)}, indent=2),
                             encoding="utf-8")
    except Exception:                                      # pragma: no cover
        pass
    return bool(enabled)


def apply(root, enabled=None):
    """Turn the theme on or off. Returns whether it ended up enabled.

    Guarded throughout: a colour scheme that fails must never stop a tool from
    starting.
    """
    if enabled is None:
        enabled = load_preference()
    try:
        from tkinter import ttk
        style = ttk.Style(root)
    except Exception:                                      # pragma: no cover
        return False

    if not enabled:
        try:
            style.theme_use(style.theme_names()[0])
            root.configure(background="")
        except Exception:
            pass
        return False

    try:
        fam = available_font(root)
        base = (fam, 10)
        head = (fam, 13, "bold")

        style.theme_use("clam")          # the only stock theme that recolours
        root.configure(background=FIELD)

        style.configure(".", background=FIELD, foreground=PAPER,
                        fieldbackground=FIELD_RAISED, font=base,
                        borderwidth=0, focuscolor=NEON_CARROT)
        style.configure("TFrame", background=FIELD)
        style.configure("TLabel", background=FIELD, foreground=PAPER, font=base)
        style.configure("Section.TLabel", background=FIELD,
                        foreground=GOLDEN_TANOI, font=head)
        style.configure("Muted.TLabel", background=FIELD, foreground=MUTED)

        # Buttons are the signature element: a solid warm panel, dark text,
        # flat, with generous horizontal padding.
        style.configure("TButton", background=GOLDEN_TANOI, foreground=INK,
                        font=(fam, 10, "bold"), padding=(14, 5), relief="flat")
        style.map("TButton",
                  background=[("active", NEON_CARROT),
                              ("pressed", ATOMIC_TANGERINE),
                              ("disabled", EGGPLANT)],
                  foreground=[("disabled", MUTED)])

        style.configure("Accent.TButton", background=LILAC, foreground=INK)
        style.map("Accent.TButton", background=[("active", PERIWINKLE)])
        style.configure("Danger.TButton", background=MARS, foreground=INK)
        style.map("Danger.TButton", background=[("active", ATOMIC_TANGERINE)])

        style.configure("TEntry", fieldbackground=FIELD_RAISED,
                        foreground=PAPER, insertcolor=GOLDEN_TANOI,
                        bordercolor=EGGPLANT, padding=4)
        style.configure("TCombobox", fieldbackground=FIELD_RAISED,
                        foreground=PAPER, background=FIELD_RAISED,
                        arrowcolor=GOLDEN_TANOI)
        style.configure("TCheckbutton", background=FIELD, foreground=PAPER)
        style.map("TCheckbutton", background=[("active", FIELD)])

        style.configure("Treeview", background=FIELD_RAISED,
                        fieldbackground=FIELD_RAISED, foreground=PAPER,
                        rowheight=22, borderwidth=0)
        style.configure("Treeview.Heading", background=EGGPLANT,
                        foreground=GOLDEN_TANOI, font=(fam, 10, "bold"),
                        relief="flat")
        style.map("Treeview", background=[("selected", BAHAMA_BLUE)],
                  foreground=[("selected", PAPER)])

        style.configure("TNotebook", background=FIELD, borderwidth=0)
        style.configure("TNotebook.Tab", background=EGGPLANT, foreground=PAPER,
                        padding=(16, 5), font=(fam, 10, "bold"))
        style.map("TNotebook.Tab",
                  background=[("selected", GOLDEN_TANOI)],
                  foreground=[("selected", INK)])

        style.configure("TProgressbar", background=GOLDEN_TANOI,
                        troughcolor=FIELD_RAISED, borderwidth=0)
        style.configure("TScrollbar", background=EGGPLANT,
                        troughcolor=FIELD, arrowcolor=GOLDEN_TANOI,
                        borderwidth=0)
        style.configure("TSeparator", background=EGGPLANT)
        return True
    except Exception:                                      # pragma: no cover
        return False


def elbow(parent, width=180, height=54, colour=GOLDEN_TANOI, corner=26,
          side="left", **kw):
    """The LCARS corner piece: a bar that turns through a quarter circle.

    Drawn on a Canvas because Tk has no rounded rectangle. Decorative only - it
    carries no state and no controls, so a machine where it fails to draw loses
    nothing but the flourish.
    """
    try:
        import tkinter as tk
    except ImportError:                                    # pragma: no cover
        return None
    c = tk.Canvas(parent, width=width, height=height, highlightthickness=0,
                  background=FIELD, **kw)
    r = min(corner, height, width)
    try:
        if side == "left":
            c.create_arc(0, 0, 2 * r, 2 * r, start=90, extent=90,
                         fill=colour, outline=colour)
            c.create_rectangle(r, 0, width, height, fill=colour, outline=colour)
            c.create_rectangle(0, r, r, height, fill=colour, outline=colour)
        else:
            c.create_arc(width - 2 * r, 0, width, 2 * r, start=0, extent=90,
                         fill=colour, outline=colour)
            c.create_rectangle(0, 0, width - r, height, fill=colour,
                               outline=colour)
            c.create_rectangle(width - r, r, width, height, fill=colour,
                               outline=colour)
    except Exception:                                      # pragma: no cover
        pass
    return c


def add_toggle(parent, root, on_change=None):
    """A 'LCARS' checkbox for a tool's control bar. Persists the choice."""
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:                                    # pragma: no cover
        return None
    var = tk.BooleanVar(value=load_preference())

    def flip():
        save_preference(var.get())
        apply(root, var.get())
        if on_change:
            on_change(var.get())

    return ttk.Checkbutton(parent, text="LCARS", variable=var, command=flip)
