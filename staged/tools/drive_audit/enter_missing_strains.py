"""Enter the seven missing strains into ReagentHub. Backup first, one txn."""
import csv, datetime, shutil, sqlite3, sys
from pathlib import Path

DB = Path(r"C:\ReagentHub\data\reagenthub.db")
BACKUPS = Path(r"L:\ReagentHub\backups")
SRC = Path(sys.argv[1])
apply = "--apply" in sys.argv

rows = list(csv.DictReader(open(SRC, newline="", encoding="utf-8-sig")))
GENE = {"AG405": "pezo-1", "AG406": "pezo-1", "COP1367": "pezo-1",
        "COP1553": "pezo-1", "COP1524": "pezo-1",
        "AVG6": "dys-1", "VG02": "dys-1"}

now = datetime.datetime.now().isoformat(sep=" ")
plan = []
for r in rows:
    strain = r["strain"].strip()
    note = (f"Entered from the drive audit, {now[:10]}. "
            f"Genotype status: {r['genotype_status']}. "
            f"{r['needs_before_entry']} "
            f"Drive footprint: {r['drive_folders']} folder(s), "
            f"{r['drive_files']} files, {r['drive_gb'] or '?'} GB, "
            f"{r['drive_years']}.")
    plan.append({
        "strain": strain,
        "genotype": r["genotype"].strip() or None,
        "description": r["description"].strip(),
        "source": r["source"].strip(),
        "made_by": r["made_by"].strip() or None,
        "gene_name": GENE.get(strain.upper()),
        "construct_description": note,
        "status": "active",
        # EVERY ROW LANDS AS needs_review. None of these was read off a tube;
        # three come from papers, two from search summaries that were not read
        # verbatim, one is composed from a stated background and one has no
        # genotype at all. The table already uses this flag on 78 rows.
        "needs_review": 1,
        "created_by": 1, "created_at": now,
        "last_modified_by": 1, "last_modified_at": now,
    })

print(f"{'strain':9} {'gene':8} {'status':9} genotype")
for p in plan:
    print(f"  {p['strain']:9} {str(p['gene_name']):8} "
          f"{'needs_review':9} {p['genotype'] or '(none recorded)'}")

if not apply:
    print("\nDRY RUN. Re-run with --apply to write.")
    raise SystemExit(0)

BACKUPS.mkdir(parents=True, exist_ok=True)
stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
backup = BACKUPS / f"reagenthub_{stamp}_before_strain_entry.db"
shutil.copy2(DB, backup)
print(f"\nbacked up to {backup}")

con = sqlite3.connect(DB)
try:
    existing = {r[0].strip().upper() for r in
                con.execute("select strain from worm_strains "
                            "where strain is not null")}
    clash = [p["strain"] for p in plan if p["strain"].upper() in existing]
    if clash:
        raise SystemExit(f"REFUSING: already present: {clash}")
    cols = list(plan[0])
    con.executemany(
        f"insert into worm_strains ({','.join(cols)}) "
        f"values ({','.join('?' * len(cols))})",
        [tuple(p[c] for c in cols) for p in plan])
    con.commit()
finally:
    con.close()

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
print(f"\nworm_strains now holds "
      f"{con.execute('select count(*) from worm_strains').fetchone()[0]} rows")
for s in sorted(GENE):
    r = con.execute("select strain, genotype, needs_review from worm_strains "
                    "where upper(trim(strain))=?", (s,)).fetchone()
    print(f"  {r[0]:9} needs_review={r[2]}  {r[1] or '(none)'}")
con.close()
