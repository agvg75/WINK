$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Root=Join-Path $env:LOCALAPPDATA 'AGVGLab';$App=Join-Path $Root 'LabTools';$RuntimeRoot=Join-Path $Root 'runtime_layer';$PythonRoot=Join-Path $RuntimeRoot 'python';$Runtime=Join-Path $RuntimeRoot 'venv';$Fiji=Join-Path $RuntimeRoot 'Fiji.app';$VersionFile=Join-Path $Root 'version.json'
$Log=Join-Path $PSScriptRoot 'install_log.txt';$Payload=Join-Path $PSScriptRoot 'LabTools';$Requirements=Join-Path $PSScriptRoot 'requirements-lock.txt';$ThirdParty=Join-Path $PSScriptRoot 'third_party';$Wheelhouse=Join-Path $ThirdParty 'wheelhouse';$Manifest=Join-Path $ThirdParty 'SHA256SUMS.json'
$PythonUrl='https://www.python.org/ftp/python/3.13.14/python-3.13.14-amd64.exe';$PythonSha256='c54d9b9bbb8a36e6489363ddd01139707fd781d72f1f9e90c7ec65d0061368e0'
$FijiUrl='https://downloads.imagej.net/fiji/latest/fiji-latest-win64-jdk.zip'
Start-Transcript -Path $Log -Force|Out-Null
try {
 Write-Host 'AGVG Lab Tools - complete student installation' -ForegroundColor Cyan
 if(-not [Environment]::Is64BitOperatingSystem){throw 'A 64-bit Windows computer is required.'}
 if(-not(Test-Path(Join-Path $Payload 'app\lab_hub.py'))){throw 'LabTools payload missing. Extract the entire ZIP before running setup.'}
 New-Item -ItemType Directory -Force -Path $Root|Out-Null
 $InstallMode=if(Test-Path $ThirdParty){'offline-bundled'}else{'online-bootstrap'};Write-Host "Installation mode: $InstallMode"
 if(Test-Path $Manifest){
  $Expected=Get-Content -LiteralPath $Manifest -Raw|ConvertFrom-Json
  foreach($Property in $Expected.PSObject.Properties){$File=Join-Path $ThirdParty $Property.Name;if(-not(Test-Path $File)){throw "Bundled dependency missing: $($Property.Name)"};$Hash=(Get-FileHash -Algorithm SHA256 -LiteralPath $File).Hash.ToLowerInvariant();if($Hash-ne ([string]$Property.Value).ToLowerInvariant()){throw "Bundled dependency checksum mismatch: $($Property.Name)"}}
 }
 Write-Host '[1/7] Installing Lab Tools files...'
 if(Test-Path $App){$Backup=Join-Path $Root 'LabTools.previous';if(Test-Path $Backup){Remove-Item -LiteralPath $Backup -Recurse -Force};Move-Item -LiteralPath $App -Destination $Backup;Write-Host "Previous application backed up to $Backup"}
 Copy-Item -LiteralPath $Payload -Destination $App -Recurse
 Write-Host '[2/7] Installing private Python runtime...'
 New-Item -ItemType Directory -Force -Path $RuntimeRoot|Out-Null
 $PythonExe=Get-ChildItem -LiteralPath $PythonRoot -Filter 'python.exe' -File -Recurse -ErrorAction SilentlyContinue|Select-Object -First 1 -ExpandProperty FullName
 if(-not $PythonExe){
  $BundledRuntime=Join-Path $ThirdParty 'python-runtime.zip'
  if(Test-Path $BundledRuntime){
   if(Test-Path $PythonRoot){Remove-Item -LiteralPath $PythonRoot -Recurse -Force}
   New-Item -ItemType Directory -Force -Path $PythonRoot|Out-Null
   Expand-Archive -LiteralPath $BundledRuntime -DestinationPath $PythonRoot -Force
  }else{
   $Exe=Join-Path $env:TEMP 'nike-python-bootstrap.exe'
   if(-not(Test-Path $Exe)){Invoke-WebRequest -Uri $PythonUrl -OutFile $Exe -UseBasicParsing}
   $Hash=(Get-FileHash -Algorithm SHA256 -LiteralPath $Exe).Hash.ToLowerInvariant();if($Hash-ne $PythonSha256){throw "Python checksum mismatch: $Hash"}
   $Sig=Get-AuthenticodeSignature -LiteralPath $Exe;if($Sig.Status-ne'Valid'-or $Sig.SignerCertificate.Subject-notmatch'Python Software Foundation'){throw 'Python digital signature is invalid.'}
   $Args=@('/quiet','InstallAllUsers=0',"TargetDir=`"$PythonRoot`"",'Include_pip=1','Include_tcltk=1','Include_launcher=0','Include_test=0','Include_doc=0','PrependPath=0','Shortcuts=0')
   $P=Start-Process -FilePath $Exe -ArgumentList $Args -Wait -PassThru;if($P.ExitCode-ne 0){throw "Python installer exit code $($P.ExitCode)"}
  }
  $PythonExe=Get-ChildItem -LiteralPath $PythonRoot -Filter 'python.exe' -File -Recurse -ErrorAction SilentlyContinue|Select-Object -First 1 -ExpandProperty FullName
 }
 if(-not $PythonExe){throw "Runtime step failed: Python payload did not produce python.exe beneath $PythonRoot. Send install_log.txt to VidalGadeaLab@gmail.com."}
 & $PythonExe --version
 if($LASTEXITCODE-ne 0){throw "Runtime step failed: interpreter is not executable at $PythonExe. Send install_log.txt to VidalGadeaLab@gmail.com."}
 $ResolvedPython=[IO.Path]::GetFullPath($PythonExe)
 Write-Host "Validated bundled interpreter: $ResolvedPython"
 Write-Host '[3/7] Installing scientific libraries...'
 if(Test-Path $Runtime){Remove-Item -LiteralPath $Runtime -Recurse -Force}
 & $ResolvedPython -m venv $Runtime;if($LASTEXITCODE-ne 0){throw "Could not create the private runtime using $ResolvedPython."}
 $RuntimePython=Join-Path $Runtime 'Scripts\python.exe'
 if(-not(Test-Path $RuntimePython)){throw "Libraries step failed: private interpreter is missing at $RuntimePython."}
 if(Test-Path $Wheelhouse){
  & $RuntimePython -m pip install --no-index --find-links $Wheelhouse --requirement $Requirements
 } else {
  & $RuntimePython -m pip install --upgrade pip
  & $RuntimePython -m pip install --requirement $Requirements
 }
 if($LASTEXITCODE-ne 0){throw 'A required Python library could not be installed.'}
 Write-Host '[4/7] Installing Fiji and bundled Java...'
 $FijiExe=Get-ChildItem -LiteralPath $Fiji -File -ErrorAction SilentlyContinue|Where-Object{$_.Name-in@('fiji-windows-x64.exe','ImageJ-win64.exe')}|Select-Object -First 1 -ExpandProperty FullName
 if(-not $FijiExe){
  $BundledFiji=Join-Path $ThirdParty 'fiji-win64-jdk.zip';$Zip=if(Test-Path $BundledFiji){$BundledFiji}else{Join-Path $env:TEMP 'agvg-fiji.zip'};$Extract=Join-Path $env:TEMP 'agvg-fiji-extract';if(-not(Test-Path $Zip)){Invoke-WebRequest -Uri $FijiUrl -OutFile $Zip -UseBasicParsing}
  if(Test-Path $Extract){Remove-Item -LiteralPath $Extract -Recurse -Force};Expand-Archive -LiteralPath $Zip -DestinationPath $Extract -Force
  $Found=Get-ChildItem -LiteralPath $Extract -File -Recurse|Where-Object{$_.Name-in@('fiji-windows-x64.exe','ImageJ-win64.exe')}|Select-Object -First 1;if(-not $Found){throw 'Official Fiji archive did not contain a recognized Windows launcher.'}
  if(Test-Path $Fiji){Remove-Item -LiteralPath $Fiji -Recurse -Force};Move-Item -LiteralPath $Found.Directory.FullName -Destination $Fiji
  $FijiExe=Join-Path $Fiji $Found.Name
 }
 Write-Host '[5/7] Installing AGVGLab Fiji menu files...'
 $Plugins=Join-Path $Fiji 'plugins\AGVGLab';New-Item -ItemType Directory -Force -Path $Plugins|Out-Null
 Copy-Item -LiteralPath (Join-Path $App 'tools\morphology\Myocyte_Morphometry.ijm') -Destination $Plugins -Force
 Copy-Item -LiteralPath (Join-Path $App 'tools\rgbcamp\fiji\WormRGBCaMPMap_v1.java') -Destination $Plugins -Force
 Copy-Item -LiteralPath (Join-Path $App 'tools\worm_kinematics\WormKinematics_patch.java') -Destination $Plugins -Force
 Write-Host '[6/7] Creating Desktop shortcuts...'
 if($env:NIKE_SKIP_SHORTCUTS-ne'1'){
  $Shell=New-Object -ComObject WScript.Shell;$Desk=[Environment]::GetFolderPath('Desktop')
  $S=$Shell.CreateShortcut((Join-Path $Desk 'AGVG Lab Tools.lnk'));$S.TargetPath=Join-Path $App 'Launch_Lab_Hub.bat';$S.WorkingDirectory=$App;$S.Description='AGVG Molecular Neuroscience Lab Tools';$S.Save()
  $S=$Shell.CreateShortcut((Join-Path $Desk 'Fiji - AGVG Lab.lnk'));$S.TargetPath=$FijiExe;$S.WorkingDirectory=$Fiji;$S.Save()
 }else{Write-Host 'Shortcut creation skipped by clean-machine validation.'}
 Write-Host '[7/7] Running diagnostics...'
 & $RuntimePython (Join-Path $App 'app\system_check.py') --quiet;if($LASTEXITCODE-ne 0){throw 'Installation diagnostics failed.'}
 $Release=Get-Content -LiteralPath (Join-Path $App 'app\release_info.json') -Raw|ConvertFrom-Json
 [ordered]@{installed_app_version=[string]$Release.app_version;installed_runtime_version=[string]$Release.runtime_version;resolved_python=$ResolvedPython;installed_utc=(Get-Date -Format o);mode=$InstallMode}|ConvertTo-Json|Set-Content -LiteralPath $VersionFile -Encoding UTF8
 Write-Host 'Installation completed successfully.' -ForegroundColor Green
} catch {Write-Host "INSTALLATION FAILED: $($_.Exception.Message)" -ForegroundColor Red;Write-Host "Log: $Log";Stop-Transcript|Out-Null;exit 1}
Stop-Transcript|Out-Null;exit 0
