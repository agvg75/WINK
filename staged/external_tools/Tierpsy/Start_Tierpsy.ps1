param(
    [Parameter(Mandatory=$true)]
    [string]$DataPath
)
$ErrorActionPreference = 'Stop'
$Docker = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
$VcXsrv = 'C:\Program Files\VcXsrv\vcxsrv.exe'
if (-not (Test-Path -LiteralPath $Docker)) {
    throw 'Docker Desktop is not installed.'
}
if (-not (Test-Path -LiteralPath $VcXsrv)) {
    throw 'VcXsrv is not installed.'
}
$ResolvedData = (Resolve-Path -LiteralPath $DataPath).Path
& $Docker info | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw 'Docker engine is not running. Start Docker Desktop and try again.'
}
if (-not (Get-Process vcxsrv -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $VcXsrv -ArgumentList ':0','-multiwindow','-wgl','-ac','-silent-dup-error'
}
& $Docker run --interactive --tty --rm `
    --env DISPLAY=host.docker.internal:0 `
    --volume "${ResolvedData}:/DATA/local_drive" `
    --sysctl net.ipv6.conf.all.disable_ipv6=0 `
    --hostname tierpsydocker `
    tierpsy/tierpsy-tracker
if ($LASTEXITCODE -ne 0) {
    throw "Tierpsy container exited with code $LASTEXITCODE."
}
