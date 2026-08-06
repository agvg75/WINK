"""Each person's own data, arranged the way they arranged it.

Andres: this should live in the Hub - a tab just for him showing the whole
lab's data, and every student seeing their own, arranged how they chose.

WHO IS LOOKING COMES FROM THE HUB, not from a login. `operator_identity`
already holds the initials someone typed on the Hub, so this needs no separate
sign-in. If nobody set initials, it says so and shows nothing rather than
guessing - showing one student another's data because a field was blank would
be worse than showing nothing at all.

THE LAB LEAD SEES EVERYTHING, and that is a setting rather than a hard-coded
name. A tool that special-cases one person by name stops working the day
somebody else runs the lab, and does so silently.

THE CATALOGUE IS SHARED, THE ARRANGEMENT IS PERSONAL. One file on the lab
drive records what each folder actually contains; each person's preferred
grouping - by assay, by strain, by date - is theirs and lives locally. So two
people can look at the same experiment through completely different trees
without either of them moving anything.

NOTHING HERE OPENS A FILE OR MOVES ONE. It reads the catalogue, shows a tree,
and can open a folder in Explorer. The heavy work - surveying, building the
symlink views - is elsewhere and is explicitly invoked.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

# Who sees the whole lab. A setting, not a name in the code.
LAB_LEAD_INITIALS = ("AVG", "AV")

DEFAULT_CATALOGUE = Path(
    os.environ.get("WINK_CATALOGUE",
                   r"L:\10_AGVG LAB\Lab Tools\folder_catalogue.json"))
DEFAULT_ARRANGEMENT = ("assay", "year")


class MyDataError(Exception):
    """Refusals that name the consequence."""


def current_person():
    """Who the Hub says is at this station."""
    try:
        import operator_identity
        op = operator_identity.load()
    except Exception:
        return {"set": False, "initials": None, "full_name": None}
    return {"set": bool(op.get("set")), "initials": op.get("initials"),
            "full_name": op.get("full_name")}


def sees_everything(person, lead_initials=LAB_LEAD_INITIALS):
    return bool(person.get("initials")) and \
        person["initials"].upper() in {i.upper() for i in lead_initials}


def entries_for(catalogue, person, *, lead_initials=LAB_LEAD_INITIALS):
    """The rows this person should see, and why that set and not another."""
    entries = catalogue.get("entries", [])
    if not person.get("set"):
        return [], {
            "shown": "nothing",
            "why": ("Nobody has entered initials on the Hub, so there is no "
                    "way to tell whose data this is. Showing one person's "
                    "folders to another because a field was blank would be "
                    "worse than showing nothing."),
        }
    if sees_everything(person, lead_initials):
        return entries, {
            "shown": "everything",
            "why": (f"{person['initials']} is set as a lab lead, so this is "
                    f"the whole lab's data."),
        }
    ini = person["initials"].upper()
    name = (person.get("full_name") or "").lower()
    first = name.split()[0] if name else ""
    mine = []
    for e in entries:
        who = str(e.get("person", "")).strip()
        if not who:
            continue
        if who.upper() == ini or (first and first in who.lower()):
            mine.append(e)
    return mine, {
        "shown": "own",
        "why": (f"Matched on the person field against {person['initials']}"
                + (f" / {first}" if first else "") + "."),
        "unattributed": sum(1 for e in entries
                            if not str(e.get("person", "")).strip()),
    }


def arrange(entries, by=DEFAULT_ARRANGEMENT, *, missing="(unlabelled)"):
    """Group entries into a nested dict for display - the personal part.

    Purely a view. Nothing on disk is grouped, moved or linked by this; two
    people can arrange the same experiments differently at the same time.
    """
    tree = {}
    for e in entries:
        node = tree
        for field in by:
            key = str(e.get(field, "") or "").strip() or missing
            node = node.setdefault(key, {})
        node.setdefault("__items__", []).append(e)
    return tree


def summarise(entries):
    """A line a person can read at a glance."""
    if not entries:
        return {"n": 0, "text": "Nothing catalogued yet."}
    people = {str(e.get("person", "")).strip() for e in entries} - {""}
    assays = {str(e.get("assay", "")).strip() for e in entries} - {""}
    unlabelled = sum(1 for e in entries if not str(e.get("assay", "")).strip())
    return {
        "n": len(entries), "n_people": len(people), "n_assays": len(assays),
        "n_unlabelled": unlabelled,
        "text": (f"{len(entries)} folders, {len(assays)} assay type(s), "
                 f"{len(people)} people"
                 + (f", {unlabelled} not yet labelled" if unlabelled else "")),
    }


def open_in_explorer(path):
    """Show a folder. Opens Explorer, never the data."""
    p = Path(path)
    if not p.exists():
        raise MyDataError(
            f"{p} is not there. If the drive is disconnected this looks "
            f"exactly like a folder that was moved - check the drive before "
            f"concluding anything is lost.")
    subprocess.Popen(["explorer", str(p)])
    return str(p)


# --------------------------------------------------------------------------- #
# The panel
# --------------------------------------------------------------------------- #
def build_panel(parent, *, catalogue_path=None, by=DEFAULT_ARRANGEMENT):
    """A tree of this person's data, grouped their way. Returns the frame."""
    import tkinter as tk
    from tkinter import ttk

    try:
        import folder_aliases as fa
        cat = fa.load_catalogue(catalogue_path or DEFAULT_CATALOGUE)
    except Exception as exc:
        cat = {"entries": [], "load_error": str(exc)}

    person = current_person()
    entries, scope = entries_for(cat, person)
    summary = summarise(entries)

    frame = ttk.Frame(parent)
    who = (f"{person['full_name']} ({person['initials']})"
           if person.get("set") else "nobody signed in")
    ttk.Label(frame, text=f"Data for {who}",
              font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(6, 2))
    ttk.Label(frame, text=summary["text"], foreground="#555").pack(anchor="w")
    ttk.Label(frame, text=scope["why"], foreground="#777", wraplength=680,
              justify="left").pack(anchor="w", pady=(2, 8))

    if cat.get("load_error"):
        ttk.Label(frame, foreground="#B03030", wraplength=680, justify="left",
                  text=(f"The shared catalogue could not be read: "
                        f"{cat['load_error']}\n\nThis is the file that records "
                        f"what each folder contains. Without it nothing can "
                        f"be listed here, but no data is affected.")
                  ).pack(anchor="w")
        return frame

    tree = ttk.Treeview(frame, columns=("path",), show="tree headings",
                        height=20)
    tree.heading("#0", text="Arranged by " + " / ".join(by))
    tree.heading("path", text="Real location")
    tree.column("path", width=380)
    tree.pack(fill="both", expand=True)

    def insert(node, parent_id=""):
        for key in sorted(k for k in node if k != "__items__"):
            nid = tree.insert(parent_id, "end", text=key, open=False)
            insert(node[key], nid)
        for e in node.get("__items__", []):
            tree.insert(parent_id, "end", text=e.get("alias", "?"),
                        values=(e.get("real_path", ""),))

    insert(arrange(entries, by))

    bar = ttk.Frame(frame)
    bar.pack(fill="x", pady=(8, 0))

    def open_selected():
        sel = tree.selection()
        if not sel:
            return
        path = tree.item(sel[0], "values")
        if path and path[0]:
            try:
                open_in_explorer(path[0])
            except MyDataError as exc:
                from tkinter import messagebox
                messagebox.showwarning("Not found", str(exc), parent=frame)

    ttk.Button(bar, text="Open in Explorer", command=open_selected
               ).pack(side="left")
    ttk.Label(bar, foreground="#777",
              text="  Arrangement is yours; the catalogue is shared."
              ).pack(side="left")
    return frame


def main():
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("My data")
    root.geometry("900x620")
    try:
        from process_ui import install_error_reporting
        install_error_reporting(root)
    except Exception as exc:
        print("error reporting unavailable:", exc)
    build_panel(root).pack(fill="both", expand=True, padx=14, pady=10)
    root.mainloop()


if __name__ == "__main__":
    main()
