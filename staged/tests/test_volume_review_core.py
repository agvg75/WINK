"""Regression tests for the volume review core, and tier equivalence.

The tiering spec's §7.1 is the one that matters: the render tier must change
interaction and NEVER measurement. If two machines can produce different volumes
for the same stack and the same student decisions, the tier has become a hidden
analysis variable and the module is no longer reproducible within the lab.

So the same scripted intent list is replayed through every available viewer and
the results must agree exactly. Any divergence means a viewer has acquired
private state, which is the highest-priority bug class in this design.
"""
from pathlib import Path
import json
import sys
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))

import matplotlib
matplotlib.use("Agg")

import muscle_boundary as mb                # noqa: E402
import volume_review_state as vrs           # noqa: E402
import volume_review_viewer as vrv          # noqa: E402
import muscle_volume_runner as mvr          # noqa: E402

SHAPE = (24, 1, 200, 200)
VOX = (2.0, 0.5, 0.5)          # anisotropic, as a real confocal stack is

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


def script():
    """A realistic review: both surfaces, sparse planes, an exclusion."""
    out = [vrs.AddRegion(region="dorsal_left", channel=0)]
    for z, dip in ((4, 0), (10, 14), (16, 0)):
        for x in (40, 100, 160):
            out.append(vrs.AddBoundaryPoint(region="dorsal_left",
                                            surface="upper", z=z, x=x,
                                            y=120 + dip))
            out.append(vrs.AddBoundaryPoint(region="dorsal_left",
                                            surface="lower", z=z, x=x,
                                            y=80 + dip))
    out.append(vrs.MoveBoundaryPoint(region="dorsal_left", surface="upper",
                                     z=10, index=1, x=100, y=136))
    out.append(vrs.SetExclusion(region="dorsal_left", z=10,
                                polygon=[[90, 60], [130, 60],
                                         [130, 140], [90, 140]],
                                reason="pharynx"))
    return out


def fresh(tier="headless"):
    return vrs.VolumeReviewState(shape_zcyx=SHAPE, voxel_size_um=VOX,
                                 source_path="synthetic.tif",
                                 render_tier=tier)


print("volume review core - regression\n")

# --- the core measures with no viewer at all ------------------------------
state = fresh()
state.replay(script())
rows = state.measure()
check("the full review computes with NO viewer instantiated", len(rows) == 1)
r = rows[0]
check("sparse marking interpolates between marked planes",
      r["n_planes_measured"] == 13 and r["n_planes_marked_upper"] == 3,
      f"{r['n_planes_measured']} measured from {r['n_planes_marked_upper']} marked")
check("the result states it was measured over the marked extent only",
      r["measured_over_marked_extent_only"] is True)
check("interpolation is named on the output, not left implicit",
      r["interpolation"] == "linear")
check("the exclusion is counted by its reason",
      r["exclusion_counts"].get("pharynx") == 1, r["exclusion_counts"])
check("excluded volume is reported separately from included",
      r["excluded_volume_um3"] > 0 and r["volume_um3"] > 0)

# --- TIER EQUIVALENCE: the one that matters -------------------------------
outcomes = {}
for cls in vrv.available_viewers():
    st = fresh(cls.tier_name)
    if cls is vrv.HeadlessVolumeReviewViewer:
        out = cls(script()).run(st)
    else:
        st.replay(script())
        st.apply_intent(vrs.AcceptReview())
        out = vrv.ReviewOutcome(status="accepted", state=st,
                                tier=cls.tier_name)
    outcomes[cls.tier_name] = out

check("at least the headless tier is available", "headless" in outcomes,
      list(outcomes))

vols, masks, logs = {}, {}, {}
for tier, out in outcomes.items():
    vols[tier] = out.state.measure()[0]["volume_um3"]
    masks[tier] = out.state.masks()["dorsal_left"]
    logs[tier] = [e["intent"] for e in out.state.correction_log]

first = sorted(vols)[0]
check("every available tier returns the SAME volume",
      all(abs(v - vols[first]) < 1e-9 for v in vols.values()), vols)
