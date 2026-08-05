"""The WINK help endpoint. Holds the API key; WINK never does.

Deployed on PythonAnywhere. See README_PYTHONANYWHERE.md for the twenty-minute
setup.

WHY THIS EXISTS AT ALL, rather than WINK calling Anthropic directly: a key
shipped inside an installer is a public key. Anyone who has WINK can read it
out of the bundle and spend the lab's balance, and rotating it means reissuing
the app to every student. Here the key sits in one place you control, student
access is a token you can revoke, and per-student caps are enforced before any
money is spent rather than discovered on a bill.

THE ORDER OF OPERATIONS MATTERS AND IS DELIBERATE:

    1. authenticate the token
    2. look for a trusted cached answer      <- free, and served first
    3. check the quota                       <- only now, if we must pay
    4. call the model with grounded context
    5. record the interaction

Checking the cache before the quota is the whole point. A student who has hit
their cap can still get every answer the lab already knows to be good, so the
cap slows new spending without cutting anyone off mid-analysis.
"""
from __future__ import annotations

import datetime as _dt
import hmac
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "app"))

import assistant_context as ctx                 # noqa: E402
import assistant_ledger as ledger               # noqa: E402

# Flask is only needed where this is SERVED. The request logic below is written
# with no Flask in it so it can be imported and tested on a lab machine, and so
# WINK itself never acquires a web-framework dependency it has no use for.
try:
    from flask import Flask, jsonify, request
    HAVE_FLASK = True
except ImportError:                                       # pragma: no cover
    HAVE_FLASK = False

MAX_QUESTION_CHARS = 1200
MODEL = "claude-haiku-4-5-20251001"    # fast and cheap; a help panel, not a paper
MAX_TOKENS = 400

app = Flask(__name__) if HAVE_FLASK else None

LEDGER_PATH = os.environ.get("WINK_LEDGER_DB", str(HERE / "wink_ledger.sqlite"))
TOKENS_PATH = os.environ.get("WINK_TOKENS", str(HERE / "tokens.json"))


def _today():
    return _dt.date.today().isoformat()


def load_tokens():
    """token -> {user, soft_cap, hard_cap}. Kept OUT of the repository.

    Read as utf-8-SIG, not utf-8. Notepad and PowerShell both write a byte-order
    mark on Windows, and plain utf-8 then fails on the very first character with
    a JSON error that names an encoding rather than the file - so the endpoint
    rejects every student and the message points at the wrong thing entirely.
    utf-8-sig reads files with and without the mark.
    """
    try:
        with open(TOKENS_PATH, encoding="utf-8-sig") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"{TOKENS_PATH} is not valid JSON: {exc}. Every request will be "
            f"rejected until this is fixed. A trailing comma after the last "
            f"entry is the usual cause.") from None


def authenticate(supplied):
    """Constant-time comparison against every known token.

    A plain dict lookup would be fine for correctness but leaks timing, and
    this endpoint is on the public internet. Comparing all of them costs
    nothing at ten students.
    """
    if not supplied:
        return None
    for token, info in load_tokens().items():
        if hmac.compare_digest(str(token), str(supplied)):
            return info
    return None


def _client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set on the server. The endpoint is "
            "running but cannot answer anything; set it in the PythonAnywhere "
            "web app configuration, never in this file.")
    import anthropic
    return anthropic.Anthropic(api_key=key)


def ask_model(question, tool, client=None):
    """One grounded call. `client` is injectable so tests never hit the network."""
    client = client or _client()
    grounding = ctx.build_grounding(tool)
    msg = client.messages.create(
        model=MODEL, max_tokens=MAX_TOKENS,
        system=ctx.SYSTEM_PROMPT + "\n\n# GROUNDING\n\n" + grounding,
        messages=[{"role": "user",
                   "content": f"[tool: {tool}]\n\n{question}"}])
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def handle_ask(payload, headers, client=None):
    """The whole request, with no Flask in it, so it can be tested directly."""
    info = authenticate(headers.get("X-WINK-Token"))
    if info is None:
        return 401, {"error": "Unrecognised or missing token. Ask Andres for "
                              "one; it identifies you for the daily cap."}

    question = str(payload.get("question", "")).strip()
    tool = str(payload.get("tool", "")).strip().lower()
    if not question:
        return 400, {"error": "No question supplied."}
    if len(question) > MAX_QUESTION_CHARS:
        return 400, {"error": f"Question is {len(question)} characters; the "
                              f"limit is {MAX_QUESTION_CHARS}. Long pastes are "
                              f"usually log files - describe what happened "
                              f"instead."}
    if tool not in ctx.known_tools():
        return 400, {"error": f"Unknown tool {tool!r}. Known: "
                              f"{', '.join(ctx.known_tools())}.",
                     "known_tools": ctx.known_tools()}

    conn = ledger.open_ledger(LEDGER_PATH)
    user, day = info["user"], _today()
    soft = int(info.get("soft_cap", 40))
    hard = int(info.get("hard_cap", 60))

    # 2. Cache FIRST, before the quota - a capped student still gets these.
    hit = ledger.lookup(conn, tool, question)
    if hit:
        iid = ledger.record(conn, user, day, tool, question, hit["answer"],
                            "cache", soft, hard)
        n = int(hit.get("resolved") or 0)
        return 200, {"answer": hit["answer"], "served_from": "cache",
                     "interaction_id": iid, "cost": "none",
                     "confirmed_by": n,
                     # The point of saying this is NOT that it was free. It is
                     # that a banked answer has been checked by people and a
                     # fresh one has not - which is the opposite of what a
                     # student would assume, since the fresh one looks more
                     # bespoke.
                     "provenance": (f"From the lab's answers - {n} "
                                    f"{'student has' if n == 1 else 'students have'} "
                                    f"confirmed this one."),
                     "note": ("Answered from the lab's ledger. It does not "
                              "count against your daily limit.")}

    # 3. Only now does anything cost money.
    q = ledger.check_quota(conn, user, day, soft, hard)
    if q["blocked"]:
        return 429, {"error": (f"You have used {q['api_calls']} of {hard} new "
                               f"questions today. Questions the lab has "
                               f"already answered still work and are free - "
                               f"only new ones are capped. Ask Andres to raise "
                               f"it if you are mid-analysis."),
                     "quota": q}

    try:
        answer = ask_model(question, tool, client=client)
    except Exception as exc:                              # pragma: no cover
        return 502, {"error": f"The assistant could not be reached: {exc}"}

    iid = ledger.record(conn, user, day, tool, question, answer, "api",
                        soft, hard)
    q_after = ledger.check_quota(conn, user, day, soft, hard)
    out = {"answer": answer, "served_from": "api", "interaction_id": iid,
           "confirmed_by": 0,
           "provenance": ("New answer - nobody has checked this one yet."),
           "please_report": ("Say whether this resolved it. That is what makes "
                             "the answer available to the next student, and "
                             "what removes it if it was wrong.")}
    # The remaining count is deliberately NOT sent unless the soft cap has been
    # passed. A running total teaches students that help is scarce and makes
    # them hesitate over questions they should ask, which costs far more than
    # the questions do. The cap exists to stop a runaway loop, and it should be
    # invisible until it is close to mattering.
    if q_after.get("over_soft"):
        out["quota_warning"] = q_after.get("warning")
        out["remaining_today"] = q_after.get("remaining")
    return 200, out


