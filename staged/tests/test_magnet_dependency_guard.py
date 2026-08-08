"""magpylib must be present AND the right major version before any field is computed.

This covers a defect that was live on every lab machine: magpylib was reachable
from the orientation workbench but was in no installer, so magnetotaxis raised
on use and the error told the reader to "install the declared dependency" -
which was declared nowhere.

The version half matters more than the missing half. v5 takes polarization in
tesla with dimensions in metres, which is what MagnetProvider passes; v4 took
magnetization in mT with dimensions in mm. A v4 install is not a crash, it is
a plausible number that is wrong by orders of magnitude - the worst kind of
defect, and the reason the pin exists rather than a bare `pip install magpylib`.
"""
import builtins
from pathlib import Path
import re
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import stimulus_fields as sf                     # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


MAGNET = dict(shape="cylinder", dimensions_mm=(6, 3), remanence_t=1.3,
              magnetization_direction_xyz=(0, 0, 1), position_xyz_mm=(0, 0, 10),
              distance_uncertainty_mm=0.5)


def build_with(fake_module):
    """Construct a MagnetProvider with magpylib replaced or removed."""
    saved = sys.modules.get("magpylib")
    real_import = builtins.__import__
    if fake_module is None:
        def blocked(name, *a, **k):
            if name == "magpylib":
                raise ImportError("magpylib is not installed")
            return real_import(name, *a, **k)
        builtins.__import__ = blocked
        sys.modules.pop("magpylib", None)
    else:
        sys.modules["magpylib"] = fake_module
    try:
        return sf.MagnetProvider(**MAGNET), None
    except RuntimeError as error:
        return None, error
    finally:
        builtins.__import__ = real_import
        if saved is not None:
            sys.modules["magpylib"] = saved
        elif fake_module is not None:
            sys.modules.pop("magpylib", None)


print("magnet dependency guard - regression\n")

# ---------------------------------------------------------------- installed
import magpylib                                  # noqa: E402
check("magpylib is importable in this runtime at all - it was in no "
      "installer until now, so this line is the whole point",
      magpylib.__version__.startswith("5."), magpylib.__version__)
provider, error = build_with(magpylib)
check("with magpylib 5.x installed, a magnet provider is built - the "
      "dependency really is satisfied in this runtime now",
      provider is not None and error is None,
      error if error else sf.__name__)
if provider is not None:
    check("and it exposes a true field direction, so the assay can run",
          provider.has_true_direction is True)

# ------------------------------------------------------------------ missing
_, error = build_with(None)
check("with magpylib absent, magnetic analysis is refused", error is not None)
if error:
    text = str(error)
    check("the refusal NAMES magpylib rather than saying 'the declared "
          "dependency', which named nothing", "magpylib" in text)
    check("it says to re-run Setup_Lab_Tools.bat, which is the only thing "
          "that installs it", "Setup_Lab_Tools.bat" in text)
    check("and warns that an app update will NOT fix it - the updater swaps "
          "files and never runs pip",
          "update" in text.lower() and "not" in text.lower(), text.split("\n")[-1])

# ------------------------------------------------------------- wrong version
for bad in ("4.5.1", "3.0.2", "6.0.0"):
    fake = types.ModuleType("magpylib")
    fake.__version__ = bad
    _, error = build_with(fake)
    check(f"magpylib {bad} is refused, because it would return plausible "
          f"field values that are simply wrong", error is not None,
          str(error)[:60] if error else "ACCEPTED")
    if error:
        check(f"  and the message reports the version actually found ({bad})",
              bad in str(error), str(error).splitlines()[0])

# A 5.x stub needs enough of the real surface to get past the version gate
# and into construction - the point is that the GATE lets it through.
good = types.ModuleType("magpylib")
good.__version__ = "5.9.9"
good.magnet = types.SimpleNamespace(
    Cylinder=lambda **kw: types.SimpleNamespace(**kw),
    Cuboid=lambda **kw: types.SimpleNamespace(**kw))
_, error = build_with(good)
check("any 5.x is accepted, so a patch release does not block the lab",
      error is None, str(error)[:70] if error else "accepted")

# --------------------------------------------------- the installer agrees
setup = (ROOT / "Setup_Lab_Tools.bat").read_text(encoding="utf-8", errors="replace")
check("Setup_Lab_Tools.bat installs magpylib at all - the gap that made "
      "magnetotaxis fail on every machine", "magpylib" in setup)
# Look at the pip line itself, not the comment above it explaining the pin.
pip_lines = [ln for ln in setup.splitlines()
             if "pip install" in ln and "magpylib" in ln]
check("magpylib is on the pip install line, not merely mentioned in a comment",
      bool(pip_lines), pip_lines[:1])
pin = re.search(r"magpylib[><=,\d.]*", pip_lines[0]) if pip_lines else None
check("and pins it to 5.x, so a fresh install cannot pick up v4 or v6",
      pin is not None and ">=5" in pin.group(0) and "<6" in pin.group(0),
      pin.group(0) if pin else "no pin found")

# THE FACT MOVED, THE ASSERTION DID NOT. This used to read
# staged/app/release_info.json. That file was a STALE RELEASE STAMP: it
# asserted a version staged did not have, which is what made a Hub running
# from staged display "WINK v11.137" while executing entirely different code.
# It is deleted, and publish_release.py now REFUSES to publish if one
# reappears in staged.
#
# The gate itself did not go away - it moved to where publishing actually
# reads it. MIN_RUNTIME_VERSION is what sends a machine whose environment
# lacks magpylib to Setup_Lab_Tools.bat instead of half-updating it, since
# the updater swaps program files and never runs pip.
publish = (ROOT / "tools" / "publish" / "publish_release.py").read_text(
    encoding="utf-8")
pinned = re.search(r'MIN_RUNTIME_VERSION\s*=\s*"([\d.]+)"', publish)
check("the published runtime floor is declared where publishing reads it",
      pinned is not None,
      pinned.group(1) if pinned else "MIN_RUNTIME_VERSION not found")
check("the runtime version was bumped, so machines missing the library are "
      "gated out of the update instead of half-updated",
      pinned is not None and pinned.group(1) != "1.0.0",
      pinned.group(1) if pinned else "not found")

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("MAGNET_DEPENDENCY_GUARD_PASS")
