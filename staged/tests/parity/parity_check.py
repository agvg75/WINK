"""
parity_harness/parity_check.py
===============================
Trust-gate harness for the RGBCaMP Fiji plugin (see
RGBCaMP_fiji_plugin_handoff.docx, "Parity test: the trust gate").

The plugin is to be a thin Java/SciJava shell that delegates all numerics to
this same Python analysis (worm_rgbcamp_analysis.py + worm_kinetics.py),
unchanged. This harness is the gate that proves that delegation is faithful:
it freezes one recording plus the expected output tables from a DIRECT run of
the Python module, then diffs a CANDIDATE run against that frozen golden
output.

Tolerance rule (per the handoff): integer counts and flag columns must match
EXACTLY; floats are compared to a relative tolerance of 1e-6 to absorb
platform floating-point differences. The QC log and flag columns are diffed
explicitly, not just the headline numeric metrics.

Usage
-----
  python parity_check.py freeze     golden_input_<case>/<file>.csv  golden_output_<case>/
  python parity_check.py check      golden_output_<case>/  [--candidate DIR]
  python parity_check.py check-all  [harness_dir]

`check` with no --candidate re-runs the direct Python path on the frozen
input and diffs the fresh run against the frozen golden output (a
determinism self-test -- there is no Java plugin yet). Once the Fiji plugin
exists, point --candidate at the directory its Python subprocess wrote its
tables to (same file names as golden_output_<case>/, plus an optional
qc_report.json); the diffing logic does not change.

`check-all` self-tests every golden_output* case in one call -- run this as
the gate. There are six cases:
  golden_output/            case 1: pilot recording, contract_version 2, no
                            background columns at all (background_applied=
                            False is the CORRECT expected state here).
  golden_output_bg/         case 2: a REAL contract_version-3 export with
                            non-empty bg_blue/bg_green/bg_red, added so a
                            regression in the background-subtraction path
                            fails a check instead of passing silently -- case
                            1 alone never exercised that path at all.
  golden_output_perchannel/ case 3 (Stage 2a): the SAME real export, gating
                            the per-channel calcium path -- red/blue outputs
                            and the dorsal/ventral split.
  golden_output_coupling/   case 4 (Stage 2b): the SAME real export, gating
                            curvature_phase_lag (green/red/blue) and
                            interchannel_timing (green_vs_blue, green_vs_red)
                            -- the sub-frame phase/xcorr-parabolic coupling
                            path. Verified: cases 1/2/3 pass even when the
                            shared _band_hilbert_phase helper is broken (none
                            of them call it); case 4 catches it immediately.
  golden_output_kinematics/ case 5 (Stage 3a): the SAME real export, gating
                            undulation_descriptors and locomotion_summary --
                            posture-only kinematics that are NOT head-masked
                            (unlike every calcium/coupling table in cases
                            1-4). Verified: cases 1-4 pass even when
                            wave_propagation is broken specifically for
                            value="seg_curv_deg" (the kinematic body-wave
                            call); case 5 catches it immediately.
  golden_output_neuromech/  case 6 (Stage 3c): the SAME real export, gating
                            curvature_to_translation, propulsion_efficiency,
                            and calcium_output_decomposition (green/red/blue)
                            -- the neuromechanical chain's missing middle
                            link and the propulsion-efficiency spatial
                            breakdown. Verified: broke the shared
                            _xcorr_lag_parabolic estimator to always return
                            zero lag/peak; case 6 failed immediately on 5
                            fields across curvature_to_translation and
                            calcium_output_decomposition, while cases 1-5
                            passed regardless.
  Cases 3, 4, 5, and 6 are frozen via compute_reference_via_run_one
  (mode="run_one" in the manifest), i.e. by calling run_one.analyse_one
  directly rather than a hand-rolled mirror of it, so the harness tests the
  SAME path the browser and CLI use.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import scipy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "rgbcamp" / "pipeline"))
import worm_rgbcamp_analysis as wa
import worm_channels as wc
import worm_kinetics as wk
import run_one

RTOL = 1e-6
ATOL = 1e-9

# Tables frozen/checked by the LEGACY reference path (cases 1 and 2, frozen
# before the per-channel work existed). release_reuptake carries every Fix
# 1-3 flag column (onset_at_boundary, decay_incomplete, tau_extrapolated,
# decay_subresolution, confirmatory) so it is the highest-value table for
# this gate; region_split and contraction_state are cheap additional
# cross-checks on the same masked frame.
TABLE_BUILDERS = {
    "release_reuptake": lambda m, wid: wk.release_reuptake(m, wid),
    "region_split": lambda m, wid: wk.region_split(m),
    "contraction_state": lambda m, wid: wk.contraction_state(m),
}


def compute_reference_legacy(csv_path: Path) -> tuple[dict, dict]:
    """Original reference path: load -> QC -> channel normalisation -> head
    mask -> the 3 green-only tables above. Kept EXACTLY as before (byte for
    byte, per the "leave existing golden cases untouched" rule) for cases 1
    and 2, which were frozen against this path. Uses worm_channels.apply_
    normalisation (the SAME call run_one.py and worm_batch.py make), not the
    older wa.add_dff -- otherwise this harness would never exercise the
    background-subtraction path at all, regardless of what the golden CSV
    contains. (That was the second half of the original background bug: the
    harness's own reference path bypassed worm_channels.py entirely.)"""
    df = wa.load_extracted(csv_path, genotype_col="genotype")
    filt, qc_report = wa.qc_filter(df)
    chan_cfg = wc.ChannelConfig(roles={"green": wc.ROLE_ACTIVITY, "red": wc.ROLE_ACTIVITY,
                                       "blue": wc.ROLE_ACTIVITY})
    filt, chan_report = wc.apply_normalisation(filt, chan_cfg)
    masked = wk.mask_head(filt)
    worm_id = str(masked["worm_id"].iloc[0])
    tables = {name: build(masked, worm_id) for name, build in TABLE_BUILDERS.items()}
    return tables, dict(qc=qc_report, channel=chan_report)


def compute_reference_via_run_one(csv_path: Path, table_keys: list) -> tuple[dict, dict]:
    """Reference path for the per-channel golden case (Stage 2a): calls
    run_one.analyse_one() directly (writing to a throwaway temp directory),
    so this harness tests the SAME computation path the browser and CLI
    launcher actually use -- not a hand-rolled mirror that could quietly
    diverge from it. `table_keys` selects which of run_one's ~27 tables this
    particular case freezes/checks (e.g. the red/blue/dorsal-ventral ones)."""
    with tempfile.TemporaryDirectory() as tmp:
        result = run_one.analyse_one(csv_path, out_dir=tmp)
        tables = {k: result.tables[k] for k in table_keys}
        report = dict(qc=result.qc_report, channel=result.channel_report)
    return tables, report


def compute_reference(csv_path: Path, mode: str = "legacy", table_keys: list | None = None):
    if mode == "run_one":
        return compute_reference_via_run_one(csv_path, table_keys or [])
    return compute_reference_legacy(csv_path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def freeze(csv_path: Path, golden_dir: Path, mode: str = "legacy", table_keys: list | None = None):
    tables, report = compute_reference(csv_path, mode=mode, table_keys=table_keys)
    golden_dir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(golden_dir / f"{name}.csv", index=False)
    (golden_dir / "qc_report.json").write_text(json.dumps(report, indent=2, default=str))
    manifest = dict(
        source_csv=csv_path.name,
        golden_input_dir=csv_path.parent.name,   # so check() can locate any case's input, not just "golden_input"
        source_sha256=_sha256(csv_path),
        tables=sorted(tables.keys()),
        mode=mode,                                # "legacy" (cases 1/2) or "run_one" (per-channel case)
        python=platform.python_version(),
        numpy=np.__version__, pandas=pd.__version__, scipy=scipy.__version__,
        rtol=RTOL, atol=ATOL,
    )
    if mode == "run_one":
        manifest["table_keys"] = sorted(tables.keys())
    (golden_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    print(f"Froze {len(tables)} table(s) + manifest to {golden_dir} (mode={mode})")
    for name, df in tables.items():
        print(f"  {name}: {len(df)} rows, {len(df.columns)} cols")
    print(f"  background_applied={report['channel']['background_applied']} "
          f"cols_used={report['channel']['background_cols_used']}")


def _split_report(report: dict) -> tuple[dict, Optional[dict]]:
    """New shape is {"qc": ..., "channel": ...}; the case-1 golden frozen
    before this gate existed is the flat qc dict with no channel report."""
    if isinstance(report, dict) and "qc" in report and "channel" in report:
        return report["qc"], report["channel"]
    return report, None


def _is_missing(s: pd.Series) -> np.ndarray:
    """True where a value is NaN OR an empty string. A blank CSV cell and an
    in-memory empty string (e.g. a "reason" column's "" for a valid row) are
    the same "no value", regardless of which side produced which dtype.

    Checks is_string_dtype (not `dtype == object`): pandas defaults to its own
    StringDtype now, not plain object, for text columns -- `== object` silently
    misses it and this whole empty-string check goes dead."""
    na = s.isna().to_numpy()
    if pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s):
        return na | (s.astype(str) == "").to_numpy()
    return na


def _diff_table(name: str, golden: pd.DataFrame, candidate: pd.DataFrame) -> list[str]:
    problems = []
    if len(golden) != len(candidate):
        problems.append(f"{name}: row count differs (golden={len(golden)}, candidate={len(candidate)})")
        return problems
    if list(golden.columns) != list(candidate.columns):
        problems.append(f"{name}: column set/order differs "
                        f"(golden={list(golden.columns)}, candidate={list(candidate.columns)})")
        return problems
    for col in golden.columns:
        g, c = golden[col], candidate[col]
        g_missing, c_missing = _is_missing(g), _is_missing(c)
        both_missing = g_missing & c_missing

        # Only true floats get tolerance comparison; everything else (ints, bools,
        # strings/labels) is exact. Deciding this from golden's dtype ALONE is not
        # reliable: a string column that is blank on every row of THIS table (e.g.
        # resting_calcium's "reason" column when every row is valid) round-trips
        # through CSV as float64 NaN, even though the candidate's in-memory
        # version is real text -- so also require the non-missing values on
        # BOTH sides to actually be numeric before treating a column as float.
        g_nonmissing_numeric = (pd.to_numeric(g[~g_missing], errors="coerce").notna().all()
                                if (~g_missing).any() else True)
        c_nonmissing_numeric = (pd.to_numeric(c[~c_missing], errors="coerce").notna().all()
                                if (~c_missing).any() else True)
        is_float_col = (pd.api.types.is_float_dtype(g) and g_nonmissing_numeric
                       and c_nonmissing_numeric)

        if not is_float_col:
            # exact match required -- both-missing rows excused (NaN vs "" both count)
            mism = (g.astype(str) != c.astype(str)) & ~both_missing
            if mism.any():
                rows = golden.index[mism].tolist()
                problems.append(f"{name}.{col}: {int(mism.sum())} exact mismatch(es) "
                                f"(rows {rows[:10]}{'...' if len(rows) > 10 else ''})")
        else:
            gv = pd.to_numeric(g, errors="coerce").to_numpy(dtype=float)
            cv = pd.to_numeric(c, errors="coerce").to_numpy(dtype=float)
            close = np.isclose(gv, cv, rtol=RTOL, atol=ATOL, equal_nan=False) | both_missing
            if not close.all():
                bad = np.where(~close)[0]
                problems.append(f"{name}.{col}: {len(bad)} value(s) outside rtol={RTOL} "
                                f"(rows {bad[:10].tolist()}{'...' if len(bad) > 10 else ''})")
    return problems


def check(golden_dir: Path, candidate_dir: Path | None) -> int:
    manifest = json.loads((golden_dir / "manifest.json").read_text())
    golden_qc, golden_channel = _split_report(json.loads((golden_dir / "qc_report.json").read_text()))

    if candidate_dir is None:
        input_dir_name = manifest.get("golden_input_dir", "golden_input")   # legacy case-1 default
        csv_path = Path(__file__).resolve().parent / input_dir_name / manifest["source_csv"]
        actual_sha = _sha256(csv_path)
        if actual_sha != manifest["source_sha256"]:
            print(f"FAIL: golden input {csv_path.name} changed since freezing "
                  f"(expected sha256 {manifest['source_sha256']}, got {actual_sha})")
            return 1
        mode = manifest.get("mode", "legacy")
        candidate_tables, candidate_report = compute_reference(
            csv_path, mode=mode, table_keys=manifest.get("table_keys"))
        candidate_qc, candidate_channel = _split_report(candidate_report)
    else:
        candidate_tables = {name: pd.read_csv(candidate_dir / f"{name}.csv")
                            for name in manifest["tables"]}
        qc_path = candidate_dir / "qc_report.json"
        if qc_path.exists():
            candidate_qc, candidate_channel = _split_report(json.loads(qc_path.read_text()))
        else:
            candidate_qc, candidate_channel = None, None

    problems = []
    for name in manifest["tables"]:
        golden = pd.read_csv(golden_dir / f"{name}.csv")
        problems += _diff_table(name, golden, candidate_tables[name])

    if candidate_qc is not None:
        for key in ("n_rows_in", "n_rows_kept", "retention_frac"):
            if key in golden_qc and str(golden_qc[key]) != str(candidate_qc.get(key)):
                problems.append(f"qc_report.{key}: golden={golden_qc[key]!r} "
                                f"candidate={candidate_qc.get(key)!r}")
    else:
        problems.append("qc_report.json missing from candidate: QC log was not diffed")

    # Background-subtraction gate: only enforced for golden cases frozen with a
    # channel report (case 1 predates it and is exempt -- it carries no bg_*
    # columns at all, so there's nothing to gate).
    if golden_channel is not None:
        if candidate_channel is None:
            problems.append("channel report missing from candidate: background "
                            "path was not diffed")
        else:
            for key in ("background_applied", "background_cols_used"):
                if str(golden_channel.get(key)) != str(candidate_channel.get(key)):
                    problems.append(f"channel_report.{key}: golden={golden_channel.get(key)!r} "
                                    f"candidate={candidate_channel.get(key)!r}")

    if problems:
        print(f"PARITY CHECK FAILED ({len(problems)} problem(s)):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"PARITY CHECK PASSED: {len(manifest['tables'])} table(s) + QC log match "
          f"exactly on flags/ints/labels and within rtol={RTOL} on floats.")
    return 0


def check_all(harness_dir: Path) -> int:
    """Convenience gate: run check() (self-test mode) on every golden case
    found under harness_dir, i.e. every golden_output* directory that has a
    manifest.json. Non-zero exit if any case fails."""
    cases = sorted(p for p in harness_dir.glob("golden_output*")
                   if (p / "manifest.json").exists())
    if not cases:
        print(f"No golden cases found under {harness_dir}")
        return 1
    failed = []
    for case_dir in cases:
        print(f"--- {case_dir.name} ---")
        rc = check(case_dir, None)
        if rc != 0:
            failed.append(case_dir.name)
        print()
    if failed:
        print(f"CHECK-ALL FAILED: {len(failed)}/{len(cases)} case(s) failed: {failed}")
        return 1
    print(f"CHECK-ALL PASSED: {len(cases)}/{len(cases)} golden case(s) passed.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    fz = sub.add_parser("freeze", help="Freeze golden output tables from a reference CSV")
    fz.add_argument("csv_path", type=Path)
    fz.add_argument("golden_dir", type=Path)
    fz.add_argument("--mode", choices=["legacy", "run_one"], default="legacy",
                    help="legacy: hand-rolled 3-table green-only path (cases 1/2). "
                        "run_one: call run_one.analyse_one directly and freeze the "
                        "tables named by --table-keys (the per-channel case).")
    fz.add_argument("--table-keys", nargs="*", default=None,
                    help="Which run_one table keys to freeze (only used with --mode run_one), "
                        "e.g. region_split_red region_split_blue dorsal_ventral_green")

    ck = sub.add_parser("check", help="Diff a candidate run against the frozen golden output")
    ck.add_argument("golden_dir", type=Path)
    ck.add_argument("--candidate", type=Path, default=None,
                    help="Directory with candidate table CSVs (e.g. plugin output). "
                        "Omit to self-test by re-running the direct Python path.")

    ca = sub.add_parser("check-all", help="Self-test every golden_output* case under this folder")
    ca.add_argument("harness_dir", type=Path, nargs="?", default=Path(__file__).resolve().parent)

    args = ap.parse_args()
    if args.cmd == "freeze":
        freeze(args.csv_path, args.golden_dir, mode=args.mode, table_keys=args.table_keys)
    elif args.cmd == "check":
        sys.exit(check(args.golden_dir, args.candidate))
    else:
        sys.exit(check_all(args.harness_dir))


if __name__ == "__main__":
    main()
