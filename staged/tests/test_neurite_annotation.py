"""Regression tests for tools/neurite_annotation.py and app/check_station.py.

The point of the split is that annotation and tracing can happen on
different machines at different times, so the tests exercise exactly that:
write a sidecar, then trace from it with no viewer involved, and prove a
sidecar cannot be silently applied to the wrong stack.
"""
from pathlib import Path
import shutil
import sys
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
import neurite_annotation as na
import confocal_loader as cl
import check_station as cs

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


def draw_tube(vol, points, radius=2, value=255.0):
    pts = np.asarray(points, float)
    for a, b in zip(pts[:-1], pts[1:]):
        for t in np.linspace(0, 1, 60):
            c = a + (b - a) * t
            zz, yy, xx = np.ogrid[:vol.shape[0], :vol.shape[1], :vol.shape[2]]
            vol[((zz - c[0]) ** 2 + (yy - c[1]) ** 2 + (xx - c[2]) ** 2)
                <= radius ** 2] = value
    return vol


print("neurite_annotation + check_station - regression\n")
tmp = Path(tempfile.mkdtemp())
try:
    VOX = (0.4, 0.1, 0.1)
    vol = np.zeros((16, 40, 60), dtype=np.float32)
    draw_tube(vol, [(8, 20, 5), (8, 20, 54)])
    stack = cl.ConfocalStack(
        array=vol[:, None, :, :],
        metadata={"voxel_size_um": VOX, "source_path": str(tmp / "demo.lif"),
                  "series_index": 2, "series_name": "demo series",
                  "calibration_source": "file_metadata"})

    # -----------------------------------------------------------------------
    # 1. Annotation records only marks and provenance
    # -----------------------------------------------------------------------
    ann = na.NeuriteAnnotation(
        neurite_id="n1", points_zyx=[(8, 20, 5), (8, 20, 30), (8, 20, 54)],
        label="PVD anterior", annotator="student_a", channel=0)
    check("endpoints and anchors are distinguished",
          ann.anchors_zyx == [[8, 20, 30]], ann.anchors_zyx)
    check("an annotation timestamps itself", bool(ann.annotated_utc))
    try:
        na.NeuriteAnnotation(neurite_id="bad", points_zyx=[(1, 2, 3)])
        check("a single-point annotation is refused", False)
    except na.AnnotationError:
        check("a single-point annotation is refused", True)

    identity = na.stack_identity(stack.metadata["source_path"], 2,
                                 stack.array.shape, VOX)
    path = na.sidecar_path(stack.metadata["source_path"], 2)
    check("the sidecar sits beside the stack and names its series",
          path.name.endswith("_series2.neurites.json"), path.name)

    na.save_annotations(path, identity, [ann], station="STATION-A")
    text = path.read_text(encoding="utf-8")
    check("the sidecar is small and human-readable JSON", len(text) < 4000, len(text))
    check("the sidecar records which station made it", "STATION-A" in text)
    check("the sidecar contains no pixel data",
          "array" not in text and str(int(vol.max())) not in text.split('"points_zyx"')[0])

    loaded, payload = na.load_annotations(path, identity)
    check("annotations round-trip", len(loaded) == 1
          and loaded[0].points_zyx == ann.points_zyx)
    check("the annotator is preserved for provenance",
          loaded[0].annotator == "student_a")

    # -----------------------------------------------------------------------
    # 2. A sidecar cannot be silently applied to a different stack
    # -----------------------------------------------------------------------
    other = na.stack_identity(stack.metadata["source_path"], 3,
                              stack.array.shape, VOX)      # different series
    try:
        na.load_annotations(path, other)
        check("a sidecar from another series is refused", False)
    except na.AnnotationError as exc:
        check("a sidecar from another series is refused", True)
        check("the refusal explains it would produce a fictional path",
              "fictional" in str(exc).lower(), str(exc)[-60:])

    recal = na.stack_identity(stack.metadata["source_path"], 2,
                              stack.array.shape, (0.5, 0.1, 0.1))
    try:
        na.load_annotations(path, recal)
        check("a sidecar made before a recalibration is refused", False)
    except na.AnnotationError:
        check("a sidecar made before a recalibration is refused", True)
    _, warned = na.load_annotations(path, other, strict=False)
    check("strict=False downgrades the mismatch to a recorded warning "
          "rather than hiding it", "identity_warning" in warned)

    # -----------------------------------------------------------------------
    # 3. Tracing from the sidecar is headless - no viewer, no Qt
    # -----------------------------------------------------------------------
    check("napari is NOT needed anywhere in this workflow, and is not "
          "installed on this station", not cs._have("napari"))
    traced = na.trace_annotations(stack, loaded, radius_um=0.2)
    check("tracing from a sidecar produces one result per annotation",
          len(traced) == 1, len(traced))
    r = traced[0]
    check("the trace has a physical length", r["length_um"] > 0, r["length_um"])
    expected = (54 - 5) * VOX[2]
    check("length uses the real anisotropic voxel size",
          abs(r["length_um"] - expected) < expected * 0.2,
          (r["length_um"], expected))
    check("the raw automatic path is reported alongside the anchored one",
          "raw_length_um" in r and r["raw_length_um"] > 0)
    check("the parameters that produced the number travel with it",
          r["sigma_um"] and r["radius_um_expected"] == 0.2
          and r["voxel_size_um"] == list(VOX))
    check("radius and volume are measured", r["volume_um3"] > 0, r["volume_um3"])
    check("the radius estimate declares itself coarse",
          "coarse" in r["radius_note"])

    rows = na.results_to_rows(traced, stack.metadata)
    check("CSV rows drop the path arrays but keep the identity",
          "path" not in rows[0] and rows[0]["series_index"] == 2)

    uncal = cl.ConfocalStack(array=vol[:, None, :, :], metadata={})
    try:
        na.trace_annotations(uncal, loaded, radius_um=0.2)
        check("tracing an uncalibrated stack is refused", False)
    except na.AnnotationError as exc:
        check("tracing an uncalibrated stack is refused", True)
        check("because no traced length would be meaningful",
              "meaningful" in str(exc).lower())

    # -----------------------------------------------------------------------
    # 4. Station check - one tier, because annotation IS the base install
    # -----------------------------------------------------------------------
    report = cs.check_station()
    check("the station check names the machine", bool(report["station"]))
    check("it reports base install completeness", report["base_ok"] is True,
          report["base_missing"])
    check("it lists what the station can actually do",
          any("Trace neurites" in c for c in report["capabilities"]))
    check("a complete base install can MARK neurites here, because the "
          "annotation viewer is Tkinter and ships with everything else",
          any("Mark neurites" in c for c in report["capabilities"]),
          report["capabilities"])
    check("nothing tells this station it cannot annotate",
          not any("CANNOT" in c for c in report["capabilities"]),
          report["capabilities"])
    check("--json shape is collectable across a fleet",
          set(["station", "base_ok", "ram_gb", "capabilities"]) <= set(report))

    # The old opt-in Napari tier is gone. These names must stay gone: a check
    # that reports a capability nothing implements sends people to machines
    # that do not exist.
    for dead in ("VIEWER_PACKAGES", "VIEWER_STATIONS", "require_viewer",
                 "viewer_requirement_message"):
        check(f"the stale viewer tier is gone, not merely unused ({dead})",
              not hasattr(cs, dead))
    check("and no viewer keys survive in the report",
          not any("viewer" in k for k in report), list(report))
    check("hardware is reported for what it actually limits - holding a big "
          "stack in memory, not hosting a 3D renderer",
          "large_stack_hardware_ok" in report)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("NEURITE_ANNOTATION_REGRESSION_PASS")
