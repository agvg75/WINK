"""Who ran this. Set once on the Hub, stamped onto everything afterwards.

Andres: students should enter their initials on the Hub so whatever they use is
tracked back to them - date and initials assigning an owner unambiguously years
from now.

NOT NAMED operator.py, which was the obvious name and would have been a bug.
`operator` is a Python standard library module that pandas, numpy and
matplotlib all import; with app/ on sys.path this file would have shadowed it
and broken imports across the entire toolset in a way whose error message
points nowhere near here.

INITIALS ALONE ARE NOT UNAMBIGUOUS, which is the thing to get right. Two
students share initials eventually, someone marries, a lab has an AV and an
AVG. So the full name is captured ONCE alongside them, and every stamp carries
both. The initials stay the short form people type and read; the full name is
what makes them resolvable in 2031.

THE MACHINE IS RECORDED TOO. "Which computer" answers questions initials
cannot: which runtime version, which drive letters, which calibration was
current. It costs nothing and has already mattered once, when a placeholder
scale reached the archive from one station.

NOT ENFORCED, DELIBERATELY. A tool that refuses to run without initials will be
met with "AA" within a week, and a false attribution is worse than a missing
one - it names an innocent person as the source of a number. Unset is recorded
as unset, visibly, so the gap is honest rather than filled with noise.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import socket
from pathlib import Path

STORE = Path(os.environ.get(
    "WINK_OPERATOR",
    Path(os.environ.get("LOCALAPPDATA", ".")) / "LabTools" / "operator.json"))


class OperatorError(Exception):
    """Refusals that name the consequence."""


def _machine():
    try:
        return socket.gethostname()
    except Exception:                                      # pragma: no cover
        return "unknown"


def load():
    try:
        d = json.loads(STORE.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {"initials": "", "full_name": "", "set": False}
    except json.JSONDecodeError as exc:
        raise OperatorError(
            f"{STORE} is not valid JSON ({exc}). Every run would be attributed "
            f"to nobody, and the gap would not be visible in the results.")
    d.setdefault("set", bool(d.get("initials")))
    return d


def save(initials, full_name="", email=""):
    """Record who is at this station. Initials are normalised, not validated.

    Deliberately not validated beyond emptiness: a lab will have someone whose
    initials are one letter or four, and rejecting them teaches people to lie
    to the field rather than to fill it in.
    """
    ini = str(initials).strip().upper()
    if not ini:
        raise OperatorError(
            "Initials cannot be empty. An empty string would be stored as a "
            "value and every run stamped with it would look attributed when "
            "it is not - leave it UNSET instead, which is recorded as unset.")
    if not str(full_name).strip():
        raise OperatorError(
            f"A full name is needed alongside {ini!r}. Initials alone stop "
            f"being unambiguous the moment a second person shares them, which "
            f"is exactly the situation this is meant to survive.")
    doc = {
        "initials": ini,
        "full_name": str(full_name).strip(),
        "email": str(email).strip(),
        "machine": _machine(),
        "set": True,
        "set_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc


def clear():
    """Hand the station to someone else. Better than leaving the last name on."""
    if STORE.exists():
        STORE.write_text(json.dumps({"initials": "", "full_name": "",
                                     "set": False}, indent=2), encoding="utf-8")
    return load()


def initials():
    """Just the short form, or "" - for callers that only want a label."""
    return load().get("initials") or ""


def stamp(record=None, tool="", note=""):
    """Attach who, when and where to a provenance record.

    Returns a NEW dict rather than mutating - a stamp that quietly rewrote the
    record it was given would make it impossible to tell measured fields from
    added ones.
    """
    op = load()
    out = dict(record or {})
    out["operator"] = {
        "initials": op.get("initials") or None,
        "full_name": op.get("full_name") or None,
        "machine": op.get("machine") or _machine(),
        "set": bool(op.get("set")),
    }
    out["run_utc"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
    out["run_date"] = _dt.date.today().isoformat()
    if tool:
        out["tool"] = tool
    if note:
        out["operator_note"] = note
    if not op.get("set"):
        out["operator_unset"] = (
            "Nobody entered initials at this station, so this run has no "
            "owner. Recorded as unset rather than guessed - a wrong "
            "attribution names an innocent person as the source of a number, "
            "which is worse than an honest gap.")
    return out


def describe():
    """One line for a status bar. Says plainly when nobody is set."""
    op = load()
    if not op.get("set"):
        return "operator: not set - runs will be unattributed"
    return (f"operator: {op['initials']} ({op['full_name']}) "
            f"on {op.get('machine', '?')}")


# --------------------------------------------------------------------------- #
# The Hub field
# --------------------------------------------------------------------------- #
def add_field(parent, on_change=None):
    """Initials entry for the Hub control bar. Returns the widget, or None."""
    try:
        import tkinter as tk
        from tkinter import ttk, simpledialog
    except ImportError:                                    # pragma: no cover
        return None

    op = load()
    var = tk.StringVar(value=op.get("initials") or "")
    frame = ttk.Frame(parent)
    ttk.Label(frame, text="You").pack(side="left")
    entry = ttk.Entry(frame, textvariable=var, width=6)
    entry.pack(side="left", padx=(4, 0))

    # The full name stays ON SCREEN rather than being announced once. The
    # failure to catch is a student working a whole session under the last
    # person's initials, and a status message that scrolls away does not
    # catch it - a name sitting next to the field does.
    name_lbl = ttk.Label(frame, foreground="#666", width=18)
    name_lbl.pack(side="left", padx=(6, 0))

    def refresh():
        op_now = load()
        name_lbl.configure(
            text=op_now.get("full_name") or "nobody - runs unattributed",
            foreground="#666" if op_now.get("set") else "#B03030")
    refresh()

    def commit(_e=None):
        ini = var.get().strip().upper()
        if not ini:
            clear()
            if on_change:
                on_change(load())
            return
        cur = load()
        # Ask for the full name the first time these initials appear, and only
        # then. Asking every session would train people to dismiss it.
        if not cur.get("set") or cur.get("initials") != ini:
            name = simpledialog.askstring(
                "Who is this?",
                f"Full name for {ini}.\n\nInitials alone stop being "
                f"unambiguous once two people share them; the full name is "
                f"what makes a run traceable years from now.",
                parent=parent)
            if not name:
                var.set(cur.get("initials") or "")
                return
            save(ini, name)
        refresh()
        if on_change:
            on_change(load())

    entry.bind("<Return>", commit)
    entry.bind("<FocusOut>", commit)
    return frame
