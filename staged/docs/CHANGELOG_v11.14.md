# NIKE application v11.14

- Fixed update failures caused by attempting to rename a centrally managed,
  versioned `*_Current_Files` folder on the shared L drive.
- Shared-folder updates now validate and open the already-published new release
  side-by-side. They never rename, delete, or replace shared student folders.
- Local installed copies retain checksum verification, atomic replacement,
  rollback, and runtime compatibility checks.
- Versioned shared releases now use their own `app/release_info.json` stamp and
  ignore a stale parent `version.json`. This prevents v11.13 from incorrectly
  offering v11.13 as an update because the shared parent still said v11.12.
- Moved **Power analysis (Experimental)** into the existing
  **Acquisition and utilities** category; the separate Utilities category has
  been removed.
