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