def handle_outcome(payload, headers):
    if authenticate(headers.get("X-WINK-Token")) is None:
        return 401, {"error": "Unrecognised or missing token."}
    try:
        conn = ledger.open_ledger(LEDGER_PATH)
        result = ledger.mark_outcome(conn, int(payload["interaction_id"]),
                                     str(payload["outcome"]))
    except (KeyError, ValueError, TypeError) as exc:
        return 400, {"error": f"Need interaction_id and outcome "
                              f"('resolved' or 'did_not_help'): {exc}"}
    except ledger.LedgerError as exc:
        return 400, {"error": str(exc)}
    return 200, result


if HAVE_FLASK:
    @app.route("/ask", methods=["POST"])
    def ask():
        code, body = handle_ask(request.get_json(silent=True) or {},
                                request.headers)
        return jsonify(body), code

    @app.route("/outcome", methods=["POST"])
    def outcome():
        code, body = handle_outcome(request.get_json(silent=True) or {},
                                    request.headers)
        return jsonify(body), code

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify(
            {"ok": True, "tools": ctx.known_tools(),
             "key_configured": bool(os.environ.get("ANTHROPIC_API_KEY")),
             "tokens_loaded": len(load_tokens())}), 200


def lan_address():
    """This machine's address on the lab network, for students to point at.

    Found by asking the OS which interface it would use to reach the outside
    world, rather than by reading the hostname - a lab PC usually has several
    addresses (VPN, virtual adapters, loopback) and the hostname resolves to
    whichever one Windows feels like, which is often not the one on the lab
    network.
    """
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))       # no packet is sent; this just routes
        return s.getsockname()[0]
    except OSError:                                       # pragma: no cover
        return "127.0.0.1"
    finally:
        s.close()


def main(port=5000):                                      # pragma: no cover
    if not HAVE_FLASK:
        raise SystemExit(
            "Flask is not installed in this runtime. Run:\n"
            "  %LOCALAPPDATA%\\LabTools\\.venv\\Scripts\\python.exe "
            "-m pip install flask anthropic")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit(
            "No ANTHROPIC_API_KEY. The endpoint would start and then fail on "
            "every question, which is harder to diagnose than not starting.\n"
            "Put the key in:  %LOCALAPPDATA%\\LabTools\\assistant_key.txt")
    tokens = load_tokens()
    if not tokens:
        raise SystemExit(
            f"No student tokens at {TOKENS_PATH}. Every request would be "
            f"rejected. Copy tokens.example.json to tokens.json and edit it.")

    ip = lan_address()
    print("=" * 62)
    print("  WINK assistant - running on this PC")
    print("=" * 62)
    print(f"  Students point WINK at:  http://{ip}:{port}")
    print(f"  Check it works:          http://{ip}:{port}/health")
    print(f"  Students with a token:   {len(tokens)}")
    print(f"  Question ledger:         {LEDGER_PATH}")
    print()
    print("  Leave this window open. Closing it stops the assistant.")
    print("  Only reachable from the campus network, by design.")
    print("=" * 62)
    # 0.0.0.0 so other machines on the lab network can reach it; on 127.0.0.1
    # it would work on this PC only and look like a firewall problem.
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":                                # pragma: no cover
    import argparse
    ap = argparse.ArgumentParser(description="WINK assistant endpoint")
    ap.add_argument("--port", type=int, default=5000)
    main(ap.parse_args().port)
