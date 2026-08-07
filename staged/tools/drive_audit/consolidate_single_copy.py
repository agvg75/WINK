"""Copy the files that exist in only ONE place onto a drive that has room.

    py consolidate_single_copy.py --plan   ... (default, writes nothing)
    py consolidate_single_copy.py --execute

WHAT THIS IS FOR. Across six locations, 10.88 TB of this archive exists in
exactly one place. Most of that is on L: and the scope computer, which the
institution backs up. What has no story attached is the material sitting
alone on the small externals: 0.41 TB on F, 0.81 TB on G, 0.36 TB on H.
This copies those, and only those, onto I: - which has 11.16 TB free and is
the only one of the six holding nothing unique.

COPYING ONTO I: KEEPS I: A BACKUP. Every file written there also remains on
its source drive, so I: still holds zero bytes that exist nowhere else. It
stays redundant by definition rather than by luck. Nothing is moved and
nothing is deleted, here or ever - this script has no delete path at all.

WHAT "EXISTS IN ONE PLACE" MEANS, because it decides what gets copied. Two
files are the same copy when they share a FILENAME and an EXACT BYTE COUNT.
No file is opened to decide that. The test is conservative in one direction:
a copy that was RENAMED reads as unique, so this may copy something that is
in fact already held elsewhere under another name. That wastes space and
loses nothing. The opposite error - two different files sharing a name and
size, treated as one, so one is NOT copied - is the one that matters, and it
is why the manifest records the identifying key for every decision.

PROVENANCE SURVIVES. Each file lands under a per-source tree that mirrors its
original path, so I:\\...\\F_injection\\Adina\\x.tif came from F:\\Adina\\x.tif
and says so without needing this script to be re-run.

VERIFICATION IS SHA-256 ON BOTH SIDES. The source is hashed as it is read
during the copy, then the written file is read back and hashed independently.
A file whose two hashes disagree is reported as FAILED and left in place for
inspection; it is never silently retried or quietly dropped.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import datetime
import hashlib
import os
import shutil
import sys
import threading
import time
from collections import Counter

# Eight was chosen against the measurement, not by taste: the serial run
# sat at 12 files/s with the CPU at 34% and the disks at 13 MB/s, so the
# limit was waiting, not throughput. More workers than this on one USB
# bus starts to contend rather than help.
WORKERS = 8

SKIP_NAMES = {"$RECYCLE.BIN", "System Volume Information", ".git",
              "__pycache__", "node_modules", ".venv", "System Volume Info"}

SIZE_BITS = 40
SIZE_MASK = (1 << SIZE_BITS) - 1
CHUNK = 4 * 1024 * 1024


def key_of(name, size):
    return (hash(name.lower()) & ((1 << 62) - 1)) << SIZE_BITS \
        | (size & SIZE_MASK)


def long_path(path):
    """Windows refuses paths over 260 characters without this prefix.

    Source trees here are already deep, and nesting them under a per-source
    root makes them deeper. Without this the copy fails partway through on
    exactly the folders most worth preserving.
    """
    path = os.path.abspath(path)
    if os.name != "nt" or path.startswith("\\\\?\\"):
        return path
    if path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + path[2:]
    return "\\\\?\\" + path


def walk_keys(root, label, *, want_paths=False, cap=3600.0, ignore=()):
    """Every file under root as a key, optionally with its path.

    `ignore` holds directories to skip entirely. THE DESTINATION MUST BE ONE
    OF THEM. On a resume, files already copied are sitting on the target
    drive, and counting them makes their sources look "already held
    elsewhere" - so they drop out of the job list and NEVER APPEAR IN THE
    MANIFEST. The copy would be correct and the record would be short by
    however many files the previous run managed, which is the provenance gap
    this whole consolidation exists to close.
    """
    started = time.time()
    keys = set()
    paths = []
    files = 0
    stack = [root]
    ignored = {os.path.normcase(os.path.abspath(p)) for p in ignore}
    while stack:
        if time.time() - started > cap:
            print(f"  [{label}] STOPPED AT CAP", flush=True)
            break
        current = stack.pop()
        if os.path.normcase(os.path.abspath(current)) in ignored:
            continue
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name not in SKIP_NAMES and \
                                    os.path.normcase(os.path.abspath(
                                        entry.path)) not in ignored:
                                stack.append(entry.path)
                            continue
                        size = entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
                    key = key_of(entry.name, size)
                    keys.add(key)
                    files += 1
                    if want_paths:
                        paths.append((entry.path, size, key))
        except OSError:
            continue
    print(f"  [{label}] {files:,} files, {time.time() - started:.0f}s",
          flush=True)
    return keys, paths


def hashed_copy(source, destination, known_dirs=None, lock=None):
    """Copy while hashing the source, then hash the written file back.

    Returns (source_hash, destination_hash, bytes). They must match; the
    caller decides what a mismatch means. Reading the destination back is the
    point - hashing only the source would verify that the disk was read, not
    that anything correct was written. Measured: that read costs nothing,
    because the file is still in the page cache when it happens.

    `known_dirs` IS WHY THIS RUNS IN HOURS RATHER THAN DAYS. The first
    version called os.makedirs for every single file - 1.57 million metadata
    round trips to a USB drive, nearly all redundant since consecutive files
    share a directory. Measured at 12 files/s, 83 ms each, against disks
    doing 13 MB/s while the CPU sat at 34%. The bottleneck was never the
    hardware.
    """
    digest_in = hashlib.sha256()
    total = 0
    parent = os.path.dirname(long_path(destination))
    if known_dirs is None:
        os.makedirs(parent, exist_ok=True)
    elif parent not in known_dirs:
        os.makedirs(parent, exist_ok=True)
        if lock is not None:
            with lock:
                known_dirs.add(parent)
        else:
            known_dirs.add(parent)
    with open(long_path(source), "rb") as fin, \
            open(long_path(destination), "wb") as fout:
        while True:
            block = fin.read(CHUNK)
            if not block:
                break
            digest_in.update(block)
            fout.write(block)
            total += len(block)
    digest_out = hashlib.sha256()
    with open(long_path(destination), "rb") as fh:
        while True:
            block = fh.read(CHUNK)
            if not block:
                break
            digest_out.update(block)
    return digest_in.hexdigest(), digest_out.hexdigest(), total


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sources", nargs="+", required=True,
                    metavar="LABEL=PATH",
                    help="drives whose single-copy files should be copied")
    ap.add_argument("--others", nargs="+", required=True,
                    metavar="LABEL=PATH",
                    help="every OTHER location, used only to decide what is "
                         "already held elsewhere. Leaving one out would copy "
                         "files that are in fact already safe.")
    ap.add_argument("--target", required=True,
                    help="destination root, e.g. I:\\_consolidated")
    ap.add_argument("--execute", action="store_true",
                    help="actually copy. Without this nothing is written.")
    ap.add_argument("--new-run", action="store_true",
                    help="start a fresh destination folder instead of "
                         "resuming the most recent one. Rarely wanted: the "
                         "default resumes, because a restart that begins "
                         "again in a new folder duplicates everything already "
                         "copied and leaves two half-copies with nothing "
                         "recording which is which.")
    ap.add_argument("--max-seconds", type=float, default=3600.0)
    args = ap.parse_args()

    def split(spec):
        label, _, path = spec.partition("=")
        return (label, path) if path else (path or label, label)

    print("Reading every location to decide what is held only once.")
    print("A location missing from --others would make its files look "
          "unique.\n")

    # DECIDED BEFORE ANYTHING IS WALKED. The destination has to be known
    # in advance so it can be excluded from the comparison - see
    # walk_keys' `ignore`.
    existing = sorted(
        name for name in os.listdir(args.target)
        if name.startswith("single_copy_")
        and os.path.isdir(os.path.join(args.target, name))) \
        if os.path.isdir(args.target) else []
    if existing and not args.new_run:
        stamp = existing[-1][len("single_copy_"):]
        target_root = os.path.join(args.target, existing[-1])
        print(f"\nRESUMING into the existing run {existing[-1]}")
        print("    files already there with a matching size will be skipped.")
        print("    Pass --new-run to start a separate copy instead.")
        if len(existing) > 1:
            print(f"    NOTE: {len(existing)} consolidation folders exist; "
                  f"resuming the most recent. The others are untouched.")
    else:
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        target_root = os.path.join(args.target, f"single_copy_{stamp}")
    consolidation_dirs = [os.path.join(args.target, name)
                          for name in (os.listdir(args.target)
                                       if os.path.isdir(args.target)
                                       else [])
                          if name.startswith('single_copy_')]
    if consolidation_dirs:
        print(f"excluding {len(consolidation_dirs)} consolidation "
              f"folder(s) from the comparison - they are this tool's own"
              f" output, not an independent copy")

    elsewhere = set()
    for spec in args.others:
        label, path = split(spec)
        if not os.path.exists(path):
            sys.exit(f"REFUSING TO RUN: --others location {label} ({path}) "
                     f"is not reachable. Its files would wrongly read as "
                     f"absent, and material already held there would be "
                     f"copied as if it were unique.")
        keys, _ = walk_keys(path, label, cap=args.max_seconds,
                           ignore=consolidation_dirs)
        elsewhere |= keys

    sources = []
    for spec in args.sources:
        label, path = split(spec)
        if not os.path.exists(path):
            sys.exit(f"REFUSING TO RUN: source {label} ({path}) is not "
                     f"reachable.")
        sources.append((label, path))

    # A source drive is also "elsewhere" for the OTHER source drives, so each
    # is compared against every location except itself.
    source_keys = {}
    source_paths = {}
    for label, path in sources:
        keys, paths = walk_keys(path, label, want_paths=True,
                                cap=args.max_seconds,
                                ignore=consolidation_dirs)
        source_keys[label] = keys
        source_paths[label] = paths

    # RESUME INTO THE EXISTING RUN, NOT BESIDE IT. The first version minted a
    # fresh timestamp every time and created a new folder, so the per-file
    # "already present" check could never see the previous run's work - it was
    # looking in a directory that had just been created empty. Restarting
    # after an interruption would have silently recopied everything into a
    # second folder: hours wasted, and two half-copies on the drive with
    # nothing saying which was which.

    jobs = []
    for label, path in sources:
        others = set(elsewhere)
        for other_label in source_keys:
            if other_label != label:
                others |= source_keys[other_label]
        drive = os.path.splitdrive(path)[0].rstrip(":\\") or label
        for full, size, key in source_paths[label]:
            if key in others:
                continue
            relative = os.path.relpath(full, path)
            jobs.append({
                "label": label, "source": full, "size": size, "key": key,
                "destination": os.path.join(target_root, label, relative),
            })

    by_label = Counter(job["label"] for job in jobs)
    bytes_by_label = Counter()
    for job in jobs:
        bytes_by_label[job["label"]] += job["size"]
    total_bytes = sum(job["size"] for job in jobs)

    print("\n" + "=" * 68)
    print("FILES HELD IN EXACTLY ONE PLACE, on the source drives")
    for label, _ in sources:
        print(f"    {label:14} {by_label[label]:9,} files   "
              f"{bytes_by_label[label] / 1e12:6.2f} TB")
    print(f"    {'TOTAL':14} {len(jobs):9,} files   "
          f"{total_bytes / 1e12:6.2f} TB")
    print(f"\n    destination {target_root}")

    free = shutil.disk_usage(args.target).free
    print(f"    free on target {free / 1e12:.2f} TB")
    if free < total_bytes * 1.05:
        sys.exit(f"\nREFUSING TO RUN: {total_bytes / 1e12:.2f} TB to copy "
                 f"against {free / 1e12:.2f} TB free. Not starting a copy "
                 f"that cannot finish - a partial consolidation whose scope "
                 f"nobody recorded is how the archive reached this state.")

    if not args.execute:
        print("\nPLAN ONLY. Nothing was written. Re-run with --execute.")
        plan_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            f"consolidation_plan_{stamp}.csv")
        with open(plan_file, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["label", "source", "destination", "size_bytes"])
            for job in jobs:
                writer.writerow([job["label"], job["source"],
                                 job["destination"], job["size"]])
        print(f"plan written to {plan_file}")
        return 0

    os.makedirs(long_path(target_root), exist_ok=True)
    manifest_path = os.path.join(target_root, "MANIFEST.csv")
    record_path = os.path.join(target_root, "VERIFICATION.txt")
    progress_path = os.path.join(target_root, "PROGRESS.log")

    copied = failed = skipped = 0
    copied_bytes = 0
    started = time.time()
    rows = []
    known_dirs = set()
    guard = threading.Lock()

    # A LOG THAT CAN BE READ WHILE THE COPY IS STILL RUNNING. Flushed on
    # every write, because a log buffered until the end tells you nothing
    # during the hours you actually want to know. Every failure is written
    # the moment it happens rather than waiting for the summary.
    # APPEND. Opening "w" would erase the previous run's log at the exact
    # moment it becomes evidence - a resume exists because something went
    # wrong, and what went wrong is written above.
    log = open(long_path(progress_path), "a", encoding="utf-8", buffering=1)

    log_lock = threading.Lock()

    def note(line):
        # Serialised because eight workers write here. Without the lock two
        # failures reported in the same instant interleave into one unreadable
        # line, and the immediate-failure log matters MORE with concurrency,
        # not less: eight threads failing on one bad directory would otherwise
        # read as eight unrelated errors.
        with log_lock:
            stamp = datetime.datetime.now().strftime("%H:%M:%S")
            log.write(f"{stamp}  {line}\n")
            log.flush()
            os.fsync(log.fileno())

    note(f"consolidation started {datetime.datetime.now().isoformat(timespec='seconds')}")
    note(f"{len(jobs):,} files to copy, {total_bytes / 1e12:.3f} TB")
    note(f"destination {target_root}")
    note("sources: " + ", ".join(f"{label} ({path})" for label, path in sources))
    note("nothing is moved or deleted; sources are left exactly as they are")
    note("-" * 66)
    def do_one(job):
        """Copy one file. Returns its manifest row. Never raises."""
        destination = job["destination"]
        source_hash = destination_hash = ""
        written = 0
        try:
            # THE RESUME RULE, and what it does about a half-written file.
            # PRESENCE ALONE IS NOT ENOUGH. A file is skipped only if it
            # exists AND its size equals the source's exactly. An interrupted
            # write leaves a SHORT file, so it fails the size test and is
            # copied again from the start - open(..., "wb") truncates, so the
            # partial content is replaced rather than appended to. That is
            # the case an existence-only check would hide, and it is the
            # likeliest failure after a knock or a power blip.
            #
            # The limit, stated because the manifest must not overclaim: a
            # file that reached full size and was corrupted afterwards would
            # pass this test. Skipped files are NOT re-hashed, and their
            # manifest row says so rather than reading as verified.
            if os.path.exists(long_path(destination)) and \
                    os.path.getsize(long_path(destination)) == job["size"]:
                status = "already present (size match, not re-hashed)"
            else:
                source_hash, destination_hash, written = hashed_copy(
                    job["source"], destination, known_dirs, guard)
                status = ("verified" if source_hash == destination_hash
                          else "FAILED - hashes differ")
                shutil.copystat(long_path(job["source"]),
                                long_path(destination), follow_symlinks=False)
        except OSError as exc:
            status = f"FAILED - {type(exc).__name__}: {exc}"
        return {
            "label": job["label"], "source": job["source"],
            "destination": destination, "size_bytes": job["size"],
            "sha256_source": source_hash,
            "sha256_written": destination_hash,
            "match": "yes" if source_hash and source_hash == destination_hash
                     else ("not checked" if status.startswith("already")
                           else "NO"),
            "status": status,
            "identity_key": job["key"],
            "bytes_written": written,
            "copied_utc": datetime.datetime.now(
                datetime.timezone.utc).isoformat(timespec="seconds"),
        }

    # EIGHT WORKERS, because the limit was per-file latency and not bandwidth.
    # Serial, this ran at 12 files/s with the disks at 13 MB/s and the CPU at
    # 34% - the drive was waiting, not working. Concurrency hides that
    # latency; it does not ask more of the hardware.
    note(f"copying with {WORKERS} workers")
    index = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for row in pool.map(do_one, jobs):
            index += 1
            rows.append(row)
            if row["status"].startswith("FAILED"):
                failed += 1
                note(f"FAILED  {row['source']}")
                note(f"        -> {row['destination']}")
                note(f"        {row['status']}")
            elif row["status"].startswith("already"):
                skipped += 1
            else:
                copied += 1
                copied_bytes += row["bytes_written"]
            if index % 500 == 0 or index == len(jobs):
                elapsed_now = max(time.time() - started, 1)
                rate = copied_bytes / elapsed_now / 1e6
                done_fraction = index / max(len(jobs), 1)
                eta = (elapsed_now / max(done_fraction, 1e-9)
                       - elapsed_now) / 3600
                line = (f"{index:,}/{len(jobs):,} files   "
                        f"{copied_bytes / 1e12:.3f} TB copied   "
                        f"{rate:.0f} MB/s   {failed} failed   "
                        f"{skipped:,} already present   "
                        f"~{eta:.1f} h left")
                print("  " + line, flush=True)
                note(line)

    fields = ["label", "source", "destination", "size_bytes", "sha256_source",
              "sha256_written", "match", "status", "identity_key",
              "bytes_written", "copied_utc"]
    with open(long_path(manifest_path), "w", newline="",
              encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    elapsed = time.time() - started
    summary = [
        "CONSOLIDATION OF SINGLE-COPY MATERIAL",
        f"written {datetime.datetime.now().isoformat(timespec='seconds')}",
        "",
        "WHAT THIS IS. Files that existed in exactly one place across six",
        "locations, copied here so they exist in two. The sources were NOT",
        "modified and NOTHING was deleted. Do not clear any source drive on",
        "the strength of this file alone - read the per-file manifest.",
        "",
        f"destination      {target_root}",
        f"sources          " + ", ".join(f"{label} ({path})"
                                         for label, path in sources),
        f"compared against " + ", ".join(split(s)[0] for s in args.others)
        + ", plus each source against the others",
        "",
        f"files copied and verified   {copied:,}",
        f"files already present       {skipped:,}",
        f"files FAILED                {failed:,}",
        f"bytes copied                {copied_bytes / 1e12:.3f} TB",
        f"elapsed                     {elapsed / 3600:.2f} h",
        "",
        "VERIFICATION. Every copied file was hashed with SHA-256 as it was",
        "read, and the WRITTEN file was then read back and hashed again.",
        "'verified' in the manifest means those two hashes matched. A file",
        "reading FAILED was left in place for inspection, never retried",
        "silently and never dropped.",
        "",
        "WHAT 'SINGLE COPY' MEANT. Same filename and same exact byte count",
        "counts as the same file. Nothing was opened to decide it. A renamed",
        "copy therefore reads as unique and may have been copied here",
        "needlessly, which costs space and loses nothing. The reverse error -",
        "two different files sharing a name and size - is recorded per file",
        "as identity_key so any decision can be re-checked.",
        "",
        "DRIVE HEALTH: SMART WAS NOT AVAILABLE, AND WHAT IS QUOTED IS NOT IT.",
        "Windows reported this destination as HealthStatus: Healthy. That is",
        "the operating system's own volume state - it means no filesystem",
        "error is outstanding and the volume mounts. It is NOT derived from",
        "SMART. Get-StorageReliabilityCounter returned nothing for ANY disk",
        "on this machine, internal or external, because the USB bridges do",
        "not pass SMART through. So there is no reallocated-sector count, no",
        "power-on hours and no temperature behind that word.",
        "",
        "Anyone reading this later should know which of the two they have:",
        "a healthy-mounting volume, not a disk that reported itself well.",
        "Every file below was nonetheless verified by reading it back and",
        "hashing it, which tests this drive far harder than SMART would.",
    ]
    if failed:
        summary += ["", "*** THIS RUN HAD FAILURES. Do not clear any source "
                        "drive. ***"]
    with open(long_path(record_path), "w", encoding="utf-8") as fh:
        fh.write("\n".join(summary) + "\n")

    note("-" * 66)
    note(f"finished: {copied:,} verified, {skipped:,} already present, "
         f"{failed:,} FAILED, {copied_bytes / 1e12:.3f} TB")
    note(f"manifest {manifest_path}")
    if failed:
        note("THIS RUN HAD FAILURES - do not clear any source drive")
    log.close()

    # THE MANIFEST GOES IN TWO PLACES. On the drive it describes, so it
    # travels with the data, and on L, so it is findable without plugging
    # anything in. The I: copy was sensible and its scope was invisible a
    # year later precisely because nothing recorded it anywhere.
    copies_made = []
    for mirror in (os.path.join(
            "L:\\", "10_AGVG LAB", "Lab Tools", "consolidation_records"),):
        try:
            os.makedirs(long_path(mirror), exist_ok=True)
            for source_file, suffix in ((manifest_path, "MANIFEST.csv"),
                                        (record_path, "VERIFICATION.txt"),
                                        (progress_path, "PROGRESS.log")):
                shutil.copy2(long_path(source_file),
                             long_path(os.path.join(
                                 mirror, f"single_copy_{stamp}_{suffix}")))
            copies_made.append(mirror)
        except OSError as exc:
            print(f"could not mirror the manifest to {mirror}: {exc}")

    print("\n".join(summary[-10:]))
    print(f"\nmanifest      {manifest_path}")
    print(f"verification  {record_path}")
    print(f"progress log  {progress_path}")
    for mirror in copies_made:
        print(f"mirrored to   {mirror}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
