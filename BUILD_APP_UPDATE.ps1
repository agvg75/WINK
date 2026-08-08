# RETIRED 7 August 2026. This script no longer runs.
#
# Superseded by:  staged\tools\publish\publish_release.py
#
# WHY IT WAS RETIRED, recorded because the failure is the interesting part.
#
# This was a hand-run script with NO RELATIONSHIP TO THE COMMIT. It read a
# version out of staged\app\release_info.json, zipped the tree, and wrote an
# update manifest - none of which was tied to what had actually been
# committed or pushed. So its output could drift from what shipped, and
# nothing could detect the drift.
#
# It did drift. Forensics, 7 Aug 2026:
#
#   file last modified          6 Aug 2026 15:19:46
#   the v11.137 commit f74c93c  6 Aug 2026 15:20:20
#   gap                         34 seconds
#
# The changelog was written, the code commit went out 34 seconds later, and
# the changelog edit was never staged. Worse, no release commit had touched
# this file for THREE consecutive releases - v11.135, v11.136 and v11.137 all
# shipped without it - so the recovered edit was cumulative, three entries
# written at once, catching up documentation that had been stranded outside
# version control the whole time.
#
# Two scripts writing the release story separately is how they come to
# describe different things. publish_release.py is now the SINGLE WRITER of
# both the published tree and update_manifest.json, generated from the same
# data in the same second, and it refuses a dirty tree - so a release whose
# documentation is uncommitted cannot be published at all.
#
# The file is left here rather than deleted: the record of what was once the
# publish path is worth more than a tidy directory.

Write-Host ""
Write-Host "  BUILD_APP_UPDATE.ps1 is RETIRED and does nothing." -ForegroundColor Yellow
Write-Host ""
Write-Host "  Use instead, from the staged folder:"
Write-Host "      py tools\publish\publish_release.py --version 11.139 --note '...'"
Write-Host ""
Write-Host "  It refuses a dirty or unpushed tree, runs the check suite,"
Write-Host "  writes a NEW versioned tree that never overwrites a published"
Write-Host "  one, generates update_manifest.json from the same data, and"
Write-Host "  verifies its own output before reporting success."
Write-Host ""
exit 1
