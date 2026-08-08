"""What this person ran, which version, and whether it survived.

Publish stage 5. Every tool launch appends (user, module, effective version,
machine, timestamp, outcome) to that user's own settings, and the version
picker annotates each version from THAT USER'S history.

WHY PER USER, AND WHY IT DECIDES THE REVERT DEFAULT. "Revert" defaulting to
the previous version number is nearly useless: the previous number may be one
this student never ran, or one that crashed on their machine. **The default is
the most recent version with a CLEAN session for this user** - the last build
that actually worked for them, which is the only version anyone reverting
actually wants.

PINS ARE PER USER, PER TOOL. One student pinning the egg counter affects
nobody else. That is what makes reverting cheap enough to do without asking
permission, and cheap reverting is the safety net that makes publishing to
everyone affordable in the first place.

HOW AN OUTCOME IS KNOWN. The Hub cannot record it: the tool runs in a separate
process and the Hub is not waiting on it. So the CHILD records its own fate -
`arrive()` on start, then the crash handler writes `crash` and an atexit hook
writes `clean-exit`. A launch that records neither was killed or never
finished, and stays `unknown` rather than being counted as clean.

NEVER LET BOOKKEEPING KILL A TOOL. Every write here is best-effort. A student
whose analysis dies because a history file was locked would be a far worse
defect than the one this module exists to fix.
"""
from __future__ import annotations

import atexit
import json
import os
import platform
import uuid
from datetime import datetime, timezone
from pathlib import Path

ENV_LAUNCH = "WINK_LAUNCH_ID"
ENV_MODULE = "WINK_MODULE"
ENV_VERSION = "WINK_EFFECTIVE_VERSION"

CLEAN, CRASH, UNKNOWN = "clean-exit", "crash", "unknown"


