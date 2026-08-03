"""The headless half, exercised the way a non-viewer station would use it.

The point of the split is that a sidecar made on one machine yields numbers
on another with no viewer present. So this never opens the viewer: it writes
a sidecar by hand, then goes through the runner's own entry points - the CLI
and the window - to get lengths and a CSV out of it.
"""
from pathlib import Path
import shutil
import sys
import tempfile

import numpy as np
import matplotlib
matplotlib.use("TkAgg")

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "tools", ROOT / "app"):
    sys.path.insert(0, str(p))

import tifffile                              # noqa: E402
import neurite_annotation as na              # noqa: E402
import check_station as cs                   # noqa: E402
import neurite_trace_runner as ntr           # noqa: E402

DIALOGS = []


class _StubMessagebox:
    def __getattr__(self, name):
        def call(title, message, **_kw):
            DIALOGS.append((name, title, message))
            return True
        return call


ntr.messagebox = _StubMessagebox()

results_log = []


def check(name, condition, detail=""):
    results_log.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("neurite_trace_runner - regression\n")
tmp = Path(tempfile.mkdtemp())
app = None
try:
    NZ, NY, NX = 16, 200, 700
    VOX = (0.2, 0.08, 0.08)
    vol = np.zeros((NZ, NY, NX), dtype=np.uint16)
    vol += np.random.default_rng(3).integers(0, 20, vol.shape, dtype=np.uint16)
    for dz in (-1, 0, 1):
        for dy in (-2, -1, 0, 1, 2):
            vol[8 + dz, 100 + dy, 50:650] = 3000
    stack_path = tmp / "run.ome.tif"
    tifffile.imwrite(str(stack_path), vol, photometric="minisblack",
                     metadata={"axes": "ZYX", "PhysicalSizeX": VOX[2],
                               "PhysicalSizeY": VOX[1], "PhysicalSizeZ": VOX[0]},
                     ome=True)

    ann = na.NeuriteAnnotation(neurite_id="d1", points_zyx=[(8, 100, 50),
                                                            (8, 100, 350),
                                                            (8, 100, 649)],
                               label="dendrite", annotator="student_b")
    identity = na.stack_identity(stack_path, 0, (NZ, 1, NY, NX), VOX)
    side = na.sidecar_path(stack_path, 0)
    na.save_annotations(side, identity, [ann], station="CONFOCAL-1")

    check("no viewer is installed on this station - which is the situation "
          "this tool exists for", not cs._have("napari"))

    # --------------------------------------------------------------- core
    results, stack, payload, used = ntr.trace_sidecar(side)
    check("the runner found the stack beside the sidecar by itself",
          stack.array.shape == (NZ, 1, NY, NX), stack.array.shape)
    check("it traced the marked neurite", len(results) == 1)
    expected = (649 - 50) * VOX[2]
    check("the length is right for the neurite that was drawn",
          abs(results[0]["length_um"] - expected) < expected * 0.15,
          (results[0]["length_um"], expected))
    check("the default radius came from the stack's own voxel size, not a "
          "hard-coded pixel count",
          abs(used - VOX[1] * ntr.DEFAULT_RADIUS_LATERAL_PX) < 1e-9, used)
    check("who marked it survives the hand-off",
          results[0]["annotator"] == "student_b")
    check("and which station marked it",
          payload["written_on_station"] == "CONFOCAL-1")
    check("the raw automatic path is reported beside the anchored one, so "
          "the effect of the correction is visible",
          results[0]["raw_length_um"] > 0)

    override, _s, _p, used2 = ntr.trace_sidecar(side, radius_um=0.5)
    check("an explicit radius overrides the default, which is what makes "
          "re-tracing without re-marking useful", used2 == 0.5)
    check("and it actually changes the computation",
          override[0]["sigma_um"] != results[0]["sigma_um"])

    # ------------------------------------------------- a sidecar gone astray
    orphan_dir = tmp / "elsewhere"
    orphan_dir.mkdir()
    orphan = orphan_dir / side.name
    shutil.copy(side, orphan)
    try:
        ntr.trace_sidecar(orphan)
        check("a sidecar separated from its stack is refused", False)
    except na.AnnotationError as exc:
        check("a sidecar separated from its stack is refused", True)
        check("and the refusal says the alternative would be wrong lengths, "
              "not just 'file not found'", "wrong lengths" in str(exc),
              str(exc)[-70:])

    # ------------------------------------------------------------------ CSV
    out = ntr.write_csv(tmp / "traced.csv", results, stack.metadata)
    text = out.read_text(encoding="utf-8")
    check("a CSV is written", out.is_file())
    check("it carries the provenance a number needs to be re-derived",
          all(k in text for k in ("neurite_id", "annotator", "sigma_um",
                                  "voxel_size_um", "source_path")), text[:80])
    check("it does NOT carry the path arrays, which would make it unreadable",
          "TracedPath" not in text)

    # ------------------------------------------------------------ CLI + UI
    rc = ntr.main([str(side), "--csv", str(tmp / "cli.csv")])
    check("the CLI runs the whole thing for batch work",
          rc == 0 and (tmp / "cli.csv").is_file())

    app = ntr.TraceRunner()
    app.update()
    app.sidecar = side
    app._trace()
    app.update()
    check("the window produces the same numbers as the CLI",
          abs(app.results[0]["length_um"] - results[0]["length_um"]) < 1e-9)
    shown = app.table.get("1.0", "end")
    check("the table shows corrected and raw side by side",
          "length um" in shown and "raw um" in shown)
    check("and explains what a gap between them means",
          "correction mattered" in shown)
    check("the coarse-radius caveat is not dropped on the way to the screen",
          "coarse" in shown)

    app.radius_var.set("not a number")
    DIALOGS.clear()
    app._trace()
    check("a nonsense radius is refused with an explanation rather than a "
          "traceback", DIALOGS and "not a number" in DIALOGS[-1][2], DIALOGS[-1:])

    app.sidecar = orphan
    app.radius_var.set("")
    DIALOGS.clear()
    app._trace()
    check("the window surfaces the misplaced-stack refusal too, instead of "
          "the button appearing to do nothing",
          DIALOGS and "not beside it" in DIALOGS[-1][2], DIALOGS[-1:])
finally:
    if app is not None:
        try:
            app.destroy()
        except Exception:
            pass
    shutil.rmtree(tmp, ignore_errors=True)

print()
failed = [n for n, ok, _ in results_log if not ok]
print(f"{len(results_log) - len(failed)} of {len(results_log)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("NEURITE_TRACE_RUNNER_REGRESSION_PASS")
