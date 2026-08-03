"""Regression tests for app/batch_audit.py.

The acceptance-sampling numbers are checked against the definition itself
(the probability of drawing zero defectives from a stratum that really is
defective at the AQL), not against a remembered table - so a wrong constant
cannot pass by matching a wrong expectation.
"""
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import batch_audit as ba

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


def item(i, stratum="s1", conf=0.9, abstained=False):
    return ba.AuditItem(
        item_id=f"{stratum}-{i}", confidence=conf, abstained=abstained,
        abstain_reason="too dim" if abstained else None,
        stratum_keys={"session": stratum}, evidence_path=f"/ev/{stratum}-{i}.png",
        module_name="demo", module_version="1.0")


print("batch_audit - regression\n")

# ---------------------------------------------------------------------------
# 1. Sample size satisfies its own definition
# ---------------------------------------------------------------------------
import math
for N, aql, alpha in [(100, 0.05, 0.05), (500, 0.05, 0.05),
                      (100, 0.01, 0.05), (50, 0.10, 0.01), (20, 0.05, 0.05)]:
    n = ba.required_sample_size(N, aql, alpha)
    D = max(1, math.ceil(aql * N))
    p_at_n = ba._p_zero_defects(N, D, n)
    check(f"N={N} aql={aql} alpha={alpha}: n={n} achieves P(miss) <= alpha",
          p_at_n <= alpha + 1e-12, f"P={p_at_n:.4f}")
    if n > 1:
        p_below = ba._p_zero_defects(N, D, n - 1)
        check(f"N={N} aql={aql} alpha={alpha}: n is the SMALLEST such n",
              p_below > alpha, f"P(n-1)={p_below:.4f}")

check("a tighter AQL demands a bigger sample",
      ba.required_sample_size(1000, 0.01) > ba.required_sample_size(1000, 0.10),
      (ba.required_sample_size(1000, 0.01), ba.required_sample_size(1000, 0.10)))
check("a stricter alpha demands a bigger sample",
      ba.required_sample_size(1000, 0.05, 0.01) > ba.required_sample_size(1000, 0.05, 0.10))
check("sampling is finite-population aware: a small stratum needs a larger "
      "FRACTION reviewed than a big one for the same guarantee",
      ba.required_sample_size(50, 0.05) / 50 > ba.required_sample_size(5000, 0.05) / 5000,
      (ba.required_sample_size(50, 0.05) / 50, ba.required_sample_size(5000, 0.05) / 5000))
check("a stratum too small to ever reach alpha is fully censused, not "
      "silently under-sampled",
      ba.required_sample_size(3, 0.05, 0.05) == 3, ba.required_sample_size(3, 0.05, 0.05))

for bad in [(0, 0.05, 0.05), (100, 0.0, 0.05), (100, 1.5, 0.05), (100, 0.05, 0.0)]:
    try:
        ba.required_sample_size(*bad)
        check(f"invalid parameters {bad} are refused", False)
    except ba.BatchAuditError:
        check(f"invalid parameters {bad} are refused", True)

# ---------------------------------------------------------------------------
# 2. The reverse question a review budget actually poses
# ---------------------------------------------------------------------------
rate = ba.detectable_defect_rate(1000, 60)
check("a budget of 60 per 1000 rules out roughly a 5% defect rate",
      0.02 < rate < 0.09, rate)
check("reviewing more rules out a smaller rate",
      ba.detectable_defect_rate(1000, 200) < ba.detectable_defect_rate(1000, 60))
check("forward and reverse agree: n from an AQL rules out about that AQL",
      abs(ba.detectable_defect_rate(1000, ba.required_sample_size(1000, 0.05)) - 0.05)
      < 0.02,
      ba.detectable_defect_rate(1000, ba.required_sample_size(1000, 0.05)))

# ---------------------------------------------------------------------------
# 3. Stratification is mandatory
# ---------------------------------------------------------------------------
no_keys = [ba.AuditItem(item_id=f"x{i}", confidence=0.9, stratum_keys={})
           for i in range(10)]
try:
    ba.plan_audit(no_keys)
    check("items with no stratum keys are refused", False)
except ba.BatchAuditError as exc:
    check("items with no stratum keys are refused", True)
    check("the refusal explains why a global random sample is not a fallback",
          "global random" in str(exc).lower(), str(exc)[:80])

try:
    ba.plan_audit([ba.AuditItem(item_id="a", confidence=1.7,
                                stratum_keys={"session": "s"})])
    check("a confidence outside 0..1 is refused", False)
except ba.BatchAuditError:
    check("a confidence outside 0..1 is refused", True)

try:
    ba.plan_audit([])
    check("an empty item list is refused", False)
except ba.BatchAuditError:
    check("an empty item list is refused", True)

# ---------------------------------------------------------------------------
# 4. Planning: per-stratum, abstentions excluded
# ---------------------------------------------------------------------------
items = ([item(i, "sessionA") for i in range(120)]
         + [item(i, "sessionB") for i in range(80)]
         + [item(900 + i, "sessionB", conf=0.99, abstained=True) for i in range(5)])
