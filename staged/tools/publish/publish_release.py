"""Publish staged as a new versioned tree on L. One command.

    py tools\\publish\\publish_release.py --version 11.139
    py tools\\publish\\publish_release.py --version 11.139 --dry-run

WHAT THE NUMBER MEANS: MAJOR.COUNTER. 11.139 is the 139th release of the v11
line, NOT a decimal - the counter is unbounded and means nothing beyond
ordering. 11.9 precedes 11.10 precedes 11.139.

The MAJOR increments only on a COMPATIBILITY BREAK: sidecar or schema changes
old tools cannot read even with migration, or changes that invalidate
cross-version measurement comparability or invalidate pins. FEATURE SIZE
NEVER JUSTIFIES A MAJOR BUMP - a release may add a whole tool family and stay
on v11. We stay on v11 indefinitely; v12 is a deliberate, rare, announced
event.

Stated here rather than left to be inferred, because the obvious reading of
"11.139" is a decimal that ought to roll over eventually, and because under
the revert system a major bump is the one version change that can break a
student's pin - which is why it belongs to compatibility rather than to how
much work went in.

THE INVARIANT THIS SYSTEM IS BUILT ON, stated here because it is the thing
most likely to be optimised away later by someone who finds the extra click
annoying:

    AN UPDATE NEVER CHANGES THE RUNNING SESSION. IT CHANGES THE NEXT LAUNCH.

The Hub used to relaunch itself from a different tree mid-session and destroy
the original window. A person testing a fix could be moved onto other code by
accepting one dialog, and because the version string came from an install-time
file rather than the tree, nothing on screen changed to say so. Every
observation after that point was about the wrong build.

So: publishing writes a NEW tree and never touches a published one; the Hub
offers the update and asks the person to close and reopen. The extra click is
the implementation of the invariant, not a rough edge to smooth.

WHAT THIS REFUSES, AND WHY EACH ONE EXISTS
  dirty tree        the preview snapshot was cut from a dirty tree and
                    stamped with a commit that did not describe its contents
  unpushed commits  a published tree whose commit is not on the remote cannot
                    be recovered by anyone else
  stale stamp       a release_info.json in staged asserts a version staged
                    does not have; that file belongs only in published trees
  failing checks    a release nobody ran the suite against
  existing folder   never overwrite a published tree; students may be running
                    it right now

AND IT CHECKS ITS OWN OUTPUT. After copying, it imports running_version FROM
THE PUBLISHED TREE and requires a trustworthy, matching answer - the same
tripwire the Hub uses. A write that half succeeded must not be reported as a
release.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

STAGED = Path(__file__).resolve().parents[2]
PUBLISH_ROOT = Path(r"L:\10_AGVG LAB\Lab Tools")
FOLDER_TEMPLATE = "WINK_Lab_Tools_v{version}_Current_Files"
# Gates machines whose environment lacks a library a release needs. The
# updater swaps app files only and never runs pip, so a machine below
# this is sent to Setup_Lab_Tools.bat rather than half-updated.
MIN_RUNTIME_VERSION = "1.1.0"

# Long enough for the slowest honest suite - the drive-audit and
# census checks read from L over SMB - and short enough that a
# blocked GUI test is caught in minutes rather than never.
TEST_TIMEOUT_S = 180

SKIP_DIRS = {"__pycache__", ".git", ".venv", ".githooks", "node_modules",
             "NIKE_Review_Sessions", ".claude", ".pytest_cache"}
SKIP_SUFFIX = {".pyc", ".pyo"}
# Run artefacts and audit outputs. A student tree does not need the drive
# census, and one of these was 339 MB.
SKIP_GLOBS = ("tools/drive_audit/consolidation_plan_*.csv",
              "tools/confocal_census/*.csv",
              "tools/drive_audit/*.csv")


def run(args, **kwargs):
    return subprocess.run(args, cwd=str(STAGED), capture_output=True,
                          text=True, **kwargs)


def refuse(message):
    print(f"\nPUBLISH REFUSED\n\n  {message}\n")
    raise SystemExit(1)


# --------------------------------------------------------------- checks --
def check_clean_tree():
    dirty = run(["git", "status", "--porcelain"]).stdout.strip()
    if dirty:
        refuse("the working tree has uncommitted changes:\n\n"
               + "\n".join(f"    {line}" for line in dirty.splitlines()[:20])
               + "\n\n  A published tree is stamped with a commit hash. If the "
                 "tree is dirty\n  that hash does not describe what was "
                 "published, which is exactly how\n  the preview snapshot came "
                 "to claim a commit it did not contain.")


def check_pushed():
    run(["git", "fetch", "--quiet"])
    ahead = run(["git", "rev-list", "--count", "@{u}..HEAD"]).stdout.strip()
    if ahead and ahead != "0":
        refuse(f"{ahead} commit(s) are not pushed. A published tree whose "
               f"commit is only\n  on this machine cannot be recovered or "
               f"inspected by anyone else.")


def check_no_stale_stamp():
    stale = STAGED / "app" / "release_info.json"
    if stale.exists():
        refuse(f"{stale} exists.\n\n  A release stamp belongs only in a "
               f"PUBLISHED tree. In staged it asserts a\n  version this code "
               f"does not have, and that is what made a Hub running\n  from "
               f"staged display someone else's version number.\n\n  Delete it "
               f"and re-run. Publishing writes it into the output tree.")


def why_failed(result, last):
    """Say why a suite failed, which is rarely the last thing it printed.

    THIS EXISTS BECAUSE THE REPORT LIED. A suite died on an uncaught
    FileNotFoundError, and the refusal read:

        FAIL  test_magnet_dependency_guard.py    PASS  and pins it to 5.x

    The last STDOUT line was the final passing check; the traceback was on
    STDERR, which `stdout or stderr` never looks at once stdout is non-empty.
    A failure notice whose text reads "PASS" costs more than no notice: it
    invites the reader to dismiss the failure as a reporting quirk.

    Order: the exception, then a self-declared failure line, then the tail.
    """
    err = (result.stderr or "").strip().splitlines()
    if err:
        # The last stderr line of a traceback is the exception itself.
        # Carry the innermost frame too - "FileNotFoundError: ... x.json"
        # says what broke, the frame says who asked for it.
        frames = [ln.strip() for ln in err if ln.strip().startswith("File \"")]
        where = f"   ({frames[-1]})" if frames else ""
        return err[-1] + where
    declared = [ln.strip() for ln in (result.stdout or "").splitlines()
                if "FAILED:" in ln or ln.strip().startswith("FAIL")]
    if declared:
        return declared[-1]
    return last


def check_suite():
    """Run every test_*.py. A release nobody checked is not a release."""
    tests = sorted((STAGED / "tests").glob("test_*.py"))
    print(f"running {len(tests)} check suites")
    failures, skipped = [], []
    for path in tests:
        # A PER-TEST TIMEOUT, because one suite that never returns hangs the
        # whole release. test_cockpit_scrolling opens a Tk window and blocks
        # on its mainloop; run unattended it sat for nine minutes with the
        # publish waiting behind it and no indication of what was stuck.
        #
        # A timeout is a FAILURE, not a skip. A check that cannot complete
        # unattended cannot gate a release, and calling it green because it
        # never finished is how a suite stops meaning anything.
        # NOBODY IS WATCHING THIS RUN, so nothing in it may wait for a click.
        # The Hub's automatic update check ends in a modal wait_window; under
        # the check suite it hung the whole release twice, once for nine
        # minutes and once into a refusal, while presenting as a flaky
        # scrolling test.
        env = dict(os.environ, WINK_NO_UPDATE_PROMPT="1")
        try:
            result = subprocess.run([sys.executable, str(path)],
                                    cwd=str(STAGED), capture_output=True,
                                    text=True, timeout=TEST_TIMEOUT_S, env=env)
        except subprocess.TimeoutExpired:
            failures.append((path.name,
                             f"did not finish within {TEST_TIMEOUT_S}s - "
                             f"probably waiting for a window or input"))
            print(f"  HUNG  {path.name:<34} killed after {TEST_TIMEOUT_S}s")
            continue
        tail = (result.stdout or result.stderr).strip().splitlines()
        last = tail[-1] if tail else "(no output)"
        if result.returncode == 0:
            print(f"  ok    {path.name:<34} {last[:38]}")
        elif "ModuleNotFoundError" in (result.stderr or ""):
            # A suite needing something absent from THIS interpreter is not a
            # failing check - but it is not a passing one either, so it is
            # named rather than counted as green.
            module = re.search(r"No module named '([^']+)'", result.stderr)
            skipped.append((path.name, module.group(1) if module else "?"))
            print(f"  SKIP  {path.name:<34} needs "
                  f"{module.group(1) if module else '?'}")
        else:
            why = why_failed(result, last)
            failures.append((path.name, why))
            print(f"  FAIL  {path.name:<34} {why[:38]}")
    if failures:
        refuse("check suites failed:\n"
               + "\n".join(f"    {name}: {why}" for name, why in failures))
    if skipped:
        print(f"\n  {len(skipped)} suite(s) skipped for missing modules in "
              f"{Path(sys.executable).parent.name}:")
        for name, module in skipped:
            print(f"    {name} needs {module}")
        print("  These were NOT run. Publish continues, but they are unchecked.")
    return {"ran": len(tests) - len(skipped), "skipped": [s[0] for s in skipped]}


def check_conformance():
    """The standing scanner. Measured-values findings BLOCK, others report.

    A rule here exists because the failure it names already happened once.
    Publishing over a new measured-values finding ships a number somebody
    would report, which is the one category worth stopping a release for.
    """
    scanner = STAGED / "tools" / "conformance" / "scan.py"
    if not scanner.is_file():
        print("  conformance scanner not present; skipped")
        return
    result = subprocess.run([sys.executable, str(scanner), "--publish"],
                            cwd=str(STAGED), capture_output=True, text=True)
    print(result.stdout.rstrip())
    if result.returncode != 0:
        refuse("the conformance scanner found new measured-values "
               "issue(s).\n\n  Each one changes a number a person would "
               "report. Fix them, or record\n  a waiver with a reason in "
               "tools/conformance/waivers.json - a waiver\n  resurfaces "
               "automatically if the code it excused changes.")


# -------------------------------------------------------------- publish --
def next_version():
    """The highest published version, plus one minor step."""
    found = []
    for item in PUBLISH_ROOT.glob("*_Lab_Tools_v*_Current_Files"):
        match = re.search(r"_v([0-9.]+)_Current_Files$", item.name)
        if match and item.is_dir():
            found.append(match.group(1))
    if not found:
        return None
    def key(v):
        return tuple(int(p) for p in v.split(".") if p.isdigit())
    latest = max(found, key=key)
    parts = latest.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    return ".".join(parts), latest


def wanted_files():
    skip_globs = set()
    for pattern in SKIP_GLOBS:
        skip_globs |= {p.resolve() for p in STAGED.glob(pattern)}
    for item in STAGED.rglob("*"):
        if item.is_dir() or any(part in SKIP_DIRS for part in item.parts):
            continue
        if item.suffix.lower() in SKIP_SUFFIX:
            continue
        if item.resolve() in skip_globs:
            continue
        yield item


def verify_published(target, version):
    """Check the OUTPUT against the same tripwire the Hub uses.

    Imported from the published tree, not from staged, so this tests what was
    actually written rather than what was meant to be.
    """
    sys.path.insert(0, str(target / "app"))
    for stale in ("running_version",):
        sys.modules.pop(stale, None)
    try:
        import running_version
    except Exception as exc:                                 # noqa: BLE001
        return False, f"the published tree cannot report its own version: {exc}"
    finally:
        sys.path.pop(0)
    found = running_version.describe()
    if not found["trustworthy"]:
        return False, (f"the published tree reports {found['version']!r} "
                       f"({found['kind']}), which the Hub would display as "
                       f"unreliable: {found['note'][:120]}")
    if str(found["version"]) != str(version):
        return False, (f"the published tree reports version "
                       f"{found['version']!r}, not {version!r}")
    return True, f"published tree self-reports v{found['version']}"


def verify_manifest(manifest_path, target, version):
    """The manifest must name the same version AND the same tree.

    The Hub reads the manifest to decide what is available and the tree
    stamp to decide what it got. If those disagree the update button
    points somewhere other than what was published, and neither file is
    obviously wrong on its own - which is the MISMATCH tripwire again,
    one level up.
    """
    try:
        found = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, f"the manifest could not be read: {exc}"
    if str(found.get("app_version")) != str(version):
        return False, (f"manifest says {found.get('app_version')!r}, "
                       f"published {version!r}")
    if Path(found.get("published_tree", "")) != target:
        return False, (f"manifest points at {found.get('published_tree')}, "
                       f"not {target}")
    return True, f"manifest v{found['app_version']} -> {target.name}"


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", help="e.g. 11.138. Omit to use the next "
                                      "minor step above the newest published.")
    ap.add_argument("--note", default="", help="one-line change note")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-checks", action="store_true",
                    help="NOT for a real release; for testing this script.")
    args = ap.parse_args()

    print(f"publishing from {STAGED}")
    check_no_stale_stamp()
    check_clean_tree()
    check_pushed()

    commit = run(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    print(f"commit {commit} on {branch}, tree clean and pushed")

    suggestion = next_version()
    version = args.version
    if not version:
        if not suggestion:
            refuse("no published trees found, so the next version cannot be "
                   "inferred. Pass --version explicitly.")
        version, previous = suggestion
        print(f"newest published is v{previous}; using v{version}")
    if not re.fullmatch(r"[0-9]+(\.[0-9]+)+", version):
        refuse(f"{version!r} is not a version number like 11.138.")

    target = PUBLISH_ROOT / FOLDER_TEMPLATE.format(version=version)
    if target.exists():
        refuse(f"{target}\n  already exists. A published tree is never "
               f"overwritten - students may be\n  running it right now. Use "
               f"the next version number.")

    checks = {"ran": 0, "skipped": []}
    if not args.skip_checks:
        checks = check_suite()
        check_conformance()

    files = list(wanted_files())
    total = sum(f.stat().st_size for f in files)
    print(f"\n{len(files):,} files, {total / 1e6:.1f} MB -> {target}")
    if args.dry_run:
        print("\nDRY RUN. Nothing was written.")
        return 0

    target.mkdir(parents=True)
    for item in files:
        out = target / item.relative_to(STAGED)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, out)

    stamp = {
        "app_version": version,
        "commit": commit,
        "published_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "published_by": os.environ.get("USERNAME", "?"),
        "note": args.note,
        "checks_ran": checks["ran"],
        "checks_skipped": checks["skipped"],
        "invariant": ("An update never changes the running session, only the "
                      "next launch."),
    }
    (target / "app" / "release_info.json").write_text(
        json.dumps(stamp, indent=2), encoding="utf-8")
    (target / "app" / "BUILD_COMMIT.txt").write_text(commit, encoding="utf-8")

    # ONE WRITER. The Hub updater reads update_manifest.json; the tree
    # carries release_info.json. Two scripts writing those separately is
    # how they come to describe different things - BUILD_APP_UPDATE.ps1
    # was a hand-run script with no relationship to the commit at all,
    # and its changelog drifted three releases behind before anyone
    # noticed. Both files are now generated here, from the same data, in
    # the same second.
    manifest = {
        "app_version": version,
        "commit": commit,
        "min_runtime_version": MIN_RUNTIME_VERSION,
        "published_utc": stamp["published_utc"],
        "published_tree": str(target),
        "changelog": args.note or f"v{version}",
    }
    manifest_path = PUBLISH_ROOT / "update_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2),
                             encoding="utf-8")

    ok, message = verify_manifest(manifest_path, target, version)
    print(f"verifying the manifest agrees with the tree: {message}")
    if not ok:
        refuse("the manifest and the published tree disagree.\n\n  "
               + message
               + "\n\n  The update button would send students to something "
                 "other than\n  what was just published.")

    ok, message = verify_published(target, version)
    print(f"\nverifying the published tree: {message}")
    if not ok:
        refuse(f"the tree was written but does NOT verify.\n\n  {message}\n\n"
               f"  It is left at {target} for inspection. Do not point "
               f"students at it.")

    print(f"\nPUBLISHED v{version}")
    print(f"  {target}")
    print(f"  commit {commit}, {len(files):,} files")
    print(f"\n  Students press the update button in the Hub. Their running "
          f"session is\n  unaffected; the new version applies at their next "
          f"launch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
