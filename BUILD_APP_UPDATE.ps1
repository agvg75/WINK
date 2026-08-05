$ErrorActionPreference='Stop'
$Here=Split-Path -Parent $MyInvocation.MyCommand.Path
$Source=Join-Path $Here 'staged'
$Updates=Join-Path $Here 'distribution\updates'
$Version=(Get-Content -Raw (Join-Path $Source 'app\release_info.json') | ConvertFrom-Json).app_version
$Exclude=@('tests','archive','distribution','.venv','__pycache__')
New-Item -ItemType Directory -Force -Path $Updates|Out-Null
$Stage=Join-Path $Updates 'LabTools'
if(Test-Path $Stage){Remove-Item -LiteralPath $Stage -Recurse -Force}
Copy-Item -LiteralPath $Source -Destination $Stage -Recurse
Get-ChildItem -LiteralPath $Stage -Directory -Recurse -Force|
 Where-Object{$_.Name-in$Exclude}|Sort-Object FullName -Descending|
 Remove-Item -Recurse -Force
$Zip=Join-Path $Updates "WINK_App_Update_v$Version.zip"
if(Test-Path $Zip){Remove-Item -LiteralPath $Zip -Force}
Compress-Archive -LiteralPath $Stage -DestinationPath $Zip -CompressionLevel Optimal
$Hash=(Get-FileHash -Algorithm SHA256 -LiteralPath $Zip).Hash.ToLowerInvariant()
[ordered]@{
 app_version=$Version
 package_filename=(Split-Path -Leaf $Zip)
 package_sha256=$Hash
 # 1.1.0 adds magpylib to the environment. The updater swaps app files only -
 # it never runs pip - so a machine on runtime 1.0.0 that took this update
 # would get magnetotaxis code whose dependency is still absent. Gating it
 # sends those machines to Setup_Lab_Tools.bat instead of half-updating them.
 # UNCHANGED for 11.125: that release adds no libraries, so a machine already
 # on 1.1.0 takes it with a click and needs no second visit to the installer.
 min_runtime_version='1.1.0'
 changelog='v11.134 Interface fixes and honest pBoc counts. The Hub control row now WRAPS when the window is narrowed instead of silently dropping the buttons that no longer fit. Tk pack does not wrap, so widgets were not clipped or shrunk but simply absent, leaving a tidy row with things missing from it and nothing to signal the loss. Tool descriptions follow the width of their pane rather than a fixed wrap set once, so they no longer overflow when the pane is narrowed or waste space when it is widened. Windows have a minimum size, because wrapping keeps controls reachable and a floor keeps them legible. An optional LCARS theme can be switched on from the Hub: off by default, remembered per machine, and fully reversible. The defecation detector now REPORTS ITS OWN MERGES. Contractions closer than five seconds were being folded into one another silently, so an animal with a fast cycle was undercounted with nothing in the output to say so. merge_report now states how many were absorbed and what the true upper bound on the count therefore is, which periodicity alone cannot reveal, because an event absorbed beside a neighbour leaves the interval structure untouched. A two-pass rescan re-examines only the windows where the rhythm of that animal says an event went missing, so a regular animal is never rescanned and nothing about it can change. That is what makes it safe across genotypes, where loosening a global threshold would not be. Per-segment curvature is now measured over a baseline that is a fixed fraction of body length rather than the handful of midline points inside each segment, which was reporting tracing jitter rather than posture. A hand correction in the neuron tracker propagates to the frames after it instead of fixing the displayed frame alone. Two tools that were built but never reachable are now in the Hub: pharynx template placement, and GCaMP segmentation calibration.'
}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $Updates 'update_manifest.json') -Encoding UTF8
Remove-Item -LiteralPath $Stage -Recurse -Force
Write-Output "Built application update: $Zip"
