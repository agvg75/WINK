"""Golden records: what the pipeline currently produces, frozen and diffed.

    py tools\\conformance\\golden.py --baseline     capture current outputs
    py tools\\conformance\\golden.py --check        diff against the baseline

WHAT THIS CATCHES THAT NOTHING ELSE DOES. The conformance scanner reads code
and the repro corpus reproduces known incidents. Neither notices a change
that is merely DIFFERENT - a refactor that shifts a threshold by one, a
library upgrade that rounds the other way, a fix whose blast radius was
larger than intended. Golden records catch drift by having something to
differ from.

ZERO TOLERANCE BY DEFAULT, and this is the discipline rather than a setting.
Any changed measured value blocks, regardless of direction: a number that
moved for a reason nobody can state is exactly as alarming as one that moved
in the wrong direction. Acceptance requires a recorded reason and a
re-baseline IN THE SAME COMMIT, so the new expectation and the justification
for it are never separated.

ANY RULE NEEDING NUMERIC TOLERANCE MUST STATE AND DERIVE IT. No underived
epsilons - a tolerance chosen to make a test pass is a threshold tuned to
hide a defect, which is the acceptance-band failure wearing different
clothes.

Non-measured changes - timings, log wording, file ordering - report only.
They are worth seeing and are not worth blocking a release for.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGED = HERE.parents[1]
GOLDEN_DIR = HERE / "golden"
CORPUS = Path(r"L:\10_AGVG LAB\Lab Tools\repro_corpus")

# Fields whose change BLOCKS. Everything else reports.
MEASURED_KEYS = ("n_frames", "n_detections", "median_area_px", "area_p10",
                 "area_p90", "n_blobs_median", "mask_hash", "verdict",
                 "fps_lower_bound", "duration_s", "admitted_by_band")
REPORT_ONLY_KEYS = ("elapsed_s", "note", "log", "written_utc")

# DERIVED TOLERANCES ONLY. An entry here must carry `derivation`; anything
# without one is rejected at load, so a bare epsilon cannot be slipped in.
TOLERANCES = {
    # (none yet - zero tolerance everywhere until something needs otherwise
    # and can explain why)
}


def check_tolerances():
    for key, spec in TOLERANCES.items():
        if not spec.get("derivation"):
            raise SystemExit(
                f"Tolerance for {key!r} has no derivation. A tolerance "
                f"without one is an underived epsilon, which is the thing "
                f"this file exists to prevent. State where the number comes "
                f"from or remove it.")


def digest(value):
    return hashlib.blake2b(json.dumps(value, sort_keys=True, default=str)
                           .encode("utf-8"), digest_size=8).hexdigest()


def entry_path(name):
    return GOLDEN_DIR / f"{name}.json"


def load(name):
    path = entry_path(name)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save(name, record, reason):
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    entry_path(name).write_text(json.dumps({
        "entry": name,
        "baselined_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "reason": reason,
        "outputs": record,
    }, indent=2), encoding="utf-8")


def diff(name, current):
    """Blocking and reporting differences against the stored baseline."""
    stored = load(name)
    if stored is None:
        return None, [], []
    previous = stored["outputs"]
    blocking, reporting = [], []
    for key in sorted(set(previous) | set(current)):
        before, after = previous.get(key), current.get(key)
        if before == after:
            continue
        line = f"{key}: {before!r} -> {after!r}"
        if key in MEASURED_KEYS:
            blocking.append(line)
        elif key in REPORT_ONLY_KEYS:
            reporting.append(line)
        else:
            # UNKNOWN KEYS BLOCK. A new output nobody classified could be a
            # measurement, and defaulting an unclassified number to
            # "reporting" would let a measured value change quietly the first
            # time it appears.
            blocking.append(line + "   [unclassified key - classify it]")
    return stored, blocking, reporting


def corpus_ready():
    """The corpus must exist before a baseline means anything."""
    if not CORPUS.is_dir():
        return False, (
            f"The repro corpus does not exist at {CORPUS}.\n"
            f"A golden record captured without frozen inputs would be a "
            f"baseline of whatever happened to be on the drive that day, and "
            f"the first diff would report drift that was really a different "
            f"recording.")
    clips = [p.name for p in CORPUS.iterdir() if p.is_dir()]
    return bool(clips), (f"{len(clips)} clip(s): {', '.join(sorted(clips))}"
                         if clips else "the corpus directory is empty")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--reason", default="",
                    help="required with --baseline when a record already "
                         "exists: why the expected values changed")
    ap.add_argument("--entry", default=None)
    args = ap.parse_args()

    check_tolerances()
    ready, message = corpus_ready()
    print(f"repro corpus: {message}")
    if not ready:
        print("\nNOTHING BASELINED. Build the corpus first.")
        return 2

    from golden_entries import ENTRIES          # noqa: E402
    names = [args.entry] if args.entry else sorted(ENTRIES)
    failed = False
    for name in names:
        run = ENTRIES[name]
        print(f"\n--- {name}")
        current = run()
        stored, blocking, reporting = diff(name, current)
        if stored is None:
            if not args.baseline:
                print("  no baseline yet; run with --baseline")
                continue
            save(name, current, args.reason or "first baseline")
            print(f"  baselined {len(current)} output(s)")
            continue
        for line in reporting:
            print(f"  report   {line}")
        for line in blocking:
            print(f"  CHANGED  {line}")
        if blocking and args.baseline:
            if not args.reason:
                print("  REFUSED: measured values changed and no --reason "
                      "given. A re-baseline needs its justification in the "
                      "same commit.")
                failed = True
                continue
            save(name, current, args.reason)
            print(f"  re-baselined with reason: {args.reason}")
        elif blocking:
            failed = True
        elif not reporting:
            print("  identical")
    if failed:
        print("\nGOLDEN RECORDS CHANGED. Publish blocked.")
        print("Accept with --baseline --reason '...' in the same commit as "
              "the change that caused it.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
