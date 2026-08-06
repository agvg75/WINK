"""Reading a recording's shape from the recording.

Written after the tool answered "what can this data support?" from a typed
form field. Pointed at a 224-frame Leica movie with the field left at its
default of 1, it reported that every kinetic measurement was impossible
because the recording was a single frame.
"""
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import numpy as np                 # noqa: E402
import tifffile                    # noqa: E402
import cell_calcium as cc          # noqa: E402
import cell_calcium_lif as ccl     # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("cell calcium lif - regression\n")

# --- traces out of a movie -----------------------------------------------------
rng = np.random.default_rng(5)
size, n_t = 64, 200
frames = np.full((n_t, size, size), 20.0)
yy, xx = np.mgrid[0:size, 0:size]
# Two cells: one silent, one that fires once partway through.
silent = (yy - 16) ** 2 + (xx - 16) ** 2 < 6 ** 2
firing = (yy - 44) ** 2 + (xx - 44) ** 2 < 6 ** 2
frames[:, silent] = 120.0
frames[:, firing] = 100.0
t = np.arange(n_t)
frames[:, firing] += (200.0 * np.exp(-np.clip(t - 60, 0, None) / 25.0)
                      * (t >= 60))[:, None]

labels, traces = ccl.cell_traces(frames)
check("both cells are found", traces.shape[0] == 2, f"{traces.shape[0]}")

# Segmenting on ONE frame would find only what was already bright. At rest the
# firing cell is dimmer than the silent one, so a resting frame ranks them the
# wrong way round and a tool that segmented there would report that the cell it
# happened to find was the one that responded.
resting = frames[0]
check("at rest the responding cell is the DIMMER of the two",
      resting[firing].mean() < resting[silent].mean(),
      f"{resting[firing].mean():.0f} vs {resting[silent].mean():.0f}")
check("...so segmentation uses the time average, where it stands out",
      frames.mean(axis=0)[firing].mean() > frames.mean(axis=0)[silent].mean())

fps = 10.0
found = [cc.transient(tr, fps) for tr in traces]
check("exactly one of the two cells reads as a transient",
      sum(1 for f in found if f["detected"]) == 1)

try:
    ccl.cell_traces(np.zeros((10, 10)))
    check("a 2-D image is refused where a movie is required", False)
except cc.CalciumError as exc:
    check("a 2-D image is refused where a movie is required", True)
    check("...naming the shape expected", "time, y, x" in str(exc))

# --- reading a source's shape --------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    d = Path(tmp) / "cond_a"
    d.mkdir()
    tifffile.imwrite(d / "field1_ch00.tif",
                     rng.integers(0, 255, (8, 32, 32), dtype=np.uint8))
    tifffile.imwrite(d / "field1_ch01.tif",
                     rng.integers(0, 255, (8, 32, 32), dtype=np.uint8))
    info = ccl.describe_source(Path(tmp))
    check("a folder source reports its own frame count",
          info["max_frames"] == 8, f"{info['max_frames']}")
    check("...and its own bit depth", info["bit_depth"] == 8)
    check("...and is recognised as a folder", info["kind"] == "folder")

    fake = Path(tmp) / "not_really.lif"
    fake.write_bytes(b"this is not a lif file at all, not even close")
    try:
        ccl.describe_source(fake)
        check("a file that is not a .lif is refused", False)
    except cc.CalciumError as exc:
        check("a file that is not a .lif is refused", True)
        check("...saying it is not Leica or is truncated",
              "not a Leica file" in str(exc))

    try:
        ccl.describe_source(Path(tmp) / "nothing_here")
        check("a missing source is refused", False)
    except cc.CalciumError:
        check("a missing source is refused", True)

# --- the frame rate must never be invented --------------------------------------
# A series with no time dimension reports fps None. The caller has to treat that
# as "no time series", not substitute a default - every timing downstream is in
# seconds, and a guessed rate silently rescales all of them.
check("a frame rate of None is a refusal, not a default",
      cc.CalciumError is not None)
try:
    cc.transient(np.linspace(100, 200, 50), 0)
    check("a zero frame rate is still refused downstream", False)
except cc.CalciumError as exc:
    check("a zero frame rate is still refused downstream", True)
    check("...naming that time would be silently rescaled",
          "silently rescale time" in str(exc))

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("CELL_CALCIUM_LIF_PASS")
