"""Find every confocal-format file on the drive. Extension-only, no headers.

Deliberately separate from the census: this is SMB I/O over an unknown tree,
the census is CPU over a known file list. Mixing them would make a slow run
impossible to attribute.
"""
import csv
import os
import sys
import time

CONFOCAL = {".lif", ".czi", ".lsm", ".nd2", ".oib", ".oif", ".ims", ".zvi"}
ROOT = sys.argv[1] if len(sys.argv) > 1 else "L:\\"
OUT = sys.argv[2]
CAP = float(sys.argv[3]) if len(sys.argv) > 3 else 900.0

started = time.time()
rows = []
dirs = files = 0
stopped = False
for dirpath, dirnames, filenames in os.walk(ROOT, onerror=lambda e: None):
    if time.time() - started > CAP:
        stopped = True
        break
    dirs += 1
    for name in filenames:
        files += 1
        ext = os.path.splitext(name)[1].lower()
        if ext in CONFOCAL:
            full = os.path.join(dirpath, name)
            try:
                st = os.stat(full)
                size, mtime = st.st_size, st.st_mtime
            except OSError:
                size, mtime = 0, 0
            rows.append({"path": full, "ext": ext, "size_bytes": size,
                         "mtime": time.strftime("%Y-%m-%d",
                                                time.localtime(mtime))
                         if mtime else ""})
    if dirs % 2000 == 0:
        print(f"  {dirs:,} dirs  {files:,} files  {len(rows)} confocal  "
              f"{time.time() - started:.0f}s", flush=True)

with open(OUT, "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=["path", "ext", "size_bytes", "mtime"])
    w.writeheader()
    w.writerows(rows)

print(f"\n{'directories walked':22} {dirs:,}"
      + ("   STOPPED AT CAP" if stopped else "   (complete)"))
print(f"{'files seen':22} {files:,}")
print(f"{'elapsed':22} {time.time() - started:.0f} s")
print(f"{'confocal files':22} {len(rows):,}")
from collections import Counter
for ext, n in Counter(r["ext"] for r in rows).most_common():
    gb = sum(r["size_bytes"] for r in rows if r["ext"] == ext) / 1e9
    print(f"    {ext:8} {n:6,}   {gb:8.1f} GB")
print(f"written {OUT}")
