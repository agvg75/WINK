"""Per-module effective versions: which release last changed THIS tool.

    py app\\module_versions.py                     the module x version table
    py app\\module_versions.py --module "Egg counter"
    py app\\module_versions.py --build-index       hash the published trees

EFFECTIVE VERSION = the last published version whose tree changed any file
this module actually depends on.

WHY THAT NUMBER AND NOT THE RELEASE NUMBER. A student on v11.138 asking "did
the egg counter change?" is not helped by "you are on 11.138" - twenty-one
releases went by and perhaps two touched their tool. The useful list is the
versions that COULD have changed this tool's behaviour, which is usually a
handful. A list of every release is noise, and noise is what makes a version
picker go unread.

WHY THE PUBLISHED TREES AND NOT git diff. Attribution needs a per-version file
list. git would give one cheaply, and it was the first design. Then the trees
were surveyed:

    v11.138                      commit 05049fe
    v11.114 ... v11.137          NO COMMIT FIELD - 20 of 21 trees

The manifest that records a commit shipped today. Attribution by git would
therefore begin today and report "unknown" for the entire history the students
are actually running. The trees themselves are on L: and contain the real
files, so they are hashed directly.

This is also the better evidence and not merely the available one. The tree is
the artifact a student runs. git describes what the repository held, which
equals the published tree only if publishing was clean - an invariant
publish_release.py now enforces but which nothing enforced for the twenty
trees that predate it.

WHAT A MODULE'S FILE SET IS. Derived, not hand-listed: the entry script plus
every in-repo module it imports, transitively. A hand-written mapping would be
wrong within two releases and nobody would notice, because a mapping that is
too NARROW fails silently - it reports "your tool did not change" about a
release that changed it.

Dynamic imports (importlib, __import__) cannot be followed statically. A
module containing one is marked incomplete and SAYS SO in the table rather
than reporting a confident answer from a file set known to have holes.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path

TREE = Path(__file__).resolve().parent.parent
PUBLISH_ROOT = Path(r"L:\10_AGVG LAB\Lab Tools")
PUBLISHED_NAME = re.compile(
    r"^(?:WINK|NIKE)_Lab_Tools_v(?P<version>[0-9.]+)_Current_Files$",
    re.IGNORECASE)
INDEX_NAME = "tree_index.json"

# Local cache, so the SMB walk happens once per machine rather than per launch.
CACHE = Path(__file__).resolve().parent / ".version_index_cache.json"

SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache"}
# A module's behaviour comes from code. Documentation and sample data change
# constantly and would make every release look like it touched every tool.
CODE_SUFFIXES = {".py", ".bat", ".ijm", ".json", ".cfg", ".ini"}


# --------------------------------------------------------------- file sets

def _module_name_candidates(node, script):
    """Import targets to try resolving, as dotted names."""
    out = []
    if isinstance(node, ast.Import):
        out.extend(alias.name for alias in node.names)
    elif isinstance(node, ast.ImportFrom):
        if node.module:
            out.append(node.module)
            # `from package import thing` where thing is itself a module.
            out.extend(f"{node.module}.{a.name}" for a in node.names)
        elif node.level:
            # Relative import with no module: `from . import thing`.
            out.extend(a.name for a in node.names)
    return out


# Calls that start another script. `launch_python` is the Hub's own.
LAUNCH_CALLS = {"Popen", "run", "call", "check_call", "check_output",
                "launch_python", "spawn"}


def _py_literals(call):
    """.py string literals passed to a call, including inside list args."""
    out = []
    for arg in list(call.args) + [kw.value for kw in call.keywords]:
        items = arg.elts if isinstance(arg, (ast.List, ast.Tuple)) else [arg]
        for item in items:
            if isinstance(item, ast.Constant) and isinstance(item.value, str) \
                    and item.value.endswith(".py"):
                out.append(item.value)
    return out


def _resolve(dotted, script):
    """Find an in-repo .py for a dotted import name, or None.

    Third-party names (numpy, cv2) resolve to nothing, which is correct and
    not an uncertainty - they are not files this release can have changed.
    """
    parts = dotted.split(".")
    roots = [script.parent, TREE / "app", TREE]
    for root in roots:
        candidate = root.joinpath(*parts)
        for path in (candidate.with_suffix(".py"), candidate / "__init__.py"):
            if path.is_file():
                try:
                    path.relative_to(TREE)
                except ValueError:
                    continue
                return path
    return None


def module_files(entry, _seen=None):
    """Every in-repo file this entry script depends on, transitively.

    Returns (files, dynamic) - `dynamic` names files using importlib or
    __import__, whose real dependencies cannot be known statically.
    """
    entry = Path(entry)
    if not entry.is_absolute():
        entry = TREE / entry
    seen, dynamic = set(), set()
    stack = [entry]
    while stack:
        path = stack.pop()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for dotted in _module_name_candidates(node, path):
                    found = _resolve(dotted, path)
                    if found is not None:
                        stack.append(found)
            elif isinstance(node, ast.Call):
                name = getattr(node.func, "id", "") or getattr(
                    node.func, "attr", "")
                if name in {"import_module", "__import__"}:
                    dynamic.add(path)
                # A TOOL THAT LAUNCHES ANOTHER SCRIPT DEPENDS ON IT, and no
                # import statement says so. Without this edge a launcher's
                # file set omits the thing it launches, and the module is
                # reported unchanged by a release that rewrote the code it
                # actually runs.
                #
                # NARROW ON PURPOSE - only .py literals inside a launch call.
                # The first draft treated every ".py" string anywhere as an
                # edge. Filenames appear in error messages and docstrings, one
                # of them named lab_hub.py, and pulling in the Hub - which
                # imports the whole registry - inflated every tool's file set
                # from a dozen files to forty and made every module claim a
                # dependency on every other. An edge that broad describes
                # nothing.
                if name in LAUNCH_CALLS:
                    for literal in _py_literals(node):
                        target = TREE / literal
                        if target.is_file():
                            stack.append(target.resolve())
    return ({p.relative_to(TREE).as_posix() for p in seen},
            {p.relative_to(TREE).as_posix() for p in dynamic})


def split_own_shared(files, entry):
    """(own, shared) - files under the tool's own directory vs everything else.

    Both change a module's effective version; the spec is explicit that shared
    code counts. But they answer different questions for the reader. "v11.138
    changed 2 shared files" and "v11.130 changed 4 of this tool's own files"
    call for different amounts of suspicion, and collapsing them into one
    count throws that away.
    """
    entry = Path(entry)
    if not entry.is_absolute():
        entry = TREE / entry
    home = entry.parent.relative_to(TREE).as_posix()
    own = {f for f in files if f.startswith(home + "/") or f == entry.relative_to(TREE).as_posix()}
    return own, set(files) - own


# ---------------------------------------------------------- published trees

def _version_key(version):
    return tuple(int(part) for part in version.split(".") if part.isdigit())


def published_trees(root=PUBLISH_ROOT):
    """[(version, path)] oldest first. Missing share -> empty, not a crash."""
    try:
        entries = list(Path(root).iterdir())
    except OSError:
        return []
    found = []
    for path in entries:
        match = PUBLISHED_NAME.match(path.name)
        if match and path.is_dir():
            found.append((match.group("version"), path))
    return sorted(found, key=lambda pair: _version_key(pair[0]))


def hash_tree(root):
    """{relpath: sha256} for the code files in a published tree."""
    root = Path(root)
    out = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in CODE_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        except OSError:
            continue
        out[path.relative_to(root).as_posix()] = digest
    return out


def load_index(rebuild=False, root=PUBLISH_ROOT, cache=CACHE):
    """{version: {relpath: hash}} for every published tree.

    Cached locally. A published tree never changes - that is the invariant
    publishing is built on - so a cached index for a version already seen can
    be trusted; only NEW versions are hashed.
    """
    cache = Path(cache)
    known = {}
    if not rebuild and cache.is_file():
        try:
            known = json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            known = {}
    changed = False
    for version, path in published_trees(root):
        if version in known and not rebuild:
            continue
        # A tree may ship its own index; publishing writes one, which spares
        # every machine the SMB walk.
        shipped = path / "app" / INDEX_NAME
        if shipped.is_file():
            try:
                known[version] = json.loads(shipped.read_text(encoding="utf-8"))
                changed = True
                continue
            except (OSError, ValueError):
                pass
        known[version] = hash_tree(path)
        changed = True
    if changed:
        try:
            cache.write_text(json.dumps(known), encoding="utf-8")
        except OSError:
            pass
    return known


def changed_in(index, version):
    """Files this version changed relative to the version published before it.

    The OLDEST version has no predecessor. It is reported as changing nothing
    rather than everything: "the egg counter last changed in the earliest
    release we hold" would be an artifact of where our records start, not a
    fact about the tool.
    """
    versions = sorted(index, key=_version_key)
    if version not in index:
        return set()
    position = versions.index(version)
    if position == 0:
        return set()
    before, now = index[versions[position - 1]], index[version]
    return {name for name in set(before) | set(now)
            if before.get(name) != now.get(name)}


def effective_version(files, index, own=frozenset()):
    """(version, history) - the newest version that changed any of `files`.

    history is [(version, n_own, n_shared, hits)] newest first, listing ONLY
    the versions where this module actually differed. That list IS the picker:
    a list of every release would be noise, and the point is to show the
    versions that could possibly have changed this tool's behaviour.
    """
    history = []
    for version in sorted(index, key=_version_key, reverse=True):
        hits = changed_in(index, version) & set(files)
        if hits:
            history.append((version, len(hits & set(own)),
                            len(hits - set(own)), sorted(hits)))
    return (history[0][0] if history else None), history


# ------------------------------------------------------------------ report

def _registry():
    sys.path.insert(0, str(TREE / "app"))
    import lab_hub
    return [tool for tool in lab_hub.REGISTRY
            if tool.kind == "python" and tool.filename]


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build-index", action="store_true",
                    help="re-hash every published tree")
    ap.add_argument("--module", default=None, help="one tool, by name")
    args = ap.parse_args()

    index = load_index(rebuild=args.build_index)
    if not index:
        print(f"no published trees found under {PUBLISH_ROOT}")
        return 1
    versions = sorted(index, key=_version_key)
    print(f"{len(versions)} published versions, "
          f"v{versions[0]} .. v{versions[-1]}\n")

    tools = _registry()
    if args.module:
        wanted = args.module.lower()
        tools = [t for t in tools if wanted in t.name.lower()]
        if not tools:
            print(f"no tool matching {args.module!r}")
            return 1

    for tool in sorted(tools, key=lambda t: t.name):
        path = TREE / tool.filename
        if not path.is_file():
            print(f"{tool.name:<46} entry script missing: {tool.filename}")
            continue
        files, dynamic = module_files(path)
        own, _shared = split_own_shared(files, path)
        version, history = effective_version(files, index, own)
        mark = "  [file set incomplete: dynamic import]" if dynamic else ""
        latest = history[0] if history else None
        via = ""
        if latest:
            via = ("own code" if latest[1] else "shared code only")
        print(f"{tool.name:<46} v{version or '?':<9} "
              f"{len(files):>3} files  {via}{mark}")
        if args.module:
            for entry, n_own, n_shared, hits in history:
                print(f"    v{entry:<10} {n_own} own, {n_shared} shared")
                for name in hits:
                    print(f"        {'OWN   ' if name in own else 'shared'} "
                          f"{name}")
            if dynamic:
                print(f"    dynamic imports in: {', '.join(sorted(dynamic))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
