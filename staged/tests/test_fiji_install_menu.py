"""Regression tests for fiji/install_menu.py.

The installer's search paths still pointed at a RGBCaMP_Tracker/ layout that
the reorganisation replaced, so it located NEITHER tool: it found Fiji, created
an empty plugins/AGVGLab folder, and installed nothing. The copies sitting in
Fiji had been put there some other way and had gone stale by months.

The test that matters is therefore not "does install() run" but "does every
entry in TOOLS actually resolve to a file on disk" - a path list is exactly the
kind of thing that rots silently when directories move.
"""
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fiji"))
import install_menu as im

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("fiji install_menu - regression\n")

check("TOOLS is not empty", len(im.TOOLS) > 0, f"{len(im.TOOLS)} entries")

# --- every declared tool must resolve -----------------------------------
for label, fname, search, kind in im.TOOLS:
    found = im.find_tool_file(fname, search)
    check(f"{label} resolves to a file on disk",
          found is not None and Path(found).exists(),
          str(found) if found else f"searched {search}")

# --- and must resolve to the CURRENT copy, not a stale duplicate ---------
# A second copy left behind by an old layout would let the installer ship
# months-old code while every path check above still passed.
for label, fname, search, kind in im.TOOLS:
    found = im.find_tool_file(fname, search)
    if found is None:
        continue
    matches = [p for p in ROOT.rglob(fname)
               if "__pycache__" not in str(p) and "archive" not in str(p).lower()]
    check(f"{label} has exactly one copy in the tree",
          len(matches) == 1, f"{len(matches)} found")

# --- install() actually copies, and reports honestly ---------------------
with tempfile.TemporaryDirectory() as tmp:
    fake_fiji = Path(tmp) / "Fiji.app"
    (fake_fiji / "plugins").mkdir(parents=True)
    target, installed, missing, notes = im.install(fake_fiji)

    check("install() reports nothing missing", missing == [], missing)
    check("install() reports every tool installed",
          len(installed) == len(im.TOOLS), f"{len(installed)}/{len(im.TOOLS)}")
    check("target is the AGVGLab submenu folder",
          target == fake_fiji / "plugins" / "AGVGLab", str(target))

    copied = sorted(p.name for p in target.iterdir()) if target.exists() else []
    check("every declared file is actually on disk afterwards",
          copied == sorted(f for _, f, _, _ in im.TOOLS), copied)

    # byte-identical, not merely present - a truncated or stale copy would
    # otherwise pass a name check
    for label, fname, search, kind in im.TOOLS:
        src = im.find_tool_file(fname, search)
        dst = target / fname
        same = (src is not None and dst.exists()
                and Path(src).read_bytes() == dst.read_bytes())
        check(f"{label} copied byte-identical", same)

# --- a missing tool must be REPORTED, not swallowed ----------------------
saved = im.TOOLS
try:
    im.TOOLS = list(saved) + [("Imaginary Tool", "does_not_exist_xyz.ijm",
                               ["."], "macro")]
    with tempfile.TemporaryDirectory() as tmp:
        fake_fiji = Path(tmp) / "Fiji.app"
        (fake_fiji / "plugins").mkdir(parents=True)
        _, installed, missing, _ = im.install(fake_fiji)
    check("a tool that cannot be found is reported as missing",
          any("Imaginary Tool" in m for m in missing), missing)
    check("a missing tool is not counted as installed",
          not any("Imaginary Tool" in i for i in installed))
finally:
    im.TOOLS = saved

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("FIJI_INSTALL_MENU_REGRESSION_PASS")
