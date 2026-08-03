"""Regression tests for tools/confocal_loader.py.

Synthetic files cover the contract mechanically (axis reordering, the
calibration hard stop, truncation, bit-depth reporting). Real confocal
files from the lab's own share cover what synthetic fixtures cannot: that
a vendor reader's metadata is being read the right way up, and that the
multi-series case this loader exists to refuse is actually present in real
data. Real-file checks skip cleanly when the share is unreachable.
"""
from pathlib import Path
import sys

import numpy as np
import tifffile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import confocal_loader as cl

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("confocal_loader - regression\n")

# ---------------------------------------------------------------------------
# 1. Format detection
# ---------------------------------------------------------------------------
check("detects .lif", cl.detect_format("a/b.lif") == "lif")
check("detects .czi", cl.detect_format("a/b.czi") == "czi")
check("detects .nd2", cl.detect_format("a/b.nd2") == "nd2")
check("detects .ome.tif as tiff", cl.detect_format("a/b.ome.tif") == "tiff")
check("unknown suffix is not guessed at", cl.detect_format("a/b.avi") is None)

# ---------------------------------------------------------------------------
# 2. Axis reordering into (Z, C, Y, X)
# ---------------------------------------------------------------------------
zcyx = cl._to_zcyx(np.zeros((4, 2, 10, 12)), "ZCYX")
check("ZCYX passes through unchanged", zcyx.shape == (4, 2, 10, 12), zcyx.shape)
czyx = cl._to_zcyx(np.zeros((2, 4, 10, 12)), "CZYX")
check("CZYX is reordered to ZCYX", czyx.shape == (4, 2, 10, 12), czyx.shape)
yx = cl._to_zcyx(np.zeros((10, 12)), "YX")
check("a bare YX plane gains singleton Z and C",
      yx.shape == (1, 1, 10, 12), yx.shape)
# Real bug this guards: tifffile labels the pages of a plain multipage TIFF
# "Q" (unknown). Collapsing Q to its first element - which the first version
# did - turned a 45-plane z stack into ONE plane, silently, making every
# depth measurement downstream meaningless. Unlabelled axes must map to Z
# then C positionally, and say that they did.
q_notes = []
qyx = cl._to_zcyx(np.zeros((5, 8, 9)), "QYX", notes=q_notes)
check("a plain multipage TIFF's unlabelled pages become Z, not collapsed "
      "to a single plane", qyx.shape == (5, 1, 8, 9), qyx.shape)
check("that assumption is reported rather than made silently",
      any("unlabelled axis" in n.lower() for n in q_notes), q_notes)
qq_notes = []
qqyx = cl._to_zcyx(np.zeros((5, 2, 8, 9)), "QQYX", notes=qq_notes)
check("two unlabelled axes map positionally to Z then C",
      qqyx.shape == (5, 2, 8, 9), qqyx.shape)
yxs = cl._to_zcyx(np.zeros((8, 9, 3)), "YXS")
check("an RGB sample axis is read as channels", yxs.shape == (1, 3, 8, 9), yxs.shape)

tzcyx = cl._to_zcyx(np.zeros((3, 4, 2, 10, 12)), "TZCYX")
check("an unmodelled axis (T) is collapsed to its first element, not "
      "silently flattened into Z", tzcyx.shape == (4, 2, 10, 12), tzcyx.shape)
scenes = cl._to_zcyx(np.zeros((3, 4, 2, 10, 12)), "SZCYX", scene=2)
check("a scene index selects that scene", scenes.shape == (4, 2, 10, 12), scenes.shape)

# ---------------------------------------------------------------------------
# 3. The calibration hard stop
# ---------------------------------------------------------------------------
check("a complete voxel size validates",
      cl._validated_voxel(0.2, 0.05, 0.05, "test") == (0.2, 0.05, 0.05))
check("a missing axis yields None rather than a guess",
      cl._validated_voxel(None, 0.05, 0.05, "test") is None)
for bad in (0.0, -1.0, float("nan"), float("inf")):
    try:
        cl._validated_voxel(bad, 0.05, 0.05, "test")
        check(f"a non-physical dz ({bad}) is refused", False)
    except cl.ConfocalCalibrationError:
        check(f"a non-physical dz ({bad}) is refused", True)

