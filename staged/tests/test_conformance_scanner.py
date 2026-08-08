"""The scanner's self-test: every rule must fire on a planted violation.

ERROR MACHINERY IS NOT TRUSTWORTHY UNTIL IT HAS BEEN FIRED. This project has
now produced four instances of the same family, three of them mine:

  a crash handler that filed a CLEAN EXIT moments after reporting the crash
  a publish refusal whose failure notice read "PASS"
  an except clause naming something imported inside its own try
  a scanner whose fixture exclusion also silenced its own self-test

Each looked correct and each was only wrong on the path nobody exercises. So
the fixtures are exercised HERE, inside the release check suite, rather than
by remembering to point --root at them.

The check that matters is the LAST one: every non-retired rule fires. A rule
that silently stops matching is indistinguishable from a clean tree, which is
precisely how the fixture exclusion once took 9 of 9 rules to 0 of 9 while the
scanner reported success either way.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
CONFORMANCE = ROOT / "tools" / "conformance"
sys.path.insert(0, str(CONFORMANCE))

import rules as ruleset                            # noqa: E402
import scan as scanner                             # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("conformance scanner - the self-test\n")

fixtures = CONFORMANCE / "fixtures"
check("the fixture tree exists", fixtures.is_dir(), str(fixtures))

findings = scanner.scan(root=fixtures)
fired = {f["rule"] for f in findings}
live = [r["id"] for r in ruleset.RULES if not r.get("retired")]

check("scanning the fixtures produces findings at all - an exclusion that "
      "also silences the self-test once took 9 of 9 rules to 0 of 9",
      bool(findings), f"{len(findings)} findings")

missing = [rule for rule in live if rule not in fired]
check("EVERY live rule fires on its planted violation; a rule that quietly "
      "stops matching looks exactly like a clean tree",
      not missing, f"silent: {missing}" if missing else f"{len(live)} rules")

# ------------------------------------------------- the structural rule
structural = [r for r in ruleset.RULES if r.get("check")]
check("at least one rule is structural - some defects are shape, not text",
      bool(structural), [r["id"] for r in structural])

hits = [f for f in findings if f["rule"] == "handler-name-bound-in-try"]
check("the handler-name rule fires on a name imported inside its own try",
      bool(hits), hits[0]["evidence"] if hits else "no hit")

# The legitimate optional-dependency shape sits two functions above the
# planted one in the same fixture and must NOT be reported: ImportError is a
# builtin, not something the try binds.
check("and does NOT fire on `try: import cv2 / except ImportError`, which is "
      "the correct way to make a dependency optional",
      all("ImportError" not in f["matched"] for f in hits),
      [f["matched"] for f in hits])

# ------------------------------------------------ structural rule directly
sample = '''
try:
    from thing import Boom
except Boom:
    pass
'''
found = ruleset.except_name_imported_in_try("x.py", sample)
check("the checker reports the handler line, not the import line",
      found and found[0][0] == 3, found)

clean = '''
from thing import Boom
try:
    risky()
except Boom:
    pass
'''
check("a name imported ABOVE the try is fine - that is the fix, and the rule "
      "must accept it or it would report every correct handler",
      not ruleset.except_name_imported_in_try("x.py", clean))

check("a file that does not parse yields nothing rather than raising; the "
      "scanner must survive a half-written file",
      ruleset.except_name_imported_in_try("x.py", "def (:") == [])

# ------------------------------------------------------- record keeping
check("every live rule carries the incident it came from - a rule whose "
      "reason is forgotten is one somebody deletes when it is inconvenient",
      all(r.get("incident") for r in ruleset.RULES if not r.get("retired")))
check("every finding carries its rank, so publish knows what blocks",
      all(f["rank"] in ("measured-values", "gating", "cosmetic")
          for f in findings))

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("CONFORMANCE_SCANNER_PASS")
