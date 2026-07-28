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
 min_runtime_version='1.0.0'
 changelog='v11.111 GitHub-based auto-update. The in-app updater can now fetch updates from the WINK GitHub releases (agvg75/WINK) when the lab L: drive is not reachable, so people running WINK off the lab network get the same one-click update prompt as lab machines. Lab machines still update from L: first; GitHub is only the fallback. No tool behaviour changed. Prior: v11.110 Pharynx morphometry and single-channel GCaMP now use the shared cockpit layout: inputs and the numbered workflow buttons on the left, a first-frame preview and status in the center, process hood on the right, with the logo theme. Their calibration, template placement, feasibility pass, extraction, neuron tracking, and review are all unchanged. This completes the migration of the safe form tools. Prior: v11.109 Three more tools moved onto the shared cockpit layout with the logo theme: Dynamic egg laying, Population tap response / habituation, and Neuromuscular paralysis pharmacology now have their inputs and buttons on the left and instructions/status in the center. Their calibration, reference-egg marking, tap detection, prod-observation review, and analysis are all unchanged. Prior: v11.108 Egg counting migrated to the shared cockpit layout: the source, frame, calibration-distance, tolerance, and worm-length fields plus the Calibrate, Draw-region, Mark-egg, and Detect/Review buttons are on the left; the chosen frame and the advanced egg-detection dials are in the center; the process hood is on the right. Calibration, ROI drawing, egg marking, detection, and the live-refresh review behave exactly as before. Prior: v11.107 The tool windows now carry the WINK logo colors too: the cockpit tools (myocyte morphometry, defecation/pBoc, population swimming, basal slowing), pharyngeal pumping, egg counting, and the shared review / ROI-drawing windows all use the slate-blue and sage-green palette with a sage accent stripe, matching the hub. This is a visual theme only - no tool behaviour changed. Prior: v11.106 Hub restyled to the WINK logo colors: the maroon is replaced by the logo slate-blue for the wordmark and headings, with a sage-green top accent stripe. Added Illinois State University under Molecular Neuroscience Lab in the brand. Individual tool windows are unchanged (neutral). Prior: v11.105 Population basal slowing now runs on the shared cockpit layout: the image folder, FPS, scale, area gates, before/after windows, buffer, and fraction inputs plus the Draw-ROIs, Undo, Clear, Analyze, and Load/Save-ROIs buttons are on the left; the first frame of the chosen folder and the status are in the center; the process hood is on the right, with the c and h panel toggles. It also gains a Calibrate scale (scope / bar) button that opens the shared in-window scale panel. ROI drawing, tracking, track review, and the paired lawn-entry review are unchanged. Close and reopen the tool to update. Prior: v11.104 made the scale calibration in-window across the cockpit tools.'
}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $Updates 'update_manifest.json') -Encoding UTF8
Remove-Item -LiteralPath $Stage -Recurse -Force
Write-Output "Built application update: $Zip"
