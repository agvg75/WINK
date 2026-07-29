param([ValidateSet('online','offline','both')][string]$Mode='both')
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$Here=Split-Path -Parent $MyInvocation.MyCommand.Path
$Source=Join-Path $Here 'staged'
$Installer=Join-Path $Here 'installer'
$Out=Join-Path $Here 'distribution\installers'
$Version=(Get-Content -Raw (Join-Path $Source 'app\release_info.json')|ConvertFrom-Json).app_version
$Exclude=@('tests','archive','distribution','.venv','__pycache__')
New-Item -ItemType Directory -Force -Path $Out|Out-Null

function Build-Package([string]$Name,[bool]$IncludeThirdParty){
  $Stage=Join-Path $Out $Name
  if(Test-Path $Stage){Remove-Item -LiteralPath $Stage -Recurse -Force}
  New-Item -ItemType Directory -Force -Path $Stage|Out-Null
  foreach($f in @('Install_Lab_Tools.bat','Install_Lab_Tools.ps1','Uninstall_Lab_Tools.bat','STUDENT_README.txt','requirements-lock.txt')){
    Copy-Item -LiteralPath (Join-Path $Installer $f) -Destination $Stage -Force
  }
  "WINK $Version" | Set-Content -LiteralPath (Join-Path $Stage 'PACKAGE_VERSION.txt') -Encoding UTF8
  # App payload -> LabTools\ (same exclusions as the update package). Use robocopy
  # so the excluded dirs (e.g. deep tests\ support bundles) are skipped DURING the
  # copy - Copy-Item copies everything first and trips over Windows MAX_PATH.
  $Payload=Join-Path $Stage 'LabTools'
  $rc=@($Source,$Payload,'/E','/NFL','/NDL','/NJH','/NP','/R:1','/W:1','/XD')+$Exclude
  & robocopy @rc | Out-Null
  $rcExit=$LASTEXITCODE
  if($rcExit -ge 8){throw "robocopy failed copying the app payload (exit $rcExit)"}
  # robocopy returns non-zero even on success (1 = files copied). Left as-is it
  # becomes the script's exit code and GitHub Actions' pwsh marks the step failed.
  $global:LASTEXITCODE=0
  if($IncludeThirdParty){
    Copy-Item -LiteralPath (Join-Path $Installer 'third_party') -Destination (Join-Path $Stage 'third_party') -Recurse
  }
  $Zip=Join-Path $Out ("$Name.zip")
  if(Test-Path $Zip){Remove-Item -LiteralPath $Zip -Force}
  # Third-party payload is already-compressed (zips/wheels), so Fastest saves time
  # for no size gain; the online (source-only) package benefits from Optimal.
  $Level=if($IncludeThirdParty){'Fastest'}else{'Optimal'}
  Compress-Archive -LiteralPath $Stage -DestinationPath $Zip -CompressionLevel $Level
  Remove-Item -LiteralPath $Stage -Recurse -Force
  $mb=[math]::Round((Get-Item $Zip).Length/1MB,1)
  Write-Output "Built $Zip ($mb MB)"
}

if($Mode -eq 'online' -or $Mode -eq 'both'){ Build-Package "WINK_Installer_Online_v$Version" $false }
if($Mode -eq 'offline' -or $Mode -eq 'both'){ Build-Package "WINK_Installer_Offline_v$Version" $true }
# Ensure a clean exit code so CI (pwsh) does not inherit robocopy's non-zero success.
exit 0
