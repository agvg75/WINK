"""What version is ACTUALLY running, derived from the tree, never from a file
that can disagree with it.

THE DEFECT THIS REPLACES. The Hub read its version from a versions JSON
written at install time. A Hub started from `staged` therefore displayed
"WINK v11.137" - the last thing installed - while running entirely different
code. Measured 7 Aug 2026: the one indicator anyone would check was the one
that could not detect the problem, and answering "what am I running" required
a WMI query against the process command line.

Everything here is derived from the location of THIS FILE. A version that is
read from somewhere else is a claim; a version read from the tree is a fact.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
TREE = APP_DIR.parent

# WINK_Lab_Tools_v11.138_Current_Files
PUBLISHED_NAME = re.compile(
    r"^(?:WINK|NIKE)_Lab_Tools_v(?P<version>[0-9.]+)_Current_Files$",
    re.IGNORECASE)


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def running_tree():
    """The directory the running code lives in."""
    return TREE


def describe():
    """Everything known about the running tree, from the tree itself.

    `version` is what a person should be shown. `kind` says how much that
    version can be trusted:

        published    a versioned release folder with a matching stamp
        preview      a snapshot cut from a known commit
        working      an editable tree; the commit is whatever was last built
        unknown      none of the above, and it says so rather than guessing
    """
    info = _read_json(APP_DIR / "release_info.json")
    commit = ""
    commit_file = APP_DIR / "BUILD_COMMIT.txt"
    if commit_file.is_file():
        try:
            commit = commit_file.read_text(encoding="utf-8").strip()
        except OSError:
            commit = ""

    folder = PUBLISHED_NAME.match(TREE.name)
    stamped = str(info.get("app_version", "")).strip()

    if folder and stamped:
        # BOTH must agree. A folder named v11.138 holding a v11.137 stamp is
        # a mis-published tree, and saying so is more useful than picking one.
        if folder.group("version") != stamped:
            return {"version": f"MISMATCH {folder.group('version')} vs "
                               f"{stamped}", "kind": "unknown",
                    "commit": commit, "tree": str(TREE),
                    "trustworthy": False,
                    "note": ("The folder name and the release stamp disagree. "
                             "This tree was published incorrectly and its "
                             "version cannot be relied on.")}
        return {"version": stamped, "kind": "published", "commit": commit,
                "tree": str(TREE), "trustworthy": True,
                "note": info.get("changelog", "")}

    if stamped:
        # A STAMP IN A TREE THAT IS NOT A PUBLISHED FOLDER IS A LEFTOVER, NOT
        # A VERSION. `staged` carries a release_info.json from whenever it was
        # last built, and trusting it is exactly the original defect: this
        # function's first draft reported `staged` as "11.137, published,
        # trustworthy" while running uncommitted code. The folder name is the
        # thing publishing controls, so the folder name decides.
        return {"version": f"{TREE.name} (stale stamp says {stamped})",
                "kind": "working", "commit": commit, "tree": str(TREE),
                "trustworthy": False,
                "note": (f"This tree is not a published release folder, so "
                         f"the {stamped} stamp inside it is left over from an "
                         f"earlier build and does not describe this code.")}

    if commit:
        return {"version": f"PREVIEW {commit}", "kind": "preview",
                "commit": commit, "tree": str(TREE), "trustworthy": True,
                "note": "Preview build; numbers may change without notice."}

    return {"version": f"working tree ({TREE.name})", "kind": "working",
            "commit": "", "tree": str(TREE), "trustworthy": False,
            "note": ("Running from an editable tree, not a published "
                     "release. The code here may differ from anything ever "
                     "given to a student.")}


def version_string():
    """One line naming the version AND how far it can be trusted."""
    found = describe()
    if found["kind"] == "published":
        return f"v{found['version']}"
    if found["kind"] == "preview":
        return found["version"]
    return found["version"]


def title_suffix():
    """What to append to a window title so the tree is never ambiguous."""
    found = describe()
    if found["kind"] == "published":
        return f"v{found['version']}"
    if found["kind"] == "preview":
        return f"{found['version']}  [PREVIEW]"
    if found["kind"] == "working":
        return f"{found['version']}  [NOT A RELEASE]"
    return f"{found['version']}  [VERSION UNRELIABLE]"