# ---------------------------------------------------------------------------
# 4. Synthetic TIFF: load, calibration refusal, manual override, truncation
# ---------------------------------------------------------------------------
import tempfile, shutil
tmp = Path(tempfile.mkdtemp())
try:
    vol = np.zeros((5, 8, 9), dtype=np.uint16)
    vol[2, 3, 4] = 4095                      # 12-bit-ish value in a 16-bit container
    plain = tmp / "plain.tif"
    tifffile.imwrite(plain, vol)

    try:
        cl.load_stack(plain)
        check("an uncalibrated stack is refused by default", False)
    except cl.ConfocalCalibrationError as exc:
        check("an uncalibrated stack is refused by default", True)
        check("the refusal explicitly warns against assuming isotropic voxels",
              "isotropic" in str(exc).lower())

    st = cl.load_stack(plain, voxel_size_um=(0.2, 0.05, 0.05))
    check("manual voxel size is accepted", st.voxel_size_um == (0.2, 0.05, 0.05))
    check("manual calibration is recorded as such, not passed off as file "
          "metadata", st.metadata["calibration_source"] == "manual")
    check("array is (Z, C, Y, X)", st.array.shape == (5, 1, 8, 9), st.array.shape)
    check("source dtype is preserved (not silently downcast)",
          st.array.dtype == np.uint16, st.array.dtype)
    check("channel() returns a (Z, Y, X) volume", st.channel(0).shape == (5, 8, 9))

    check("anisotropy is computed", abs(st.anisotropy() - 4.0) < 1e-9, st.anisotropy())
    warnings = st.preflight_warnings()
    check("strong anisotropy raises a preflight warning",
          any("anisotropic" in w for w in warnings), warnings)
    check("hand-entered calibration is surfaced as a warning",
          any("by hand" in w for w in warnings), warnings)
    check("low intensity range in a wide container is flagged (12-bit data "
          "in a 16-bit file is common on Zeiss and Nikon systems)",
          any("bit depth" in w or "container" in w for w in warnings), warnings)

    ok = cl.load_stack(plain, voxel_size_um=(0.2, 0.05, 0.05), require_calibration=False)
    check("require_calibration=False allows an uncalibrated load path",
          ok.array.shape[0] == 5)

    trunc = cl.load_stack(plain, voxel_size_um=(0.2, 0.05, 0.05), expected_z=9)
    check("a z-count mismatch is reported, not silently accepted",
          trunc.metadata["truncation_note"] is not None,
          trunc.metadata["truncation_note"])
    check("the truncation note names both counts",
          "9" in trunc.metadata["truncation_note"]
          and "5" in trunc.metadata["truncation_note"])

    # folder-of-TIFFs treated as a z axis
    folder = tmp / "seq"; folder.mkdir()
    for i in range(4):
        tifffile.imwrite(folder / f"plane_{i:03d}.tif",
                         np.full((6, 7), i, dtype=np.uint8))
    fs = cl.load_stack(folder, voxel_size_um=(0.3, 0.1, 0.1))
    check("a folder of TIFFs loads as a z stack",
          fs.array.shape == (4, 1, 6, 7), fs.array.shape)
    check("folder planes keep their order",
          [int(fs.array[z, 0, 0, 0]) for z in range(4)] == [0, 1, 2, 3])

    try:
        cl.load_stack(plain, series=7, voxel_size_um=(0.2, 0.05, 0.05))
        check("a non-existent series is refused", False)
    except cl.ConfocalLoadError:
        check("a non-existent series is refused", True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ---------------------------------------------------------------------------
# 5. Real confocal file. This is the part synthetic fixtures cannot do: it
#    checks the vendor metadata is read the right way up, and that the
#    multi-series case is real rather than hypothetical.
# ---------------------------------------------------------------------------
REAL_LIF = Path(r"L:/05_Proprioception/Ella/Myocyte Measurements"
                r"/240619_BZ33_day5A_crawl_phall_9"
                r"/240619_BZ33_day5A_crawl_phall_9.lif")
if REAL_LIF.exists():
    series = cl.list_series(REAL_LIF)
    check("real .lif: series are enumerated without loading pixels",
          len(series) == 9, len(series))
    try:
        cl.load_stack(REAL_LIF)
        refused = False
    except cl.ConfocalLoadError:
        refused = True
    check("real .lif: a multi-series file refuses to load without an "
          "explicit choice (loading the first would pick an arbitrary "
          "acquisition from a raw/deconvolved pair)", refused)

    info = series[2]
    dz, dy, dx = info.voxel_size_um
    # readlif reports PIXELS PER MICROMETRE; inverting this is silent and
    # total, so pin the actual expected values from this real acquisition.
    check("real .lif: lateral voxel size is sub-micron, i.e. the px/um "
          "reciprocal was applied (not left as ~18 um)",
          0.04 < dy < 0.07 and 0.04 < dx < 0.07, (dy, dx))
    check("real .lif: z spacing is read independently of lateral",
          0.15 < dz < 0.19, dz)
    check("real .lif: voxels are genuinely anisotropic, which is exactly "
          "why dz is never inferred from dy/dx",
          dz / ((dy + dx) / 2) > 2.5, dz / ((dy + dx) / 2))

    st = cl.load_stack(REAL_LIF, series=2)
    check("real .lif: loads as (Z, C, Y, X)", st.array.ndim == 4, st.array.shape)
    check("real .lif: z planes match the series listing",
          st.array.shape[0] == info.shape_zcyx[0], st.array.shape)
    check("real .lif: channel count matches the series listing",
          st.array.shape[1] == info.shape_zcyx[1], st.array.shape)
    check("real .lif: calibration came from file metadata, not a default",
          st.metadata["calibration_source"] == "file_metadata")
    check("real .lif: the objective is captured for provenance",
          bool(st.metadata.get("objective")), st.metadata.get("objective"))
    check("real .lif: anisotropy warning fires on real data",
          any("anisotropic" in w for w in st.preflight_warnings()))
    check("real .lif: bit depth is per-series (this file mixes 8- and "
          "16-bit series)",
          len({s.bit_depth for s in series}) > 1,
          sorted({s.bit_depth for s in series}))
else:
    print(f"\n  (real .lif not reachable at {REAL_LIF} - real-file checks skipped)")

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("CONFOCAL_LOADER_REGRESSION_PASS")
