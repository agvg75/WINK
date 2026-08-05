"""Add a student to the assistant, and produce the one file they need.

    python issue_student.py kiley ella mackenzie
    python issue_student.py --list
    python issue_student.py --revoke ella
    python issue_student.py --cap kiley 80 120

Two files change and they live in different places for a reason. The TOKEN goes
into the lab PC's tokens.json, which is the credential list and never leaves
that machine. The student gets a CLIENT CONFIG holding the endpoint address and
their own token only - so handing it over shares one person's access, not
everybody's.

ONE TOKEN PER PERSON, NEVER SHARED. Two people on one token makes the daily cap
and the usage report meaningless, and revoking one revokes both.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path

LT = Path(os.environ.get("LOCALAPPDATA", ".")) / "LabTools"
TOKENS = Path(os.environ.get("WINK_TOKENS", LT / "tokens.json"))
HANDOUT = LT / "student_configs"

DEFAULT_SOFT, DEFAULT_HARD = 40, 60


def _read():
    if not TOKENS.exists():
        return {}
    # utf-8-sig: Notepad and PowerShell both write a byte-order mark, and plain
    # utf-8 fails on the first character with an error naming an encoding.
    return json.loads(TOKENS.read_text(encoding="utf-8-sig"))


def _write(d):
    TOKENS.parent.mkdir(parents=True, exist_ok=True)
    TOKENS.write_text(json.dumps(d, indent=2), encoding="utf-8")


def endpoint_guess():
    """This PC's LAN address, which is what students must point at."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return f"http://{s.getsockname()[0]}:5000"
    except OSError:                                       # pragma: no cover
        return "http://127.0.0.1:5000"
    finally:
        s.close()


def add(names, soft=DEFAULT_SOFT, hard=DEFAULT_HARD, endpoint=None):
    tokens = _read()
    endpoint = endpoint or endpoint_guess()
    HANDOUT.mkdir(parents=True, exist_ok=True)
    made = []
    for name in names:
        name = name.strip().lower()
        existing = [t for t, v in tokens.items() if v.get("user") == name]
        if existing:
            print(f"  {name}: already has a token - leaving it alone. "
                  f"Use --revoke first if you mean to reissue.")
            token = existing[0]
        else:
            token = "wink-" + secrets.token_hex(6)
            tokens[token] = {"user": name, "soft_cap": soft, "hard_cap": hard}
            print(f"  {name}: token issued")
        cfg = HANDOUT / f"{name}_wink_assistant_client.json"
        cfg.write_text(json.dumps({"endpoint": endpoint, "token": token},
                                  indent=2), encoding="utf-8")
        made.append((name, cfg))
    _write(tokens)
    return made


def revoke(name):
    tokens = _read()
    gone = [t for t, v in tokens.items() if v.get("user") == name.strip().lower()]
    for t in gone:
        del tokens[t]
    _write(tokens)
    stale = HANDOUT / f"{name.strip().lower()}_wink_assistant_client.json"
    if stale.exists():
        stale.unlink()
    return len(gone)


def set_cap(name, soft, hard):
    tokens = _read()
    n = 0
    for t, v in tokens.items():
        if v.get("user") == name.strip().lower():
            v["soft_cap"], v["hard_cap"] = int(soft), int(hard)
            n += 1
    _write(tokens)
    return n


def listing():
    tokens = _read()
    if not tokens:
        print("No tokens yet.")
        return
    print(f"{'student':<14}{'soft':>6}{'hard':>6}   token")
    for t, v in sorted(tokens.items(), key=lambda kv: kv[1].get("user", "")):
        print(f"{v.get('user',''):<14}{v.get('soft_cap',''):>6}"
              f"{v.get('hard_cap',''):>6}   {t}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="*", help="student names to add")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--revoke", metavar="NAME")
    ap.add_argument("--cap", nargs=3, metavar=("NAME", "SOFT", "HARD"))
    ap.add_argument("--endpoint", help="override the address students point at")
    ap.add_argument("--soft", type=int, default=DEFAULT_SOFT)
    ap.add_argument("--hard", type=int, default=DEFAULT_HARD)
    a = ap.parse_args(argv)

    if a.list:
        listing()
        return 0
    if a.revoke:
        n = revoke(a.revoke)
        print(f"Revoked {n} token(s) for {a.revoke}. Restart the assistant to "
              f"apply." if n else f"No token found for {a.revoke}.")
        return 0
    if a.cap:
        n = set_cap(a.cap[0], a.cap[1], a.cap[2])
        print(f"Updated caps for {a.cap[0]}." if n
              else f"No token found for {a.cap[0]}.")
        return 0
    if not a.names:
        ap.print_help()
        return 1

    made = add(a.names, a.soft, a.hard, a.endpoint)
    print(f"\nTokens file: {TOKENS}")
    print(f"Endpoint    : {a.endpoint or endpoint_guess()}")
    print("\nGive each student ONLY their own file, and have them save it as:")
    print(r"    %LOCALAPPDATA%\LabTools\wink_assistant_client.json")
    for name, cfg in made:
        print(f"    {name:<12} {cfg}")
    print("\nRestart the assistant so it picks up the new tokens.")
    print("Send each file to that student only - the tokens file itself is a "
          "credential list for everyone and must not be shared.")
    return 0


if __name__ == "__main__":                                # pragma: no cover
    sys.exit(main())
