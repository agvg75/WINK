"""The LCARS theme: optional, reversible, and never able to stop a tool."""
from pathlib import Path
import os
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

os.environ["WINK_THEME_PREF"] = str(Path(tempfile.mkdtemp()) / "theme.json")

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("LCARS theme - regression\n")
import theme_lcars as th   # noqa: E402

# --- preference -----------------------------------------------------------
check("the theme is OFF by default", th.load_preference() is False)
th.save_preference(True)
check("...and the choice persists", th.load_preference() is True)
th.save_preference(False)
check("...both ways", th.load_preference() is False)

# --- the palette ----------------------------------------------------------
check("the LCARS palette is present",
      th.GOLDEN_TANOI == "#FFCC66" and th.MARS == "#CC6666")
check("the field is a dark NEUTRAL, not pure black",
      th.FIELD != "#000000",
      f"{th.FIELD} - black under dense tables and long text costs readability")


def _contrast(a, b):
    def lum(h):
        r, g, bl = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
        f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(bl)
    l1, l2 = sorted((lum(a), lum(b)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


check("body text on the field clears the 4.5:1 readability bar",
      _contrast(th.PAPER, th.FIELD) >= 4.5,
      f"{_contrast(th.PAPER, th.FIELD):.1f}:1")
check("dark text on a golden panel clears it too",
      _contrast(th.INK, th.GOLDEN_TANOI) >= 4.5,
      f"{_contrast(th.INK, th.GOLDEN_TANOI):.1f}:1")
check("...and on the error colour",
      _contrast(th.INK, th.MARS) >= 4.5,
      f"{_contrast(th.INK, th.MARS):.1f}:1")

# --- applying it ----------------------------------------------------------
try:
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    HAVE_TK = True
except Exception as exc:                                   # pragma: no cover
    HAVE_TK = False
    print(f"  tkinter unavailable ({exc}); skipping the applied checks")

if HAVE_TK:
    from tkinter import ttk

    check("the theme applies", th.apply(root, True) is True)
    style = ttk.Style(root)
    check("...recolouring buttons to a warm panel",
          style.lookup("TButton", "background") == th.GOLDEN_TANOI)
    check("...with dark text on them",
          style.lookup("TButton", "foreground") == th.INK)
    check("...and a font this machine actually has",
          th.available_font(root) in th.FONT_STACK,
          th.available_font(root))

    check("turning it off is complete, not partial",
          th.apply(root, False) is False
          and style.lookup("TButton", "background") != th.GOLDEN_TANOI)

    el = th.elbow(root)
    check("the elbow draws", el is not None and el.winfo_class() == "Canvas")

    tog = th.add_toggle(root, root)
    check("a toggle can be added to any control bar", tog is not None)

    # The property that matters most: a broken theme must not stop a tool.
    broken = object()
    check("applying to a non-window returns False instead of raising",
          th.apply(broken, True) is False)

    root.destroy()

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("THEME_LCARS_PASS")
