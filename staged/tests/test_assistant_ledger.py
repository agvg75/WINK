"""Quotas, the answer ledger, and the rule that keeps an FAQ from hiding a bug.

Two negative properties carry this file. A cached answer that failed a student
must stop being served, however many others it satisfied. And a question asked
by many students must be reported as evidence about the TOOL, not quietly
turned into documentation.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import assistant_ledger as al   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("assistant ledger - regression\n")
DAY = "2026-08-05"
db = al.open_ledger()

# --- the key includes the tool -------------------------------------------
check("the same words in different tools are different questions",
      al.question_key("pumping", "why did it not find my worm")
      != al.question_key("gcamp", "why did it not find my worm"))
check("...while wording noise collapses to the same key",
      al.question_key("pumping", "Why did it not find my worm?")
      == al.question_key("pumping", "why did it not find the worm"))

# --- quota ----------------------------------------------------------------
q = al.check_quota(db, "student_a", DAY, soft_cap=3, hard_cap=5)
check("a fresh user has full quota", q["remaining"] == 5 and not q["blocked"])

for i in range(3):
    al.record(db, "student_a", DAY, "pumping", f"question {i}", "an answer",
              "api", soft_cap=3, hard_cap=5)
q = al.check_quota(db, "student_a", DAY, soft_cap=3, hard_cap=5)
check("the soft cap warns without blocking",
      q["over_soft"] and not q["blocked"] and q["warning"])
check("...and the warning says the cap is to stop a loop, not to ration help",
      "not to ration help" in q["warning"])

# cached answers must not consume quota
for i in range(9):
    al.record(db, "student_a", DAY, "pumping", "a known question", "cached",
              "cache", soft_cap=3, hard_cap=5)
q = al.check_quota(db, "student_a", DAY, soft_cap=3, hard_cap=5)
check("cached answers do not count against the cap",
      q["api_calls"] == 3 and q["cached_calls"] == 9 and not q["blocked"],
      f"{q['api_calls']} api, {q['cached_calls']} cached")

al.record(db, "student_a", DAY, "pumping", "q4", "a", "api", 3, 5)
al.record(db, "student_a", DAY, "pumping", "q5", "a", "api", 3, 5)
try:
    al.record(db, "student_a", DAY, "pumping", "q6", "a", "api", 3, 5)
    check("the hard cap blocks new API questions", False)
except al.LedgerError as exc:
    check("the hard cap blocks new API questions", True)
    check("...while telling them cached answers still work",
          "still available and cost nothing" in str(exc))

try:
    al.record(db, "s", DAY, "t", "q", "a", "guess")
    check("an unlabelled billing source is refused", False)
except al.LedgerError as exc:
    check("an unlabelled billing source is refused", True,
          "hides real spend" in str(exc))

# --- trust is earned across distinct users --------------------------------
db2 = al.open_ledger()
Q = "what does the coherence value mean"
ids = []
for u in ("a", "b", "c"):
    ids.append(al.record(db2, u, DAY, "morphology", Q, "It is the strength "
                         "of local orientation agreement.", "api"))

check("an unproven answer is not served from the cache",
      al.lookup(db2, "morphology", Q) is None)

st = al.mark_outcome(db2, ids[0], "resolved")
check("one resolution is not enough to trust an answer",
      st["status"] == "unproven", st["why"])
al.mark_outcome(db2, ids[1], "resolved")
st = al.mark_outcome(db2, ids[2], "resolved")
check("three distinct users resolving makes it trusted",
      st["status"] == "trusted" and st["distinct_resolvers"] == 3)
check("...and it is then served from the ledger",
      al.lookup(db2, "morphology", Q) is not None)

# --- THE KEY ONE: one failure demotes it ---------------------------------
bad = al.record(db2, "d", DAY, "morphology", Q, "same answer", "cache")
st = al.mark_outcome(db2, bad, "did_not_help")
check("a single 'did not help' demotes a trusted answer",
      st["status"] == "demoted", f"after {st['distinct_resolvers']} resolvers")
check("...saying why an answer that is right sometimes is the worst to serve",
      "right sometimes" in st["why"])
check("...and it stops being served", al.lookup(db2, "morphology", Q) is None)
check("...but the counts that earned its status are kept",
      st["distinct_resolvers"] == 3 and st["unhelpful"] == 1)

try:
    al.mark_outcome(db2, ids[0], "probably fine")
    check("an invented outcome is refused", False)
except al.LedgerError as exc:
    check("an invented outcome is refused", True)
    check("...preferring unproven to guessed",
          "which is the safe default" in str(exc))

# --- promotion: default to fixing the tool --------------------------------
db3 = al.open_ledger()
FAIL_Q = "why did it not detect my worm"
for u in ("a", "b", "c", "d", "e"):
    al.record(db3, u, DAY, "gcamp", FAIL_Q, "Check the channel.", "api")
CONCEPT_Q = "what is a pBoc"
for u in ("a", "b", "c", "d"):
    al.record(db3, u, DAY, "defecation", CONCEPT_Q,
              "The posterior body wall contraction.", "api")

p = al.promotion_candidates(db3)
check("a repeated failure question is put under 'fix the tool'",
      p["n_fix"] == 1 and p["fix_the_tool"][0]["question"] == FAIL_Q,
      f"{p['n_fix']} to fix, {p['n_faq']} FAQ")
check("...flagged as a defect signal, not a documentation gap",
      p["fix_the_tool"][0]["defect_signal"] is True
      and "defect in the tool first" in p["fix_the_tool"][0]["recommendation"])
check("...saying the answer belongs where the confusion happens",
      "where the confusion happens" in p["fix_the_tool"][0]["recommendation"])
check("a conceptual question IS put forward as a genuine FAQ",
      p["n_faq"] == 1 and p["genuine_faq"][0]["question"] == CONCEPT_Q)
check("the default reading is a defect", p["default_is_defect"] is True
      and "hidden the problem rather than solved it" in p["why"])
check("...and nothing is published automatically",
      "Nothing is published from here" in p["human_decides"])

check("classification separates failures from concepts",
      al.classify("why did it fail") == "failure"
      and al.classify("what is a pBoc") == "concept")

# --- monitoring -----------------------------------------------------------
r = al.usage_report(db)
check("usage is reported per user", r["users"][0]["user"] == "student_a")
check("...with a cache hit rate", 0.0 < r["cache_hit_rate"] < 1.0,
      f"{r['cache_hit_rate']}")
check("...and a note that an outlier is usually a loop, not a keen student",
      "usually a loop" in r["note"])

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("ASSISTANT_LEDGER_PASS")
