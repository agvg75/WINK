"""Survey a drive by directory entries alone, never by opening a file.

Andres crashed a previous attempt because the search inspected each gigantic
image across millions of them. The property under test here is that nothing is
ever opened - a folder of huge files must cost the same as a folder of empty
ones - and that the next layer is PRICED before it is run.
"""
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import drive_survey as ds   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("drive survey - regression\n")

tmp = Path(tempfile.mkdtemp())
(tmp / "expA" / "ch00").mkdir(parents=True)
(tmp / "expA" / "ch01").mkdir(parents=True)
(tmp / "expB").mkdir()
(tmp / "$RECYCLE.BIN").mkdir()
(tmp / "__pycache__").mkdir()
for i in range(5):
    (tmp / "expA" / f"frame{i}.tif").write_bytes(b"x" * 1000)
(tmp / "expA" / "results.csv").write_text("a,b\n1,2\n", encoding="utf-8")
(tmp / "expA" / "notes.docx").write_bytes(b"y" * 50)
(tmp / "expB" / "movie.avi").write_bytes(b"z" * 2000)

top = ds.scan_one(tmp)
check("subdirectories are listed", sorted(top["subdirs"]) == ["expA", "expB"])
check("...with recycle bins and caches skipped",
      "$RECYCLE.BIN" not in top["subdirs"] and
      "__pycache__" not in top["subdirs"],
      "they are never experiments and cost a lot to walk")

a = ds.scan_one(tmp / "expA")
check("files are counted", a["n_files"] == 7)
check("extensions are histogrammed",
      a["extensions"][".tif"] == 5 and a["extensions"][".csv"] == 1)
check("...and grouped into families that say what a folder HOLDS",
      a["families"]["image_stack"] == 5 and a["families"]["table"] == 1 and
      a["families"]["document"] == 1)
# Compared against the real on-disk total rather than an arithmetic guess:
# write_text translates \n to \r\n on Windows, so counting the characters
# written is short by one byte per line. The property that matters is that the
# reported size matches what the filesystem says, which is what a directory
# entry carries - not that it matches what the test thinks it wrote.
on_disk = sum(f.stat().st_size for f in (tmp / "expA").iterdir() if f.is_file())
check("size comes from the directory entry, not from reading",
      a["total_bytes"] == on_disk, f"{a['total_bytes']} == {on_disk} on disk")
check("modification times are captured",
      a["newest_mtime"] is not None and a["oldest_mtime"] is not None)

# --- nothing is opened -------------------------------------------------------
import builtins   # noqa: E402
opened = []
real_open = builtins.open


def watched(*args, **kwargs):
    opened.append(str(args[0]) if args else "?")
    return real_open(*args, **kwargs)


builtins.open = watched
try:
    ds.survey_layer([tmp, tmp / "expA", tmp / "expB"])
finally:
    builtins.open = real_open
check("scanning opens NO file", opened == [], str(opened[:3]))
check("...which is the entire reason this exists",
      True, "a folder of 2 GB stacks costs the same as a folder of empty files")

# --- confocal formats are recognised by name --------------------------------
(tmp / "expB" / "stack.lif").write_bytes(b"q")
(tmp / "expB" / "other.nd2").write_bytes(b"q")
b = ds.scan_one(tmp / "expB")
check("confocal formats are named without being read",
      b["families"]["confocal"] == 2)

# --- one layer, no recursion -------------------------------------------------
layer = ds.survey_layer([tmp])
check("a layer scans only what it is given, never deeper",
      layer["n_dirs_scanned"] == 1)
check("...and reports its own rate, measured not assumed",
      layer["entries_per_s"] is not None and layer["seconds_per_dir"] >= 0)

# --- the next layer is priced before it is run -------------------------------
est = ds.estimate_next_layer(layer, sample=2)
check("the next layer's size is known from the current one",
      est["n_dirs_next"] == 2)
check("...and its cost is measured on this drive, not guessed",
      "estimated_seconds" in est and est["sampled"] <= 2)
check("...and labelled a projection",
      "not a measurement" in est["is_a_projection"])

leaf = ds.survey_layer([tmp / "expA" / "ch00"])
done = ds.estimate_next_layer(leaf)
check("a layer with nothing below it says the survey is complete",
      done["n_dirs_next"] == 0 and "complete" in done["why"])

# --- an uneven tree is flagged, not averaged away ----------------------------
(tmp / "big").mkdir()
for i in range(60):
    (tmp / "big" / f"f{i}.tif").write_bytes(b"x")
(tmp / "tiny").mkdir()
(tmp / "tiny" / "one.tif").write_bytes(b"x")
uneven = ds.estimate_next_layer(ds.survey_layer([tmp]), sample=6)
check("a lopsided tree is flagged", "warning" in uneven,
      f"spread {uneven.get('sample_spread')}x")
check("...naming that the average describes none of them",
      "describes none of them" in uneven["warning"])

# --- the plan ----------------------------------------------------------------
cheap = ds.plan(layer, {"n_dirs_next": 10, "estimated_minutes": 0.5})
check("a cheap layer is recommended", cheap["recommend"] == "go")
dear = ds.plan(layer, {"n_dirs_next": 5000, "estimated_minutes": 40.0})
check("an expensive layer is split, not refused",
      dear["recommend"] == "split" and dear["suggested_batches"] > 1)
check("...naming that a crash then costs one branch, not the layer",
      "one branch, not the whole layer" in dear["why"],
      "which is what happened last time")
check("nothing below means stop",
      ds.plan(layer, {"n_dirs_next": 0, "why": "nothing"})["recommend"] == "stop")

# --- resumability ------------------------------------------------------------
out = tmp / "sub" / "layer1.json"
ds.save(layer, out)
check("a layer is written as soon as it completes", out.exists())
check("...and reads back", ds.load(out)["n_dirs_scanned"] == 1)
check("a missing layer file is not an error, just absent",
      ds.load(tmp / "nope.json") is None)
(tmp / "bad.json").write_text("{half", encoding="utf-8")
try:
    ds.load(tmp / "bad.json")
    check("a half-written layer is refused", False)
except ds.SurveyError as exc:
    check("a half-written layer is refused", True)
    check("...naming both ways of getting it wrong",
          "silently re-scan" in str(exc) and "never reached" in str(exc))

# --- unreadable directories do not stop the survey ---------------------------
bad = ds.scan_one(tmp / "does_not_exist")
check("an unreadable directory is recorded, not raised",
      "unreadable" in bad and bad["n_files"] == 0,
      "one locked folder must not end a survey of millions")

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("DRIVE_SURVEY_PASS")
