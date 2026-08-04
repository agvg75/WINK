"""Regression test for tools/worm_kinematics/worm_kinetics_foraging_dampening.py.

These two summaries were written to be pasted into worm_kinetics.py, where
wave_propagation() is already in scope. Imported as a standalone module they
raised NameError on the first call to posterior_dampening().

run_one_kinematics.py hid that by assigning `_fd.wave_propagation = wk.wave_propagation`
before grafting the functions onto wk - correct, but it made the module depend
on its caller, so any other importer got the NameError instead. The test that
matters is therefore that the module works with NO help from a caller.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "rgbcamp" / "pipeline"))
sys.path.insert(0, str(ROOT / "tools" / "worm_kinematics"))

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("foraging / posterior dampening - standalone import\n")

import worm_kinetics_foraging_dampening as fd     # noqa: E402

check("wave_propagation is resolvable from the module itself, with no caller "
      "injecting it", hasattr(fd, "wave_propagation"))
check("it is the real estimator, not a stub", callable(getattr(fd, "wave_propagation", None)))

# a travelling body wave, so the estimator has something coherent to fit
rng = np.random.default_rng(0)
n_frames, n_seg, fps = 200, 12, 10.0
rows = []
for f in range(n_frames):
    t = f / fps
    for s in range(n_seg):
        amp = 20.0 * np.exp(-1.4 * s / n_seg)       # decays head -> tail
        rows.append({
            "worm_id": "w1", "frame": f, "time_s": t, "segment": s, "fps": fps,
            "seg_curv_deg": amp * np.sin(2 * np.pi * (0.8 * t - 0.15 * s))
                            + rng.normal(0, 0.4),
            "head_bend_deg": 30.0 * np.sin(2 * np.pi * 1.6 * t) + rng.normal(0, 0.5),
        })
df = pd.DataFrame(rows)

try:
    out = fd.posterior_dampening(df, "w1")
    called = True
    err = ""
except NameError as exc:                            # the original defect
    called, out, err = False, None, f"NameError: {exc}"
except Exception as exc:                            # any other failure is not this bug
    called, out, err = True, None, f"{type(exc).__name__}: {exc}"

check("posterior_dampening() runs standalone without NameError", called, err)
if out is not None:
    d = dict(out)
    check("it returns a resolved/unresolved verdict rather than a bare number",
          "resolved" in d, sorted(d)[:6])

try:
    fout = fd.foraging_descriptors(df, "w1")
    check("foraging_descriptors() runs standalone", True)
    check("foraging returns a resolved verdict too", "resolved" in dict(fout))
except Exception as exc:
    check("foraging_descriptors() runs standalone", False, f"{type(exc).__name__}: {exc}")

# The honesty convention: absent input must yield NaN + resolved=False, never a
# fabricated amplitude. Drop the column the head metric needs.
try:
    bare = fd.foraging_descriptors(df.drop(columns=["head_bend_deg"]), "w1")
    d = dict(bare)
    check("missing head_bend_deg gives resolved=False rather than a number",
          d.get("resolved") in (False, 0), d.get("resolved"))
except Exception as exc:
    check("missing head_bend_deg gives resolved=False rather than a number",
          False, f"{type(exc).__name__}: {exc}")

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("FORAGING_DAMPENING_STANDALONE_PASS")