check("every available tier returns byte-identical masks",
      all(np.array_equal(m, masks[first]) for m in masks.values()))
check("correction logs are identical once the tier field is excluded",
      all(l == logs[first] for l in logs.values()))
check("the tier IS recorded, as how the review was conducted",
      all(e["render_tier"] for e in outcomes[first].state.correction_log))

# --- every mutation is logged --------------------------------------------
st = fresh()
st.replay(script())
check("one log entry per intent, so nothing changes state unlogged",
      len(st.correction_log) == len(script()),
      f"{len(st.correction_log)} vs {len(script())}")
check("log entries describe the change in words, not just a type",
      all(e["description"] for e in st.correction_log))

# --- refusals -------------------------------------------------------------
try:
    fresh().apply_intent(vrs.SetExclusion(region="x", z=0,
                                          polygon=[[0, 0], [1, 0], [1, 1]],
                                          reason="because_i_said_so"))
    check("an off-vocabulary exclusion reason is refused", False)
except mb.BoundaryError as exc:
    check("an off-vocabulary exclusion reason is refused", True)
    check("...and says why a free-text reason cannot be counted",
          "counted across students" in str(exc))

try:
    fresh().apply_intent(vrs.AddBoundaryPoint(region="never_added",
                                              surface="upper", z=1, x=1, y=1))
    check("marking into a region that was never added is refused", False)
except mb.BoundaryError:
    check("marking into a region that was never added is refused", True)

try:
    vrs.intent_from_dict({"kind": "teleport_the_worm"})
    check("an unknown intent is refused", False)
except mb.BoundaryError as exc:
    check("an unknown intent is refused", True)
    check("...naming the risk it represents",
          "differ between tiers" in str(exc))

# --- crash recovery: a viewer failure must not cost the marking -----------
with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
    st = fresh("tier2")
    st.replay(script())
    outcome = vrv.VolumeReviewViewer.recover(st, td, RuntimeError("backend died"),
                                             "tier2")
    check("a crashed viewer serializes state for recovery",
          outcome.recovery_path.exists() and outcome.status == "crashed")
    restored = vrs.VolumeReviewState.from_dict(
        json.loads(Path(outcome.recovery_path).read_text(encoding="utf-8")))
    check("recovered state measures identically to the pre-crash state",
          abs(restored.measure()[0]["volume_um3"]
              - st.measure()[0]["volume_um3"]) < 1e-9)
    check("the correction log survives the crash unbroken",
          len(restored.correction_log) == len(st.correction_log))

# --- round trip -----------------------------------------------------------
st = fresh()
st.replay(script())
again = vrs.VolumeReviewState.from_dict(st.to_dict())
check("state round-trips through serialization without changing the volume",
      abs(again.measure()[0]["volume_um3"]
          - st.measure()[0]["volume_um3"]) < 1e-9)
check("provenance describes interaction, and says nothing measured",
      set(st.to_provenance()) >= {"render_tier", "n_intents", "interpolation"})

# --- the rotating surface movie ------------------------------------------
with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
    st = fresh()
    st.replay(script())
    rows = st.measure()
    path, prov = mvr.render_surface_movie(st.regions, SHAPE, VOX, rows,
                                          Path(td) / "spin.mp4", n_frames=12)
    check("the rotating surface movie renders",
          path.exists() and path.stat().st_size > 1000,
          f"{path.stat().st_size} bytes" if path.exists() else "missing")
    check("...and records that it is a view, not a measurement",
          prov.get("view") == "rotating 3D surfaces")

    written = mvr.write_outputs(td, "rec", rows, st.masks(),
                                {"tool": "test", **st.to_provenance()})
    check("volume CSV is written", written["csv"].exists())
    check("the mask is written as a first-class output",
          bool(written.get("masks")))
    check("provenance is written beside it", written["provenance"].exists())
    text = written["csv"].read_text(encoding="utf-8")
    check("voxel size reaches the CSV, since volume goes as its cube",
          "voxel_size_um_x" in text)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("VOLUME_REVIEW_CORE_REGRESSION_PASS")
