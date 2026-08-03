"""Regression tests for app/calibration_pipeline.py.

The scientific-integrity rules are the point of this module, so they are
what get tested hardest: held-out data must stop being held out once it
tunes something, a confidence curve must not pool across module versions,
'uncertain' must not count as acceptance, and a split must be by session
rather than by frame.
"""
from pathlib import Path
import shutil
import sys
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import calibration_pipeline as cp

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("calibration_pipeline - regression\n")
tmp = Path(tempfile.mkdtemp())
try:
    # -----------------------------------------------------------------------
    # 1. Ledger: held-out status is auditable, not remembered
    # -----------------------------------------------------------------------
    ledger = cp.DatasetLedger(root=tmp / "cal")
    ds = cp.LegacyDataset(
        dataset_id="pumping_2019", module_target="pharyngeal_pumping",
        source_path="L:/legacy/pumping", scoring_records="L:/legacy/pumping.xlsx",
        scorer_id="student_a", scoring_protocol_notes="counted by eye at 0.25x",
        blinded=True, double_scored=None)
    ledger.register(ds)
    check("a legacy dataset registers", len(ledger.datasets()) == 1)
    try:
        ledger.register(ds)
        check("registering the same dataset twice is refused", False)
    except cp.CalibrationError as exc:
        check("registering the same dataset twice is refused", True)
        check("the refusal explains the double-counting risk",
              "two independent validations" in str(exc), str(exc)[-50:])

    check("a fresh dataset is held out for a module by default",
          ledger.is_held_out_for("pumping_2019", "pharyngeal_pumping"))
    ledger.record_use("pumping_2019", "other_module", "1.0", cp.TUNING)
    check("tuning a DIFFERENT module does not spend this dataset's held-out "
          "status for the module in question",
          ledger.is_held_out_for("pumping_2019", "pharyngeal_pumping"))
    ledger.record_use("pumping_2019", "pharyngeal_pumping", "1.0", cp.TUNING)
    check("once used for tuning, the dataset is no longer held out",
          not ledger.is_held_out_for("pumping_2019", "pharyngeal_pumping"))
    try:
        ledger.record_use("pumping_2019", "m", "1", "something_else")
        check("an unrecognised use role is refused", False)
    except cp.CalibrationError:
        check("an unrecognised use role is refused", True)
    try:
        ledger.record_use("never_registered", "m", "1", cp.HELD_OUT)
        check("recording use of an unregistered dataset is refused", False)
    except cp.CalibrationError:
        check("recording use of an unregistered dataset is refused", True)

    # -----------------------------------------------------------------------
    # 2. Agreement analysis refuses contaminated data
    # -----------------------------------------------------------------------
    agreement = cp.continuous_agreement([10.0, 12.0, 14.0], [10.5, 11.5, 14.5])
    try:
        cp.validate_against_legacy(ledger, "pumping_2019", "pharyngeal_pumping",
                                   "1.0", agreement)
        check("agreement is refused on a dataset already used for tuning", False)
    except cp.CalibrationError as exc:
        check("agreement is refused on a dataset already used for tuning", True)
        check("the refusal says the number would be optimistically biased",
              "optimistically biased" in str(exc), str(exc)[:70])

    clean = cp.LegacyDataset(
        dataset_id="pboc_2020", module_target="defecation",
        source_path="L:/legacy/pboc", scoring_records="L:/legacy/pboc.csv",
        double_scored=True, inter_scorer_agreement=0.88)
    ledger.register(clean)
    out = cp.validate_against_legacy(ledger, "pboc_2020", "defecation", "2.1",
                                     agreement)
    check("agreement runs on a genuinely held-out dataset", out["held_out"] is True)
    check("the inter-scorer ceiling is reported alongside the result",
          out.get("inter_scorer_ceiling") == 0.88)
    check("the ceiling is explained as bounding what any module could achieve",
          "ceiling" in out.get("ceiling_note", "").lower())
    check("using it for validation is itself recorded in the ledger",
          any(r["role"] == cp.HELD_OUT
              for r in ledger.uses("pboc_2020", "defecation")))
    check("a never-double-scored dataset says variability is UNKNOWN rather "
          "than assuming the single score is exact",
          "UNKNOWN" in cp.validate_against_legacy(
              ledger, "pumping_2019", "pharyngeal_pumping", "1.0", agreement,
              allow_contaminated=True).get("ceiling_note", ""))

    # -----------------------------------------------------------------------
    # 3. Confidence calibration
    # -----------------------------------------------------------------------
    # A deliberately OVERCONFIDENT module: high scores, mediocre accept rate.
    rows = []
    for i in range(200):
        conf = 0.90 + (i % 10) * 0.005
        accepted = (i % 10) < 6          # ~60% accepted despite ~0.92 claimed
        rows.append({"module_version": "1.0", "in_audit_sample": True,
                     "confidence": conf,
                     "reviewer_decision": "accept" if accepted else "reject"})
    # Same module, different version, well calibrated - must not be pooled in.
    for i in range(200):
        rows.append({"module_version": "2.0", "in_audit_sample": True,
                     "confidence": 0.9,
                     "reviewer_decision": "accept" if i % 10 < 9 else "reject"})

    cal_v1 = cp.confidence_calibration(rows, module_version="1.0")
    check("overconfidence is detected", cal_v1["overconfident"] is True,
          cal_v1["signed_bias"])
    check("overconfidence is called out as the dangerous direction",
          "dangerous direction" in cal_v1["interpretation"])
    check("only the requested version's records are used",
          cal_v1["n_reviewed"] == 200, cal_v1["n_reviewed"])
    cal_v2 = cp.confidence_calibration(rows, module_version="2.0")
    check("a well-calibrated version is not flagged overconfident",
          cal_v2["overconfident"] is False, cal_v2["signed_bias"])
    check("the two versions give different answers, i.e. pooling them would "
          "have corrupted the curve",
          abs(cal_v1["signed_bias"] - cal_v2["signed_bias"]) > 0.15,
          (cal_v1["signed_bias"], cal_v2["signed_bias"]))

    unc = [{"module_version": "3.0", "in_audit_sample": True, "confidence": 0.95,
            "reviewer_decision": "uncertain"} for _ in range(50)]
    cal_unc = cp.confidence_calibration(unc, module_version="3.0")
    check("'uncertain' does not count as acceptance - counting it would make "
          "the module look better calibrated than it is",
          cal_unc["bins"][0]["observed_accept_rate"] == 0.0)

    try:
        cp.confidence_calibration(rows, module_version="does_not_exist")
        check("a version with no reviewed records raises rather than "
              "returning an empty curve", False)
    except cp.CalibrationError:
        check("a version with no reviewed records raises rather than "
              "returning an empty curve", True)

    # -----------------------------------------------------------------------
    # 4. Threshold recommendation carries its own evidence
    # -----------------------------------------------------------------------
    graded = []
    for i in range(300):
        conf = i / 300.0
        bad = np.random.RandomState(i).rand() > conf   # worse at low confidence
        graded.append({"module_version": "1.0", "in_audit_sample": True,
                       "confidence": conf,
                       "reviewer_decision": "reject" if bad else "accept"})
    rec = cp.recommended_auto_accept_threshold(graded, "1.0", target_error_rate=0.10)
    check("a threshold is recommended with a measured error rate attached",
          rec["threshold"] is not None and "observed error rate" in rec["reason"],
          rec.get("reason", "")[:70])
    impossible = [{"module_version": "1.0", "in_audit_sample": True,
                   "confidence": 0.99, "reviewer_decision": "reject"}
                  for _ in range(50)]
    rec_none = cp.recommended_auto_accept_threshold(impossible, "1.0")
    check("when no threshold is supportable, None is returned rather than a "
          "guess", rec_none["threshold"] is None)
    check("and it says auto-accept is not supportable yet",
          "not supportable" in rec_none["reason"])

    # -----------------------------------------------------------------------
    # 5. Parameter recalibration reports the distribution
    # -----------------------------------------------------------------------
    tight = [{"module_version": "1.0", "implied": 1.5 + 0.02 * (i % 5),
              "strain": "N2"} for i in range(60)]
    res_tight = cp.parameter_recalibration(tight, lambda r: r["implied"], "1.0")
    check("a tight distribution supports a global default",
          res_tight["stable_operating_point"] is True,
          res_tight["relative_spread"])

    wide = [{"module_version": "1.0", "implied": 0.5 if i % 2 else 3.0,
             "strain": "N2" if i % 2 else "dys-1"} for i in range(60)]
    res_wide = cp.parameter_recalibration(wide, lambda r: r["implied"], "1.0",
                                          stratify_by="strain")
    check("a wide/multimodal distribution does NOT produce a single default",
          res_wide["stable_operating_point"] is False)
    check("and says that is the finding rather than a missing number",
          "the finding" in res_wide["recommendation"], res_wide["recommendation"][-60:])
    check("stratified disagreement is surfaced, so a default that is better "
          "on average but worse for one strain cannot hide",
          res_wide.get("stratum_disagreement", 0) > 0.25,
          res_wide.get("stratum_disagreement"))

    # -----------------------------------------------------------------------
    # 6. Agreement forms appropriate to the measurement type
    # -----------------------------------------------------------------------
    biased_m = [10.0, 11.0, 12.0, 13.0]
    biased_h = [8.0, 9.0, 10.0, 11.0]          # module reads 2 units high
    ba_res = cp.continuous_agreement(biased_m, biased_h)
    check("a constant offset shows up as bias even at perfect correlation",
          abs(ba_res["bias"] - 2.0) < 1e-9 and ba_res["correlation"] > 0.999,
          (ba_res["bias"], ba_res["correlation"]))

    ev = cp.event_agreement([1.0, 2.0, 3.0, 9.0], [1.05, 2.1, 3.0, 5.0],
                            tolerance=0.2)
    check("an event slightly off in time counts as matched, not missed",
          ev["matched"] == 3, ev)
    check("an event with no counterpart counts as missed", ev["missed"] == 1, ev)
    check("an invented event counts as spurious", ev["spurious"] == 1, ev)

    cat = cp.categorical_agreement(["a", "a", "b", "b", "a"],
                                   ["a", "a", "b", "a", "a"])
    check("categorical agreement reports per-class rates, not just accuracy",
          "per_class" in cat and set(cat["per_class"]) == {"a", "b"})
    check("a class that fails is visible in its own recall",
          cat["per_class"]["a"]["recall"] < 1.0, cat["per_class"])

    # -----------------------------------------------------------------------
    # 7. Curation split discipline
    # -----------------------------------------------------------------------
    frames = [{"id": f"{s}-{i}", "session": s, "strain": "N2"}
              for s in ("s1", "s2", "s3", "s4") for i in range(25)]
    split = cp.curation_split(frames, train_fraction=0.75, seed=1)
    train_sessions = {i["session"] for i in split["train"]}
    test_sessions = {i["session"] for i in split["test"]}
    check("the split is by session, so no session appears on both sides - "
          "frames from one animal are not independent examples",
          not (train_sessions & test_sessions), (train_sessions, test_sessions))
    check("both sides are non-empty", split["train"] and split["test"])
    try:
        cp.curation_split([{"id": "a", "session": "only"}], seed=0)
        check("a single-session pool is refused rather than split by frame", False)
    except cp.CalibrationError as exc:
        check("a single-session pool is refused rather than split by frame", True)
        check("the refusal explains the same-animal problem",
              "same animal" in str(exc).lower(), str(exc)[-60:])

    narrow = [{"id": f"x{i}", "session": "s1", "strain": "N2"} for i in range(10000)]
    broad = [{"id": f"y{i}", "session": f"s{i % 30}", "strain": "N2"}
             for i in range(1000)]
    cov_n = cp.coverage_report(narrow)
    cov_b = cp.coverage_report(broad)
    check("coverage reports breadth, not just size: 10000 frames from 1 "
          "session is narrower than 1000 from 30",
          cov_n["n_sessions"] == 1 and cov_b["n_sessions"] == 30,
          (cov_n["n_sessions"], cov_b["n_sessions"]))
    check("the coverage note says why breadth matters more than count",
          "correlated" in cov_b["note"])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("CALIBRATION_PIPELINE_REGRESSION_PASS")
