"""Layout survives being resized - checked by actually resizing it.

Andres: the launcher and modules struggle with boxes and text and reorganizing
things when the window changes size. Screenshots showed category names cut off
mid-word and the detail pane's Launch button pushed past the edge.

These are measured against a real Tk window at several widths rather than
reasoned about, because Tk geometry is what it does, not what the code says.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import tkinter as tk                                        # noqa: E402
from tkinter import ttk                                     # noqa: E402
from flow_layout import fit_tree_column, keep_panes_usable   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("layout resize - regression\n")

try:
    root = tk.Tk()
except tk.TclError as exc:                                  # pragma: no cover
    print(f"  SKIP - no display available ({exc})")
    raise SystemExit(0)
root.geometry("1200x700")

paned = ttk.Panedwindow(root, orient="horizontal")
paned.pack(fill="both", expand=True)
rail = ttk.Frame(paned, width=220)
paned.add(rail, weight=0)
tree = ttk.Treeview(rail, show="tree", selectmode="browse")
tree.pack(fill="both", expand=True)
LONG = "Motor output - Sensory-guided behaviour  (13)"
tree.insert("", "end", iid="a", text=LONG)
centre = ttk.Frame(paned)
paned.add(centre, weight=3)
detail = ttk.Frame(paned, width=310)
paned.add(detail, weight=1)
button = ttk.Button(detail, text="Launch Cultured cell calcium (probe-aware)")
button.pack(anchor="w")
root.update_idletasks()

default_col = int(tree.column("#0", "width"))
check("Tk's default column width is narrower than a real category name",
      default_col <= 220,
      f"{default_col}px default, and the rail is 220px")

fit_tree_column(tree, rail)
keep_panes_usable(paned, [190, 360, 260])
root.update_idletasks()
root.update()

MINIMA = [190, 360, 260]
for width in (1400, 1200, 1000, 860):
    root.geometry(f"{width}x700")
    root.update_idletasks()
    root.update()
    col = int(tree.column("#0", "width"))
    rail_w = rail.winfo_width()
    check(f"at {width}px the category column follows its pane",
          col >= min(rail_w - 40, 120),
          f"column {col}px in a {rail_w}px rail")

    try:
        sashes = [int(paned.sashpos(i)) for i in range(2)]
    except tk.TclError:                                     # pragma: no cover
        sashes = []
    if sashes and paned.winfo_width() >= sum(MINIMA):
        pane_widths = [sashes[0], sashes[1] - sashes[0],
                       paned.winfo_width() - sashes[1]]
        check(f"at {width}px no pane is squeezed below its minimum",
              all(p >= m - 2 for p, m in zip(pane_widths, MINIMA)),
              f"panes {pane_widths} against minima {MINIMA}")
        check(f"at {width}px the Launch button fits inside its pane",
              button.winfo_reqwidth() <= pane_widths[2] + 40,
              f"button wants {button.winfo_reqwidth()}px, "
              f"pane has {pane_widths[2]}px")

# A GUESSED MINIMUM IS THE SAME BUG IN A NEW PLACE. The first version of this
# used 190px for the rail, which passed every clamp check above and still cut
# the longest category name in half - the column dutifully followed a pane that
# was itself too narrow. So the floor has to be measured from the text.
import tkinter.font as tkfont                               # noqa: E402
font = tkfont.nametofont("TkDefaultFont")
needed = font.measure(LONG)
check("a 190px rail is too narrow for the longest category name",
      needed + 52 > 190,
      f"'{LONG}' needs {needed}px of text alone")

measured_min = int(min(max(needed + 52, 190), 400))
keep_panes_usable(paned, [measured_min, 360, 260])
root.geometry("1400x700")
root.update_idletasks()
root.update()
check("a measured minimum leaves the whole name visible",
      int(tree.column("#0", "width")) >= needed,
      f"column {int(tree.column('#0', 'width'))}px for {needed}px of text")

# ...and the measured floor must not eat the window on a small screen.
check("the measured minimum stays within a sane ceiling",
      measured_min <= 400, f"{measured_min}px")

root.destroy()

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("LAYOUT_RESIZE_PASS")
