"""Controls must WRAP when a window narrows, never disappear.

Andres: "when I resize it horizontally the buttons disappear rather than
rearranging in the new geometry." That is Tk's pack, which does not wrap - it
silently stops allocating space to widgets that no longer fit, leaving a tidy
row with things missing from it and nothing to signal the loss.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("flow layout - regression\n")

try:
    import tkinter as tk
    from tkinter import ttk
    root = tk.Tk()
    root.withdraw()
    HAVE_TK = True
except Exception as exc:                                   # pragma: no cover
    HAVE_TK = False
    print(f"  tkinter unavailable ({exc}); cannot test layout")

if HAVE_TK:
    import flow_layout as fl   # noqa: E402

    win = tk.Toplevel(root)
    win.geometry("900x200")
    bar = fl.FlowFrame(win)
    bar.pack(fill="x")

    LABELS = ["Load", "Acquisition advisor", "Filter", "Show all tools",
              "Status", "Check for updates", "Revert update", "Publish"]
    made = [bar.add(ttk.Button(bar, text=t)) for t in LABELS]
    win.update_idletasks()
    win.update()

    check("every control is created", len(made) == len(LABELS))
    check("...and every one is placed, not dropped",
          all(w.winfo_manager() == "place" for w in made))

    # --- wide: one row ----------------------------------------------------
    win.geometry("1200x200")
    win.update_idletasks(); win.update()
    bar.event_generate("<Configure>", width=1200)
    win.update_idletasks(); win.update()
    wide_rows = bar.rows()
    check("at full width the controls sit on one row", wide_rows == 1,
          f"{wide_rows} row(s)")

    # --- narrow: MORE ROWS, and still all present -------------------------
    win.geometry("380x260")
    win.update_idletasks(); win.update()
    bar.event_generate("<Configure>", width=380)
    win.update_idletasks(); win.update()
    narrow_rows = bar.rows()

    check("narrowing the window WRAPS instead of dropping controls",
          narrow_rows > wide_rows, f"{wide_rows} row -> {narrow_rows} rows")
    check("...and all eight controls are still managed",
          sum(1 for w in made if w.winfo_manager() == "place") == len(LABELS),
          f"{sum(1 for w in made if w.winfo_manager() == 'place')} of {len(LABELS)}")
    check("...none is pushed off the left edge",
          all(w.winfo_x() >= 0 for w in made))
    check("...and none starts beyond the frame's width",
          all(w.winfo_x() < max(bar.winfo_width(), 380) for w in made),
          f"widest x = {max(w.winfo_x() for w in made)}")

    # --- widening restores the single row ---------------------------------
    win.geometry("1200x200")
    win.update_idletasks(); win.update()
    bar.event_generate("<Configure>", width=1200)
    win.update_idletasks(); win.update()
    check("widening again collapses back to one row", bar.rows() == 1,
          f"{bar.rows()} row(s)")

    # --- the minimum size floor -------------------------------------------
    fl.set_minimum_size(win, 700, 480)
    win.update_idletasks()
    check("a minimum window size can be set so a drag cannot crush it",
          tuple(win.minsize()) == (700, 480), f"{win.minsize()}")

    # --- an empty flow does not crash -------------------------------------
    empty = fl.FlowFrame(win)
    empty.pack(fill="x")
    win.update_idletasks()
    check("an empty flow frame lays out without error", empty.rows() == 0)

    root.destroy()

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("FLOW_LAYOUT_PASS")
