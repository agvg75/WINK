"""Method attribution, and the head/tail override that must propagate."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))

import method_provenance as mp   # noqa: E402
import head_tail as ht           # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("method provenance and head override - regression\n")

# --- the registry itself --------------------------------------------------
problems = mp.check_registry()
check("every recorded method has a valid, self-consistent attribution",
      not problems, "; ".join(problems[:3]) if problems else
      f"{len(mp.METHODS)} methods")

s = mp.attribution_summary()
check("all three parties are represented",
      all(s["contributed_to"].get(w, 0) > 0
          for w in ("andres", "claude", "literature")),
      ", ".join(f"{k} {v}" for k, v in sorted(s["contributed_to"].items())))
check("origin and involvement are reported separately",
      sum(s["by_origin"].values()) == s["n_methods"]
      and sum(s["contributed_to"].values()) > s["n_methods"],
      f"{s['by_origin']}")
check("...and the difference between them is explained",
      "who was involved at all" in s["note"])

# The honest expectation: Andres originates biology, the assistant originates
# measurement design, the literature supplies statistics and vocabulary. If
# any of those went to zero the registry would be flattering someone.
check("no party originates zero methods",
      all(s["by_origin"][o] > 0 for o in ("andres", "claude", "literature")),
      f"{s['by_origin']}")

md = mp.methods_section(["taper_shape", "vulval_gap", "ordinal_guard"])
check("the manual section names each contributor", "Andres Vidal-Gadea" in md
      and "assistant (Claude)" in md and "published literature" in md)
check("...and reports what was verified", "Verified:" in md)
check("...with an attribution summary", "Attribution summary" in md)

try:
    mp.methods_section(["not_a_real_method"])
    check("an unattributed method is refused", False)
except mp.ProvenanceError as exc:
    check("an unattributed method is refused", True)
    check("...naming why it matters",
          "as though it came from nowhere" in str(exc))

bad = {"x": dict(title="t", module="m", origin="joint",
                 contribution={"claude": "only one"})}
check("a 'joint' method with one contributor is caught",
      any("marked joint" in p for p in mp.check_registry(bad)))
bad2 = {"y": dict(title="t", module="m", origin="andres",
                  contribution={"claude": "did it all"})}
check("an origin that contributed nothing is caught",
      any("contributed nothing" in p for p in mp.check_registry(bad2)))

# --- the bibliography -----------------------------------------------------
rc = mp.check_references()
check("every reference is well formed", not rc["problems"],
      "; ".join(rc["problems"][:2]) if rc["problems"]
      else f"{rc['n_references']} references")
check("every source has been retrieved rather than recalled",
      len(rc["retrieved"]) == rc["n_references"] and not rc["recalled"],
      f"{len(rc['retrieved'])} retrieved, {len(rc['recalled'])} recalled")
check("...every retrieved source carries the URL it came from",
      all(mp.REFERENCES[k]["url"] for k in rc["retrieved"]))
check("...and every recalled one, if any, says what must be verified",
      all(mp.REFERENCES[k].get("check") for k in rc["recalled"]))

# The sharper failure: a REAL reference attached to a claim it does not make.
# Worse than a missing citation, because the reference makes it look supported.
check("claims the sources did not confirm are recorded",
      len(rc["unconfirmed_claims"]) >= 2,
      f"{len(rc['unconfirmed_claims'])}: "
      f"{', '.join(rc['unconfirmed_claims'])}")
check("...and rendered under their own heading, not buried",
      "Claims the sources did NOT confirm" in mp.references_section())
check("...with the status line saying why they outrank a missing citation",
      "looks fully supported" in rc["publication_blocker"])
check("the '~70% of papers' figure is marked as unsourced, not repeated",
      "NO SOURCE FOR THAT FIGURE HAS BEEN FOUND"
      in mp.REFERENCES["klopfleisch_2013_scoring_review"]["unconfirmed"])
check("...and no method text still asserts it",
      not any("70%" in str(m.get("contribution", {}))
              for m in mp.METHODS.values()))
check("outstanding bibliographic details are listed separately",
      len(rc["details_still_to_check"]) >= 1,
      f"{', '.join(rc['details_still_to_check'])}")

check("a method claiming literature support must cite something",
      not [p for p in mp.check_registry() if "cites nothing" in p])
bad3 = {"z": dict(title="t", module="m", origin="literature",
                  contribution={"literature": "trust me"})}
check("...and an uncited literature claim is caught",
      any("cites nothing" in p for p in mp.check_registry(bad3)))
bad4 = {"w": dict(title="t", module="m", origin="claude",
                  contribution={"claude": "x"}, refs=["no_such_ref"])}
check("a dangling reference key is caught",
      any("unknown reference" in p for p in mp.check_registry(bad4)))

# --- the supervision record -----------------------------------------------
a = mp.contribution_audit()
check("corrections are recorded, not just contributed methods",
      a["corrections_total"] >= 8, f"{a['corrections_total']} corrections")
check("...including reversals of the direction of the work",
      a["reversals"] >= 3, f"{a['reversals']} reversals")
check("...each naming an artefact so the claim is checkable",
      all(c.get("evidence") for c in mp.CORRECTIONS))
check("...and each saying what the implementation had had first",
      all(c.get("assistant_had") and c.get("andres_said") and c.get("consequence")
          for c in mp.CORRECTIONS))
check("the audit states what the corrections establish",
      "not output that was accepted uncritically" in a["what_this_establishes"])
check("...and that it is checkable against the repository",
      "commit history" in a["auditable"])

# The record must cut both ways or it is advocacy, not an audit.
check("the record also holds cases where his expectation was revised",
      a["counter_record_entries"] >= 2, f"{a['counter_record_entries']} entries")
check("...and says why a one-sided record would not count",
      "advocacy" in a["not_one_sided"])
check("every counter-record entry names what the evidence showed",
      all(c.get("evidence_showed") and c.get("outcome")
          for c in mp.COUNTER_RECORD))

stmt = mp.contribution_statement()
check("the contributions section carries both halves",
      "Supervision record" in stmt and "the other way" in stmt)

# --- what a future reader needs -------------------------------------------
check("rejected alternatives are recorded with their numbers",
      a["rejected_alternatives"] >= 6
      and all(r.get("numbers") and r.get("why") for r in mp.REJECTED.values()),
      f"{a['rejected_alternatives']} recorded")
check("...each pointing at the method that superseded it",
      all(r["instead_of"] in mp.METHODS for r in mp.REJECTED.values()))
check("open problems name the data to work from",
      a["open_problems"] >= 5
      and all(p.get("data") and p.get("would_resolve")
              for p in mp.OPEN_PROBLEMS.values()),
      f"{a['open_problems']} open")

brief = mp.supersession_brief()
check("the brief warns that some rejects won on the obvious metric",
      "scored BETTER on the obvious metric" in brief)
check("...and lists the open problems with their data",
      "Open problems" in brief and "myocyte_vertices_head.npz" in brief)

# --- the human override ---------------------------------------------------
machine = {"head_end": 0, "confidence": 0.42, "low_confidence": True,
           "cues": {"taper": 0.3}, "why": "weak"}
ventral = {"ventral_sign": 1, "confidence": 0.5}

fixed, vflip = ht.override_head(machine, 1, ventral_call=ventral,
                                by="AVG", reason="pharynx clearly at the other end")
check("a hand correction sets the head", fixed["head_end"] == 1)
check("...at full confidence, marked as human",
      fixed["confidence"] == 1.0 and fixed["source"] == "human")
check("...applying to the whole track, not one frame",
      fixed["propagates_to_whole_track"] is True
      and "leave the rest of the recording behind" in fixed["note"])
check("...keeping what the machine said, and that they disagreed",
      fixed["machine_head_end"] == 0 and fixed["machine_confidence"] == 0.42
      and fixed["agreed_with_machine"] is False)
check("...and clearing the stale low-confidence warning",
      "low_confidence" not in fixed and "why" not in fixed)

check("the dorsoventral call is INVERTED with the head, not left to contradict it",
      vflip["ventral_sign"] == -1 and vflip["flipped_by_head_override"] is True,
      f"{ventral['ventral_sign']} -> {vflip['ventral_sign']}")

agreed, vsame = ht.override_head(machine, 0, ventral_call=ventral)
check("confirming the machine's answer does not flip anything",
      vsame["ventral_sign"] == 1 and vsame["flipped_by_head_override"] is False
      and agreed["agreed_with_machine"] is True)

alone, none = ht.override_head(machine, 1)
check("overriding without the dorsoventral call warns that it is now inverted",
      none is None and "now INVERTED" in alone["dorsoventral_not_updated"])

try:
    ht.override_head(machine, 2)
    check("an impossible end is refused", False)
except ht.HeadTailError as exc:
    check("an impossible end is refused", True, str(exc)[-24:])

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("METHOD_PROVENANCE_PASS")