plans = ba.plan_audit(items, aql=0.05, alpha=0.05)
check("one plan per stratum", len(plans) == 2, [p.stratum_id for p in plans])
by_id = {p.stratum_id: p for p in plans}
a, b = by_id["session=sessionA"], by_id["session=sessionB"]
check("each stratum is sized from its OWN population, not the dataset total",
      a.sample_size == ba.required_sample_size(120, 0.05, 0.05)
      and b.sample_size == ba.required_sample_size(80, 0.05, 0.05),
      (a.sample_size, b.sample_size))
check("abstained items are excluded from the sampled population",
      b.population == 80, b.population)
check("abstained items are routed to full review regardless of a high "
      "confidence value - the module already declined to stand behind them",
      len(b.abstained_item_ids) == 5, len(b.abstained_item_ids))
check("the sample is drawn only from eligible items",
      not set(b.sample_item_ids) & set(b.abstained_item_ids))
check("sample size matches the number of ids drawn",
      len(a.sample_item_ids) == a.sample_size)
check("planning is reproducible for a given seed",
      ba.plan_audit(items, seed=0)[0].sample_item_ids == plans[0].sample_item_ids)

# the sample must be representative, not confidence-ranked
mixed = [item(i, "sx", conf=(i / 100.0)) for i in range(100)]
mixed_plan = ba.plan_audit(mixed, seed=3)[0]
drawn_conf = [float(x.item_id.split("-")[1]) / 100.0 for x in
              [m for m in mixed if m.item_id in set(mixed_plan.sample_item_ids)]]
check("the sample is NOT taken from the least confident items - the "
      "acceptance math assumes it stands for its stratum",
      max(drawn_conf) > 0.5, (min(drawn_conf), max(drawn_conf)))

# ---------------------------------------------------------------------------
# 5. The zero-defect rule and escalation
# ---------------------------------------------------------------------------
clean = {i: ba.ACCEPT for i in a.sample_item_ids}
out = ba.evaluate_stratum(a, clean)
check("a clean sample accepts the stratum", out.accepted is True)
check("acceptance records the sample size and AQL as provenance",
      out.reviewed == a.sample_size and out.aql == 0.05)
check("acceptance says plainly that this is weaker than full review",
      "weaker claim" in out.reason.lower(), out.reason[-60:])

one_bad = dict(clean); one_bad[a.sample_item_ids[0]] = ba.REJECT
out_bad = ba.evaluate_stratum(a, one_bad)
check("a single rejection escalates the stratum", out_bad.accepted is False)
check("escalation covers the stratum's ENTIRE population, not just the "
      "sampled items", out_bad.escalated_population == a.population,
      out_bad.escalated_population)
check("the escalation reason names it as systematic rather than a rounding "
      "error", "systematic" in out_bad.reason.lower())

uncertain = dict(clean); uncertain[a.sample_item_ids[1]] = ba.UNCERTAIN
out_unc = ba.evaluate_stratum(a, uncertain)
check("'uncertain' fails the zero-defect rule exactly as a rejection does - "
      "ambiguity is evidence the item needs full review",
      out_unc.accepted is False)

try:
    ba.evaluate_stratum(a, {a.sample_item_ids[0]: ba.ACCEPT})
    check("an incomplete review is refused rather than scored early", False)
except ba.BatchAuditError:
    check("an incomplete review is refused rather than scored early", True)

# ---------------------------------------------------------------------------
# 6. Methods summary carries what a paper must state
# ---------------------------------------------------------------------------
outcomes = [ba.evaluate_stratum(a, clean), ba.evaluate_stratum(b, {i: ba.ACCEPT for i in b.sample_item_ids})]
summary = ba.methods_summary(plans, outcomes, "demo", "1.0", "plateau vs spike")
for key in ("aql", "alpha", "sample_sizes_per_stratum", "n_strata_escalated",
            "confidence_definition"):
    check(f"methods summary reports {key}", key in summary and summary[key] is not None)
check("methods summary states the status word",
      summary["status"] == "batch_audited")
check("methods summary carries the not-equivalent-to-full-review caveat",
      "not equivalent" in summary["caveat"].lower())

# ---------------------------------------------------------------------------
# 7. Log pairs confidence with the verdict (what calibration will need)
# ---------------------------------------------------------------------------
tmp = Path(tempfile.mkdtemp())
try:
    log = ba.AuditLog(root=tmp)
    sampled = set(a.sample_item_ids)
    for it in items:
        if it.stratum_id() != a.stratum_id:
            continue
        log.record(it, a, decision=clean.get(it.item_id),
                   sampled=it.item_id in sampled)
    rows = log.read_all()
    check("every considered item is logged, not only the sampled ones",
          len(rows) == 120, len(rows))
    reviewed = [r for r in rows if r["in_audit_sample"]]
    check("sampled rows carry a reviewer decision",
          all(r["reviewer_decision"] for r in reviewed), len(reviewed))
    check("every row pairs confidence with the verdict, which is what a "
          "later calibration pass needs",
          all("confidence" in r and "reviewer_decision" in r for r in rows))
    check("rows record the module version, so a curve is never pooled "
          "across versions by accident",
          all(r["module_version"] == "1.0" for r in rows))
    check("rows record the AQL and alpha the sample size came from",
          all(r["aql"] == 0.05 and r["alpha"] == 0.05 for r in rows))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("BATCH_AUDIT_REGRESSION_PASS")
