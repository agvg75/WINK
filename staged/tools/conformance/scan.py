"""Standing conformance scanner. Reports and proposes; never applies.

    py tools\\conformance\\scan.py              full scan
    py tools\\conformance\\scan.py --new-only   only findings not yet known
    py tools\\conformance\\scan.py --publish    exit non-zero on a blocker

PROPOSE-ONLY, ABSOLUTELY. This may draft a patch into the findings log as a
suggestion. It never edits a source file. A scanner that fixes things is a
scanner nobody reads, and the fix that matters is usually not the mechanical
one - the acceptance band did not need a different number, it needed a
different derivation.

FINDINGS ARE FINGERPRINTED ON CONTENT, NOT LINE NUMBER. Adding an import at
the top of a file must not re-report everything below it as new. The
fingerprint covers rule, file and the matched text; the surrounding line is
hashed separately so a WAIVER RESURFACES when the code it excused changes.
A waiver is a judgement about specific code, and it expires when that code
does.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGED = HERE.parents[1]
sys.path.insert(0, str(HERE))

import rules as ruleset   # noqa: E402

FINDINGS_LOG = HERE / "findings.jsonl"
WAIVERS = HERE / "waivers.json"
CONTEXT_LINES = 6


def fingerprint(rule_id, path, matched):
    key = f"{rule_id}|{path}|{matched.strip()}"
    return hashlib.blake2b(key.encode("utf-8"), digest_size=8).hexdigest()


def code_hash(line):
    return hashlib.blake2b(line.strip().encode("utf-8"),
                           digest_size=6).hexdigest()


def load_waivers():
    if not WAIVERS.is_file():
        return {}
    try:
        return {w["fingerprint"]: w
                for w in json.loads(WAIVERS.read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return {}


def known_fingerprints():
    seen = set()
    if FINDINGS_LOG.is_file():
        for line in FINDINGS_LOG.read_text(encoding="utf-8").splitlines():
            try:
                seen.add(json.loads(line)["fingerprint"])
            except (ValueError, KeyError):
                continue
    return seen


def files_for(rule, root):
    for pattern in rule["files"]:
        for path in root.glob(pattern):
            if path.is_file() and "__pycache__" not in path.parts:
                yield path


def exempt(context, patterns):
    """Whole words only.

    Substring matching excused the very things the rules name: "underived"
    contains "derived", so `def underived_gate` exempted itself from the
    underived-constant rule, and `def declared_depth` exempted itself from
    declared-not-measured. A rule a violation can satisfy by NAMING itself is
    worse than no rule. Found by the self-test on its first firing.
    """
    for pattern in patterns:
        anchored = pattern if pattern.startswith(r"\b") else r"\b" + pattern
        if re.search(anchored, context, re.IGNORECASE):
            return True
    return False


def scan(root=STAGED):
    waivers = load_waivers()
    findings = []
    for rule in ruleset.RULES:
        if rule.get("retired"):
            continue
        compiled = [re.compile(p, re.IGNORECASE | re.MULTILINE)
                    for p in rule["patterns"]]
        for path in files_for(rule, root):
            # The scanner's own rules file quotes every pattern it looks for.
            # The scanner's own files quote every pattern they look for,
            # and the FIXTURES exist precisely to violate every rule -
            # scanning them reports 10 findings that are the self-test
            # working correctly. They are excluded here and exercised
            # only by pointing --root at them.
            if path.resolve() in (Path(__file__).resolve(),
                                  (HERE / "rules.py").resolve()):
                continue
            # ...unless the scan is AIMED at them. The first version of this
            # exclusion also silenced the self-test, which is the one place
            # the fixtures must be read: 9 of 9 rules went to 0 of 9 and the
            # scanner reported a clean tree either way.
            fixtures = (HERE / "fixtures").resolve()
            aimed_at_fixtures = (root.resolve() == fixtures
                                 or fixtures in root.resolve().parents)
            if not aimed_at_fixtures and fixtures in path.resolve().parents:
                continue
            try:
                lines = path.read_text(encoding="utf-8",
                                       errors="replace").splitlines()
            except OSError:
                continue
            text = "\n".join(lines)
            starts, offset = [], 0
            for line in lines:
                starts.append(offset)
                offset += len(line) + 1
            # A STRUCTURAL RULE SEES SHAPE, WHICH A REGEX CANNOT. Its hits
            # are funnelled through the same exemption, fingerprint and
            # waiver path as pattern hits - a second reporting route would
            # be a second place for a waiver to be forgotten.
            structural = []
            checker = rule.get("check")
            if checker is not None:
                try:
                    structural = checker(path, text)
                except Exception:                            # noqa: BLE001
                    structural = []
            for index, matched in structural:
                line = lines[index] if index < len(lines) else ""
                lo = max(0, index - CONTEXT_LINES)
                context = "\n".join(lines[lo:index + CONTEXT_LINES])
                if exempt(context, rule.get("exempt_context", ())):
                    continue
                rel = str(path.relative_to(root)).replace("\\", "/")
                mark = fingerprint(rule["id"], rel, matched)
                waiver = waivers.get(mark)
                current = code_hash(line)
                if waiver and waiver.get("code_hash") == current:
                    continue
                findings.append({
                    "fingerprint": mark,
                    "rule": rule["id"],
                    "rank": rule["rank"],
                    "file": rel,
                    "line": index + 1,
                    "matched": matched[:120],
                    "evidence": line.strip()[:160],
                    "code_hash": current,
                    "incident": rule["incident"],
                    "summary": rule["summary"],
                    "waiver_expired": bool(
                        waiver and waiver.get("code_hash") != current),
                })
            for pattern in compiled:
                # SEARCHED OVER THE WHOLE FILE, not line by line. The first
                # version iterated lines, so a MULTILINE pattern - the
                # try/except ImportError shape that runtime-parity looks for -
                # could never match however correct it was. Found by the
                # self-test on its first firing: 4 of 9 planted violations.
                for match in pattern.finditer(text):
                    index = 0
                    for position, start in enumerate(starts):
                        if start <= match.start():
                            index = position
                        else:
                            break
                    line = lines[index] if index < len(lines) else ""
                    lo = max(0, index - CONTEXT_LINES)
                    context = "\n".join(lines[lo:index + CONTEXT_LINES])
                    if exempt(context, rule.get("exempt_context", ())):
                        continue
                    rel = str(path.relative_to(root)).replace("\\", "/")
                    mark = fingerprint(rule["id"], rel, match.group(0))
                    waiver = waivers.get(mark)
                    current = code_hash(line)
                    if waiver and waiver.get("code_hash") == current:
                        continue
                    findings.append({
                        "fingerprint": mark,
                        "rule": rule["id"],
                        "rank": rule["rank"],
                        "file": rel,
                        "line": index + 1,
                        "matched": match.group(0).strip()[:120],
                        "evidence": line.strip()[:160],
                        "code_hash": current,
                        "incident": rule["incident"],
                        "summary": rule["summary"],
                        "waiver_expired": bool(
                            waiver and waiver.get("code_hash") != current),
                    })
    return findings


RANK_ORDER = {"measured-values": 0, "gating": 1, "cosmetic": 2}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--new-only", action="store_true")
    ap.add_argument("--publish", action="store_true",
                    help="exit non-zero if any measured-values finding is new")
    ap.add_argument("--record", action="store_true",
                    help="append findings to the log so they become known")
    ap.add_argument("--root", default=str(STAGED))
    args = ap.parse_args()

    findings = scan(Path(args.root))
    known = known_fingerprints()
    for item in findings:
        item["new"] = item["fingerprint"] not in known
    if args.new_only:
        findings = [f for f in findings if f["new"]]
    findings.sort(key=lambda f: (RANK_ORDER.get(f["rank"], 9), f["file"],
                                 f["line"]))

    counts = {}
    for item in findings:
        counts[item["rank"]] = counts.get(item["rank"], 0) + 1
    print(f"scanned {args.root}")
    print(f"{len(findings)} finding(s): "
          + ", ".join(f"{n} {rank}" for rank, n in sorted(
              counts.items(), key=lambda kv: RANK_ORDER.get(kv[0], 9)))
          + ("" if findings else "none"))

    current_rank = None
    for item in findings:
        if item["rank"] != current_rank:
            current_rank = item["rank"]
            print(f"\n=== {current_rank.upper()} "
                  + ("(BLOCKS PUBLISH)" if current_rank
                     == ruleset.BLOCKING_RANK else "(reported)"))
        flag = "NEW " if item["new"] else "    "
        expired = "  [WAIVER EXPIRED]" if item["waiver_expired"] else ""
        print(f"  {flag}{item['rule']:<24} {item['file']}:{item['line']}"
              f"{expired}")
        print(f"       {item['evidence'][:104]}")

    if args.record and findings:
        with open(FINDINGS_LOG, "a", encoding="utf-8") as handle:
            for item in findings:
                if item["new"]:
                    handle.write(json.dumps(
                        {**item, "first_seen": datetime.now(timezone.utc)
                         .isoformat(timespec="seconds")}) + "\n")
        print(f"\nrecorded {sum(1 for f in findings if f['new'])} new "
              f"finding(s) to {FINDINGS_LOG.name}")

    if args.publish:
        blockers = [f for f in findings
                    if f["rank"] == ruleset.BLOCKING_RANK and f["new"]]
        if blockers:
            print(f"\nPUBLISH BLOCKED by {len(blockers)} new "
                  f"measured-values finding(s).")
            print("Each one changes a number a person would report. Fix, or "
                  "record a waiver with a reason.")
            return 1
        print("\nno new measured-values findings; publish may proceed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
