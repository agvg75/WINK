"""Characterization pin for the four functions moving out of magnetotaxis.

These are not magnetic and never were - time off food, initial state, segment
covariates, and the toward/away regime split are facts about a population of
worms migrating on a plate. They are moving into a shared layer so chemotaxis
and thermotaxis can use them, which today they cannot.

WHY A PIN AND NOT JUST THE UNIT TESTS. The existing tests assert on a handful
of fields and all pass; a relocation could keep every one of them true and
still change a number nobody is looking at. This serializes the COMPLETE
output of each function on richer input and compares it byte for byte. The
magnetotaxis results are the ones Andres has published against, so
"probably equivalent" is not good enough.

Regenerate deliberately with --write after an INTENDED behaviour change, never
to make a failure go away. A diff here means the refactor changed something.
"""
from pathlib import Path
import json
import math
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"),
                str(ROOT / "tools" / "orientation_assays"),
                str(ROOT / "tools" / "population_orientation")]

GOLDEN = Path(__file__).parent / "golden" / "plate_assay_pin.json"
WRITE = "--write" in sys.argv

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


# --------------------------------------------------------------------------- #
# Deterministic input. No RNG - a pin whose input drifts is not a pin.
# --------------------------------------------------------------------------- #
def make_tracks():
    """Three plates, four worms each, 40 samples - crawling outward at
    different rates and angles, with one stationary worm per plate so the
    dwell and initial-state branches are exercised."""
    rows = []
    for p in range(3):
        for w in range(4):
            speed = 0.0 if w == 3 else 0.05 + 0.03 * w
            theta = math.radians(20 * w + 45 * p)
            for t in range(40):
                time_s = t * 2.0
                r = speed * time_s
                rows.append({
                    "plate_id": f"plate{p}",
                    "worm_id": f"w{w}",
                    "time_s": time_s,
                    "x_mm": round(5.0 + r * math.cos(theta), 6),
                    "y_mm": round(5.0 + r * math.sin(theta), 6),
                    "heading_deg": round(math.degrees(theta), 6),
                    "spine_quality": round(0.6 + 0.1 * ((t + w) % 4), 6),
                })
    return rows


def make_segments(tracks):
    out = []
    for row in tracks:
        dx, dy = row["x_mm"] - 5.0, row["y_mm"] - 5.0
        radial = math.degrees(math.atan2(dy, dx))
        out.append({**row,
                    "angle_to_vector_deg": round((radial + 360) % 360 - 180, 6),
                    "radial_heading_deg": round(radial, 6),
                    "signed_track_curvature_deg_s": round(
                        math.sin(row["time_s"] / 7.0) * 3.0, 6)})
    return out


def sort_key(row):
    return (str(row.get("plate_id")), str(row.get("worm_id")),
            float(row.get("time_s", 0)))


def capture():
    """Everything the four functions produce, in a stable order."""
    import magnetotaxis as mt

    tracks = make_tracks()
    segments = make_segments(tracks)
    departures = [{"worm_id": f"w{w}", "committed_departure_s": 10.0 + 4 * w}
                  for w in range(4)]

    snap = {}

    # 1. time off food - every branch, including the refusals
    offsets = {}
    for label, kwargs in (
        ("elapsed", {"elapsed_s": 300}),
        ("elapsed_zero", {"elapsed_s": 0}),
        ("elapsed_string", {"elapsed_s": "450"}),
        ("clock_hm", {"food_removal_clock": "09:55",
                      "assay_start_clock": "10:00"}),
        ("clock_hms", {"food_removal_clock": "09:55:30",
                       "assay_start_clock": "10:00:00"}),
        ("clock_midnight_wrap", {"food_removal_clock": "23:50",
                                 "assay_start_clock": "00:05"}),
        ("nothing_given", {}),
    ):
        try:
            offsets[label] = mt.resolve_time_off_op50_offset(**kwargs)
        except Exception as exc:
            offsets[label] = f"{type(exc).__name__}: {exc}"
    for label, kwargs in (
        ("negative_elapsed", {"elapsed_s": -1}),
        ("bad_clock_format", {"food_removal_clock": "9.55",
                              "assay_start_clock": "10:00"}),
    ):
        try:
            offsets[label] = mt.resolve_time_off_op50_offset(**kwargs)
        except Exception as exc:
            offsets[label] = f"{type(exc).__name__}: {exc}"
    snap["time_off_op50"] = offsets

    # 2. initial states
    states = mt._initial_states(tracks, opening_s=30.0)
    snap["initial_states"] = {f"{k[0]}|{k[1]}": v
                              for k, v in sorted(states.items())}

    # 3. segment covariates
    rows, events = mt.build_segment_covariates(
        tracks, segments, departures, 300.0,
        per_worm_food_offsets_s={"w1": 420.0},
        initial_state_window_s=30.0)
    snap["covariate_rows"] = sorted(rows, key=sort_key)
    snap["covariate_events"] = sorted(
        events, key=lambda e: json.dumps(e, sort_keys=True, default=str))

    # 4. regime comparison - a passing plate and a thin one
    snap["regime_default"] = mt.regime_comparison(segments, (5.0, 5.0))
    snap["regime_min1"] = mt.regime_comparison(
        segments, (5.0, 5.0), min_worms_per_regime=1)
    snap["regime_thin"] = mt.regime_comparison(
        segments, (5.0, 5.0), min_worms_per_regime=99)
    return snap


print("plate assay - characterization pin\n")
snap = capture()
text = json.dumps(snap, indent=2, sort_keys=True, default=str)

if WRITE or not GOLDEN.exists():
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(text, encoding="utf-8")
    print(f"  WROTE {GOLDEN}  ({len(text)} chars)")
    print("  Baseline recorded. Re-run without --write to compare.")
    raise SystemExit(0)

want = GOLDEN.read_text(encoding="utf-8-sig")
check("the pinned output is unchanged", text == want,
      "" if text == want else "see the first differing key below")

if text != want:
    a, b = json.loads(want), json.loads(text)
    for key in sorted(set(a) | set(b)):
        if a.get(key) != b.get(key):
            print(f"\n  FIRST DIFFERENCE IN: {key}")
            sa = json.dumps(a.get(key), indent=2, sort_keys=True,
                            default=str).splitlines()
            sb = json.dumps(b.get(key), indent=2, sort_keys=True,
                            default=str).splitlines()
            for i, (la, lb) in enumerate(zip(sa, sb)):
                if la != lb:
                    print(f"    line {i}\n      was: {la.strip()}"
                          f"\n      now: {lb.strip()}")
                    break
            break

# The pin is only meaningful if it actually covers the functions being moved.
check("the pin covers time off food", bool(snap["time_off_op50"]))
check("...including its refusals",
      any("Error" in str(v) for v in snap["time_off_op50"].values()),
      "a refusal that stops refusing is a silent behaviour change")
check("the pin covers initial states", len(snap["initial_states"]) == 12)
check("the pin covers segment covariates", len(snap["covariate_rows"]) > 100,
      f"{len(snap['covariate_rows'])} rows")
check("the pin covers the regime split",
      bool(snap["regime_default"].get("per_plate")))
check("...including the thin-plate refusal",
      all(p.get("status") == "withheld"
          for p in snap["regime_thin"]["per_plate"].values()))

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("PLATE_ASSAY_PIN_PASS")
