"""Show a tool's effective version; offer the versions that could have changed it.

Publish stages 4 and 5, the visible half.

    from version_picker import open_picker
    open_picker(parent, "Endpoint egg counting", "tools/egg/egg_tool.py")

WHAT IS OFFERED, AND WHY IT IS SHORT. Only the versions where THIS MODULE
ACTUALLY DIFFERED. There are 22 published releases and a given tool changed in
a handful of them; listing all 22 would be noise, and a picker that reads as
noise does not get read. The list answers "which releases could possibly have
changed this tool's behaviour", which is the question someone chasing a
changed result actually has.

SELECTING A VERSION RELAUNCHES FROM THAT VERSION'S WHOLE TREE. Never a module
from one release against core files from another: that is a configuration
nobody has tested and nobody could reproduce. The chosen tree's own copy of
the script is run, with its own directory as the working directory, so its
imports resolve inside it.

AND IT DOES NOT TOUCH THE RUNNING SESSION. Starting an older version starts a
NEW process. Nothing about the window the student is looking at changes. This
is the same invariant publishing is built on - an update changes the next
launch, never the current one - and it applies just as much when the movement
is backwards.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent

try:
    import module_versions
    import launch_history
except ImportError:                                          # pragma: no cover
    sys.path.insert(0, str(APP_DIR))
    import module_versions
    import launch_history


def tree_for(version, root=None):
    """The published tree for a version, or None."""
    root = Path(root) if root else module_versions.PUBLISH_ROOT
    for known, path in module_versions.published_trees(root):
        if known == version:
            return path
    return None


def release_note(version, root=None):
    """(published date, one-line note) for a version. Blank when not recorded.

    The oldest trees predate the manifest and carry neither. They say so
    rather than borrowing a plausible-looking date from the filesystem: a
    folder's mtime is when it was last COPIED, which on a share that has been
    reorganised is not when it was published.
    """
    tree = tree_for(version, root)
    if tree is None:
        return "", ""
    try:
        info = json.loads((tree / "app" / "release_info.json").read_text(
            encoding="utf-8-sig"))
    except (OSError, ValueError):
        return "", ""
    when = str(info.get("published_utc", ""))[:10]
    note = str(info.get("note") or info.get("changelog") or "")
    return when, note


def offer(module, filename, index=None, history=None, current=None, root=None):
    """What the picker shows.

    Returns {"rows": [...], "revert_to": version|None, "pinned": version|None,
             "incomplete": bool}.
    """
    index = index if index is not None else module_versions.load_index()
    store = history or launch_history.LaunchHistory()
    # RESOLVE AGAINST module_versions.TREE, not this module's own ROOT. The
    # index's keys are paths relative to that tree, and two independent
    # notions of "the tree" is one too many - the first draft had both, and
    # the file set silently came back empty, which reads as "no release ever
    # changed this tool" rather than as an error.
    path = module_versions.TREE / filename
    incomplete = False
    if path.is_file():
        files, dynamic = module_versions.module_files(path)
        own, _shared = module_versions.split_own_shared(files, path)
        incomplete = bool(dynamic)
    else:
        files, own = set(), set()
    effective, story = module_versions.effective_version(files, index, own)
    current = current or effective
    versions = [version for version, _own, _shared, _hits in story]
    notes = store.annotate(module, versions, current=current)

    rows = []
    for version, n_own, n_shared, _hits in story:
        when, note = release_note(version, root)
        rows.append({
            "version": version, "when": when, "note": note,
            "own": n_own, "shared": n_shared,
            "changed": ("this tool's own code" if n_own
                        else "shared code it depends on"),
            "your_history": notes.get(version, ""),
        })
    return {"rows": rows, "effective": effective,
            "revert_to": store.revert_default(module, versions, current),
            "pinned": store.pinned(module), "incomplete": incomplete}


def launch_command(version, filename, root=None):
    """(argv, cwd) to run this tool from a published tree, or None."""
    tree = tree_for(version, root)
    if tree is None:
        return None
    script = tree / filename
    if not script.is_file():
        return None
    for candidate in (tree / ".venv" / "Scripts" / "pythonw.exe",
                      Path(os.path.expandvars(
                          r"%ProgramData%\LabTools\.venv\Scripts\pythonw.exe")),
                      Path(sys.executable)):
        try:
            if candidate.exists():
                return ([str(candidate), str(script)], str(script.parent))
        except OSError:
            continue
    return ([sys.executable, str(script)], str(script.parent))


def launch_version(module, version, filename, root=None, history=None):
    """Start this tool from an older published tree. Returns True on success."""
    command = launch_command(version, filename, root)
    if command is None:
        return False
    argv, cwd = command
    store = history or launch_history.LaunchHistory()
    env = None
    try:
        launch_id = store.record_launch(module, version, tree=cwd,
                                        tree_version=version)
        env = launch_history.launch_environment(module, version, launch_id)
    except Exception:                                        # noqa: BLE001
        env = None
    try:
        subprocess.Popen(argv, cwd=cwd, env=env)
        return True
    except OSError:
        return False


# --------------------------------------------------------------------- UI

def open_picker(parent, module, filename, current=None):
    """The dialog. Import of Tk is deferred so the core stays testable."""
    import tkinter as tk
    from tkinter import ttk, messagebox

    data = offer(module, filename, current=current)
    window = tk.Toplevel(parent)
    window.title(f"{module} - version history")
    window.geometry("760x460")

    header = (f"Effective version: v{data['effective'] or 'unknown'}")
    if data["pinned"]:
        header += f"    PINNED to v{data['pinned']}"
    tk.Label(window, text=header, font=("Segoe UI", 11, "bold"),
             anchor="w").pack(fill="x", padx=12, pady=(12, 2))
    tk.Label(window, anchor="w", justify="left", wraplength=720,
             text=("Only releases that changed this tool are listed. Opening "
                   "one starts a new window from that release; the session "
                   "you are in now is not affected."),
             ).pack(fill="x", padx=12)
    if data["incomplete"]:
        tk.Label(window, anchor="w", fg="#a05000", wraplength=720,
                 justify="left",
                 text=("This tool loads code by name at run time, so this "
                       "list may be incomplete.")).pack(fill="x", padx=12)

    columns = ("version", "when", "changed", "your_history", "note")
    table = ttk.Treeview(window, columns=columns, show="headings", height=12)
    for name, width in zip(columns, (80, 92, 170, 180, 220)):
        table.heading(name, text=name.replace("_", " "))
        table.column(name, width=width, anchor="w")
    for row in data["rows"]:
        table.insert("", "end", values=(
            f"v{row['version']}", row["when"] or "-", row["changed"],
            row["your_history"], row["note"][:70] or "-"))
    table.pack(fill="both", expand=True, padx=12, pady=8)
    if data["revert_to"]:
        for item in table.get_children():
            if table.item(item, "values")[0] == f"v{data['revert_to']}":
                table.selection_set(item)
                table.see(item)
                break

    def chosen():
        selection = table.selection()
        if not selection:
            return None
        return table.item(selection[0], "values")[0].lstrip("v")

    def do_open():
        version = chosen()
        if not version:
            messagebox.showinfo(module, "Select a version first.", parent=window)
            return
        if launch_version(module, version, filename):
            messagebox.showinfo(
                module,
                f"Opening {module} from v{version} in a new window.\n\n"
                f"This window and anything already running are unchanged.",
                parent=window)
        else:
            messagebox.showerror(
                module, f"Could not start v{version}. That release may not be "
                        f"on the share, or may not contain this tool.",
                parent=window)

    def do_pin():
        version = chosen()
        if not version:
            return
        launch_history.LaunchHistory().pin(module, version)
        messagebox.showinfo(
            module, f"{module} pinned to v{version} for you only.\n\n"
                    f"Nobody else is affected.", parent=window)
        window.destroy()

    def do_unpin():
        launch_history.LaunchHistory().unpin(module)
        messagebox.showinfo(module, "Pin removed.", parent=window)
        window.destroy()

    bar = tk.Frame(window)
    bar.pack(fill="x", padx=12, pady=(0, 12))
    tk.Button(bar, text="Open this version", command=do_open).pack(side="left")
    tk.Button(bar, text="Pin to this version", command=do_pin
              ).pack(side="left", padx=6)
    tk.Button(bar, text="Remove pin", command=do_unpin).pack(side="left")
    tk.Button(bar, text="Close", command=window.destroy).pack(side="right")
    if data["revert_to"]:
        tk.Label(bar, text=(f"Suggested: v{data['revert_to']} - your most "
                            f"recent clean session"), fg="#005000"
                 ).pack(side="right", padx=12)
    return window
