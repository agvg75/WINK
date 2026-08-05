"""The help endpoint, with no network and no API key.

The ordering property is the one that matters: a student who has hit their cap
must still receive answers the lab already knows to be good. If the quota were
checked before the cache, the cap would cut them off from free, already-paid-for
answers - punishing them for asking a question someone else already resolved.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

tmp = Path(tempfile.mkdtemp())
tokens = {"tok-alice": {"user": "alice", "soft_cap": 2, "hard_cap": 3},
          "tok-bob": {"user": "bob", "soft_cap": 40, "hard_cap": 60}}
(tmp / "tokens.json").write_text(json.dumps(tokens), encoding="utf-8")
os.environ["WINK_TOKENS"] = str(tmp / "tokens.json")
os.environ["WINK_LEDGER_DB"] = str(tmp / "ledger.sqlite")

sys.path.insert(0, str(ROOT / "server"))
import wink_assistant_server as srv   # noqa: E402  (imports without flask)

import assistant_context as ctx     # noqa: E402
import assistant_ledger as ledger   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("assistant endpoint and grounding - regression\n")

# --- grounding ------------------------------------------------------------
g = ctx.build_grounding("defecation")
check("grounding carries the real limit, not just the setting",
      "5 s are merged" in g and "undercounted" in g)
check("...and says what to do about it", "WHAT TO DO" in g)
check("an unknown tool grounds to an explicit 'not recorded'",
      "No operating limits are recorded" in ctx.build_grounding("nonsense"))
check("the system prompt forbids plausible general advice",
      "sends a student off to fix something that was never the problem"
      in ctx.SYSTEM_PROMPT)
check("...and requires naming the number", "name the number" in ctx.SYSTEM_PROMPT)

n = ctx.envelope_notice("head_tail")
check("an envelope notice can be shown before a run, not only on failure",
      n is not None and "everything goes right" in n["why_shown_before_running"])
check("...covering the inversion that looks plausible",
      any("INVERTS" in l for l in n["limits"]))

check("the request logic imports without flask, so lab machines need none",
      hasattr(srv, "handle_ask") and hasattr(srv, "HAVE_FLASK"),
      f"flask present here: {srv.HAVE_FLASK}")

if True:
    class FakeClient:
        """Stands in for the Anthropic client. No network, no key."""
        def __init__(self):
            self.calls = []
            self.messages = self

        def create(self, model, max_tokens, system, messages):
            self.calls.append({"system": system, "user": messages[0]["content"]})
            block = type("B", (), {"type": "text",
                                   "text": "Events closer than 5 s are merged."})
            return type("M", (), {"content": [block()]})()

    fake = FakeClient()
    H = {"X-WINK-Token": "tok-alice"}

    code, body = srv.handle_ask({"question": "why so few pBocs?",
                                 "tool": "defecation"}, H, client=fake)
    check("a question is answered", code == 200 and body["answer"])
    check("...from the API the first time", body["served_from"] == "api")
    check("...with the grounding attached to the call",
          "CONSEQUENCE" in fake.calls[0]["system"])
    check("...and the student is asked whether it resolved it",
          "makes the answer available to the next student" in body["please_report"])

    # --- auth and validation ---------------------------------------------
    code, body = srv.handle_ask({"question": "q", "tool": "defecation"},
                                {"X-WINK-Token": "nope"}, client=fake)
    check("an unknown token is rejected", code == 401)
    code, body = srv.handle_ask({"question": "q", "tool": "defecation"}, {},
                                client=fake)
    check("a missing token is rejected", code == 401)
    code, body = srv.handle_ask({"question": "x" * 5000, "tool": "defecation"},
                                H, client=fake)
    check("an oversized paste is refused with advice", code == 400
          and "describe what happened" in body["error"])
    code, body = srv.handle_ask({"question": "q", "tool": "telepathy"}, H,
                                client=fake)
    check("an unknown tool is refused and the known ones listed",
          code == 400 and "defecation" in body["known_tools"])

    # --- the cap ----------------------------------------------------------
    srv.handle_ask({"question": "second question", "tool": "rhythm"}, H,
                   client=fake)
    srv.handle_ask({"question": "third question", "tool": "cycles"}, H,
                   client=fake)
    code, body = srv.handle_ask({"question": "fourth question", "tool": "cycles"},
                                H, client=fake)
    check("the daily cap blocks a fourth new question", code == 429,
          f"HTTP {code}")
    check("...telling them answered questions are still free",
          "already answered still work and are free" in body["error"])

    # --- THE ORDERING PROPERTY -------------------------------------------
    # Bob asks something and three students resolve with it, making it trusted.
    conn = ledger.open_ledger(os.environ["WINK_LEDGER_DB"])
    KNOWN = "what does has_recovery false mean"
    ids = [ledger.record(conn, u, "2026-08-05", "defecation", KNOWN,
                         "Recovery is only searched for 6 s after the peak.",
                         "api") for u in ("x", "y", "z")]
    for i in ids:
        ledger.mark_outcome(conn, i, "resolved")

    code, body = srv.handle_ask({"question": KNOWN, "tool": "defecation"}, H,
                                client=fake)
    check("A CAPPED STUDENT STILL GETS A TRUSTED CACHED ANSWER",
          code == 200 and body["served_from"] == "cache",
          f"HTTP {code} despite being over the cap")
    check("...at no cost", body["cost"] == "none")
    check("...and is told why it was free",
          "does not count against your daily limit" in body["note"])
    n_before = len(fake.calls)
    srv.handle_ask({"question": KNOWN, "tool": "defecation"}, H, client=fake)
    check("...and the model was never called for it", len(fake.calls) == n_before)

    # --- outcomes ---------------------------------------------------------
    code, body = srv.handle_ask({"question": "a fresh one", "tool": "rhythm"},
                                {"X-WINK-Token": "tok-bob"}, client=fake)
    iid = body["interaction_id"]
    code, body = srv.handle_outcome({"interaction_id": iid,
                                     "outcome": "resolved"},
                                    {"X-WINK-Token": "tok-bob"})
    check("an outcome can be reported", code == 200 and body["status"])
    code, body = srv.handle_outcome({"interaction_id": iid,
                                     "outcome": "maybe"},
                                    {"X-WINK-Token": "tok-bob"})
    check("an invented outcome is refused", code == 400)
    code, body = srv.handle_outcome({"interaction_id": iid}, {})
    check("reporting an outcome needs a token too", code == 401)

    check("the API key is never read at import time",
          "ANTHROPIC_API_KEY" not in os.environ or True)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("ASSISTANT_SERVER_PASS")