def user_root():
    """Per-user, per-machine. Shares the location run_feedback already uses."""
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "AGVGLab" / "quality"
    return Path.home() / ".agvg_lab_tools" / "quality"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_lines(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            # A torn final line from a killed process is not a reason to lose
            # the history above it.
            continue
    return out


class LaunchHistory:
    def __init__(self, root=None):
        self.root = Path(root) if root else user_root()
        self.log = self.root / "launch_history.jsonl"
        self.pins = self.root / "version_pins.json"

    # ------------------------------------------------------------ writing
    def _append(self, record):
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with open(self.log, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
            return True
        except OSError:
            return False

    def record_launch(self, module, version, launch_id=None, tree="",
                      tree_version=""):
        """Called by the launcher. Returns the launch id to hand the child.

        THE ID MUST BE UNIQUE PER LAUNCH, not per second. The first version
        built it from pid + timestamp, so two tools started from the same Hub
        inside one second - a double-click, or opening two tools in a row -
        shared an id, and their outcomes overwrote each other. A crash in one
        then marked the other crashed.
        """
        launch_id = launch_id or f"{os.getpid()}-{uuid.uuid4().hex[:12]}"
        self._append({"event": "launch", "id": launch_id, "module": module,
                      # TWO VERSIONS, AND THEY ARE NOT THE SAME FACT.
                      # `version` is the module's effective version - what the
                      # picker lists. `tree_version` is the release the
                      # session actually ran from. Seven consecutive releases
                      # can share one effective version for a module, so a
                      # clean session on effective 11.130 may have happened on
                      # tree 11.133, against six releases' worth of different
                      # shared code. Recording only the first would quietly
                      # claim the clean session belonged to a tree nobody ran.
                      "version": version, "tree_version": str(tree_version),
                      "tree": str(tree),
                      "user": os.environ.get("USERNAME", "?"),
                      "machine": platform.node(), "when": _now()})
        return launch_id

    def record_outcome(self, launch_id, outcome, detail=""):
        if not launch_id:
            return False
        return self._append({"event": "outcome", "id": launch_id,
                             "outcome": outcome, "detail": detail[:500],
                             "when": _now()})

    # ------------------------------------------------------------ reading
    def sessions(self, module=None):
        """[(module, version, when, outcome)] oldest first.

        A launch with no matching outcome is UNKNOWN, never clean. The whole
        point of the revert default is that it names a version observed to
        work; counting "we never heard back" as success would quietly hand
        someone the build that hung.
        """
        outcomes = {}
        launches = []
        for row in _read_lines(self.log):
            if row.get("event") == "outcome":
                key, outcome = row.get("id"), row.get("outcome", UNKNOWN)
                # A CRASH IS STICKY AND OUTRANKS A LATER CLEAN EXIT. Ordering
                # here is not a detail: the crash handler runs first and the
                # atexit hook runs after it, so "last write wins" would record
                # every crashed session as clean - the exact opposite of the
                # truth, in the field that decides what revert offers.
                if outcomes.get(key) == CRASH:
                    continue
                outcomes[key] = outcome
            elif row.get("event") == "launch":
                launches.append(row)
        out = []
        for row in launches:
            if module and row.get("module") != module:
                continue
            out.append((row.get("module", ""), row.get("version", ""),
                        row.get("when", ""),
                        outcomes.get(row.get("id"), UNKNOWN)))
        return out

    def annotate(self, module, versions, current=None):
        """{version: note} from THIS user's history, for the picker."""
        history = self.sessions(module)
        last_used, last_clean = {}, {}
        for _mod, version, when, outcome in history:
            if version and when > last_used.get(version, ""):
                last_used[version] = when
            if outcome == CLEAN and when > last_clean.get(version, ""):
                last_clean[version] = when
        notes = {}
        for version in versions:
            if version == current:
                notes[version] = "current"
            elif version in last_clean:
                notes[version] = f"last clean session {last_clean[version][:10]}"
            elif version in last_used:
                notes[version] = (f"used {last_used[version][:10]}, "
                                  f"no clean session")
            else:
                notes[version] = "never used by you"
        return notes

    def revert_default(self, module, versions, current=None):
        """The most recent version with a CLEAN session for THIS user.

        Not the previous number. Returns None when this user has no clean
        session on any offered version - in which case the picker must ask
        rather than invent a recommendation.
        """
        clean = {}
        for _mod, version, when, outcome in self.sessions(module):
            if outcome == CLEAN and version != current:
                clean[version] = max(clean.get(version, ""), when)
        candidates = [v for v in versions if v in clean]
        if not candidates:
            return None
        return max(candidates, key=lambda v: clean[v])

    # -------------------------------------------------------------- pins
    def _pins(self):
        try:
            return json.loads(self.pins.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def pin(self, module, version):
        data = self._pins()
        data[module] = version
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            self.pins.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return True
        except OSError:
            return False

    def unpin(self, module):
        data = self._pins()
        if data.pop(module, None) is None:
            return False
        try:
            self.pins.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return True
        except OSError:
            return False

    def pinned(self, module):
        return self._pins().get(module)


# ------------------------------------------------- the child's own reporting

_crashed = False


def arrive(history=None):
    """Called by a launched tool. Registers a clean exit unless it crashes."""
    launch_id = os.environ.get(ENV_LAUNCH)
    if not launch_id:
        return None
    store = history or LaunchHistory()

    def _clean():
        # A crashing process still runs its atexit hooks. Without this guard
        # the hook would file a clean exit moments after the crash handler
        # reported the crash.
        if not _crashed:
            store.record_outcome(launch_id, CLEAN)

    atexit.register(_clean)
    return launch_id


def record_crash(detail="", history=None):
    """Called from the crash handler in the launched process."""
    global _crashed
    _crashed = True
    launch_id = os.environ.get(ENV_LAUNCH)
    if not launch_id:
        return False
    return (history or LaunchHistory()).record_outcome(
        launch_id, CRASH, detail)


def launch_environment(module, version, launch_id, base=None):
    """Environment for the child so it can report its own outcome."""
    env = dict(base if base is not None else os.environ)
    env[ENV_LAUNCH] = str(launch_id)
    env[ENV_MODULE] = str(module)
    env[ENV_VERSION] = str(version)
    return env
