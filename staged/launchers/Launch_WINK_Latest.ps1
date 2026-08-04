# Launch the latest WINK, wherever this file lives.
#
# Resolves the current WINK snapshot next to this script and starts its
# Launch_Lab_Hub.bat, so a single Desktop shortcut to Launch_WINK_Latest.bat
# always opens the newest release - no need to open the versioned
# WINK_Lab_Tools_v*_Current_Files folder by hand each time.
#
# Order of preference:
#   1. the version named in updates\update_manifest.json (the canonical latest)
#   2. otherwise the most recently written WINK_Lab_Tools_v*_Current_Files folder
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

$target = $null
$manifest = Join-Path $root 'updates\update_manifest.json'
if (Test-Path $manifest) {
    try {
        $version = (Get-Content -Raw $manifest | ConvertFrom-Json).app_version
        $candidate = Join-Path $root ("WINK_Lab_Tools_v{0}_Current_Files" -f $version)
        if (Test-Path $candidate) { $target = $candidate }
    } catch { }
}
if (-not $target) {
    # Choose the highest VERSION, not the most recently written folder.
    # Timestamps are the wrong key twice over: robocopy preserves source times,
    # so two releases published minutes apart can carry the SAME LastWriteTime -
    # and PowerShell's sort is stable, so a tie falls back to alphabetical order
    # and v11.128 beat v11.129. That is exactly what happened on 2026-08-04, and
    # it silently launched the previous release while the title bar said so and
    # nobody looked. Restoring or re-copying an old folder would break it the
    # same way.
    $target = (Get-ChildItem -Path $root -Directory -Filter 'WINK_Lab_Tools_v*_Current_Files' |
               ForEach-Object {
                   if ($_.Name -match 'v(\d+)\.(\d+)') {
                       [pscustomobject]@{
                           Path  = $_.FullName
                           Major = [int]$Matches[1]
                           Minor = [int]$Matches[2]
                       }
                   }
               } |
               Sort-Object Major, Minor -Descending |
               Select-Object -First 1).Path
}
if (-not $target) {
    Write-Host "No WINK_Lab_Tools_v*_Current_Files folder was found next to this launcher."
    Start-Sleep -Seconds 6
    exit 1
}

$bat = Join-Path $target 'Launch_Lab_Hub.bat'
if (-not (Test-Path $bat)) {
    Write-Host "Found $target but it has no Launch_Lab_Hub.bat."
    Start-Sleep -Seconds 6
    exit 1
}
Write-Host ("Launching latest WINK: {0}" -f (Split-Path -Leaf $target))
Start-Process -FilePath $bat -WorkingDirectory $target
