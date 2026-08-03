"""Regression tests for app/myocyte_schematic.py.

The diagram is generated rather than stored so that it cannot drift out of
step with the segmentation the tools measure with. These tests exercise
exactly that claim: boundaries match the extractor's own profile, the
anatomy the lab specified lands where it should, and the module stays
importable from a Tkinter tool without hijacking the backend.
"""
from pathlib import Path
import sys
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("myocyte_schematic - regression\n")

# --- importing must be inert -------------------------------------------
# A Tkinter tool imports this to draw into an embedded canvas. If importing
# selected a backend, that tool would lose its own.
_before = sys.modules.get("matplotlib")
import myocyte_schematic as ms          # noqa: E402

check("importing does not pull in matplotlib.pyplot",
      "matplotlib.pyplot" not in sys.modules or _before is not None)

# --- boundaries mirror buildMuscleBoundaries() -------------------------
frac = ms.boundaries()
check("boundaries has n_seg+1 entries", len(frac) == ms.N_SEG + 1,
      f"{len(frac)}")
check("boundaries run 0..1 exactly", frac[0] == 0.0 and frac[-1] == 1.0)
check("boundaries are strictly increasing", bool(np.all(np.diff(frac) > 0)))

# the raised cosine is symmetric, so the profile must be too: cell k and
# cell n-1-k are the same size. If this breaks, the diagram and the
# extractor have diverged.
sizes = np.diff(frac)
check("cell sizes are symmetric head-to-tail, as the raised cosine implies",
      bool(np.allclose(sizes, sizes[::-1])))
check("mid-body myocytes are larger than terminal ones",
      sizes[ms.N_SEG // 2] > sizes[0] and sizes[ms.N_SEG // 2] > sizes[-1],
      f"mid {sizes[ms.N_SEG // 2]:.4f} vs ends {sizes[0]:.4f}")

# --- the anatomy the lab specified -------------------------------------
ph = frac[ms.PHARYNX_THROUGH]
check("pharynx spans through myocyte 7", ms.PHARYNX_THROUGH == 7)
check("pharynx ends at a plausible fraction of body length (0.20-0.30)",
      0.20 < ph < 0.30, f"{ph:.3f}")
check("vulva sits at mid-body", abs(ms.VULVA_FRAC - 0.5) < 1e-9)
check("vulva falls on a cell boundary rather than inside a myocyte",
      bool(np.min(np.abs(frac - ms.VULVA_FRAC)) < 1e-9),
      "cell 12/13 boundary")

# --- 48 myocytes, two bands, no anatomical identity ---------------------
cells = ms.cell_polygons()
check("two bands of n_seg myocytes are drawn", len(cells) == 2 * ms.N_SEG,
      f"{len(cells)}")
bands = {b for b, _, _, _, _ in cells}
check("exactly two bands", bands == {0, 1})
check("band 0 lies one side of the midline and band 1 the other",
      all(hi > 0 for b, _, _, lo, hi in cells if b == 0)
      and all(lo < 0 for b, _, _, lo, hi in cells if b == 1))

src = (ROOT / "app" / "myocyte_schematic.py").read_text(encoding="utf-8")
for word in ("dorsal_label", "dorsal_known"):
    check(f"the diagram does not consume {word}", word not in src)
# Parse the module and collect every string that reaches a drawing call, so
# this asserts what is actually rendered rather than that a word is absent
# from the file - the docstring legitimately discusses dorsal/ventral in
# order to explain why the diagram refuses to claim it.
import ast                                # noqa: E402

drawn_strings = []
for node in ast.walk(ast.parse(src)):
    if not isinstance(node, ast.Call):
        continue
    fn = node.func
    name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
    if name not in ("text", "annotate", "set_title", "set_xlabel", "lead"):
        continue
    for arg in list(node.args) + [kw.value for kw in node.keywords]:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            drawn_strings.append(arg.value.lower())

check("the drawing code renders at least one label, so the scan is meaningful",
      len(drawn_strings) > 0, f"{len(drawn_strings)} label strings")
check("no rendered label claims dorsal or ventral identity",
      not any("dorsal" in s or "ventral" in s for s in drawn_strings),
      ", ".join(sorted(set(drawn_strings))[:6]))

# --- n_seg is honoured, not assumed ------------------------------------
alt = ms.boundaries(12)
check("a 12-per-side profile still produces valid boundaries",
      len(alt) == 13 and alt[0] == 0.0 and alt[-1] == 1.0)
check("cell_polygons follows n_seg rather than the default",
      len(ms.cell_polygons(12)) == 24)
try:
    ms.boundaries(1)
    check("n_seg below 2 is refused", False)
except ValueError:
    check("n_seg below 2 is refused", True)

# --- the tinting contract the movie depends on -------------------------
import matplotlib                        # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt          # noqa: E402

fig, ax = plt.subplots()
handles = ms.draw(ax, values=None)
check("a blank template still creates channel patches, so a caller can tint "
      "per frame without rebuilding the figure",
      len(handles["channels"]) > 0)
check("three channel patches per myocyte",
      len(handles["channels"]) == 3 * 2 * ms.N_SEG,
      f"{len(handles['channels'])}")
check("one outline patch per myocyte",
      len(handles["cells"]) == 2 * ms.N_SEG)
plt.close(fig)

fig, ax = plt.subplots()
vals = np.zeros((ms.N_SEG, 2, 3))
vals[5, 0, 1] = 1.0                       # one bright green myocyte
handles = ms.draw(ax, values=vals)
bright = handles["channels"][(0, 5, 1)].get_facecolor()
dark = handles["channels"][(0, 6, 1)].get_facecolor()
check("a value of 1.0 renders saturated and 0.0 renders white",
      bright[1] < dark[1] and dark[0] > 0.98,
      f"green {bright[:3]} vs unlit {dark[:3]}")
plt.close(fig)

fig, ax = plt.subplots()
try:
    ms.draw(ax, values=np.zeros((ms.N_SEG, 2)))
    check("a wrongly shaped values array is refused rather than broadcast",
          False)
except ValueError:
    check("a wrongly shaped values array is refused rather than broadcast",
          True)
plt.close(fig)

# --- the reference PNG the morphometry tool shows -----------------------
with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp) / "schematic.png"
    ms.render_reference(out)
    check("render_reference writes a non-trivial image",
          out.exists() and out.stat().st_size > 20_000,
          f"{out.stat().st_size if out.exists() else 0} bytes")

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("MYOCYTE_SCHEMATIC_REGRESSION_PASS")
