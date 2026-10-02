param(
    [int]$Seconds = 120,
    [int]$VerifySeconds = 30,
    [string[]]$Entity = @(),
    [string]$ArduinoCli = 'arduino-cli',
    [switch]$Build,
    [switch]$Pilot
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location -LiteralPath $projectRoot
try {
    if ($Pilot -and $Entity.Count) { throw 'Choose -Pilot or -Entity, not both.' }
    $selectionArgs = @()
    if ($Pilot) { $selectionArgs += '--pilot' }
    foreach ($name in $Entity) { $selectionArgs += @('--entity',$name) }
    $env:WOKWI_LAB_HOST = 'mqtt'
    docker compose -p ehpad-hardware -f docker-compose.hardware-lab.yml up -d --build
    if ($LASTEXITCODE -ne 0) { throw 'Docker startup failed.' }
    if ($Build) {
        python firmware/all_sensors/tools/export_collective.py
        if ($LASTEXITCODE -ne 0) { throw 'Collective export failed.' }
        python firmware/all_sensors/tools/build_collective.py --cli $ArduinoCli @selectionArgs
        if ($LASTEXITCODE -ne 0) { throw 'Collective compilation failed.' }
    }
    $launcherArgs = @('firmware/all_sensors/tools/run_collective.py','--seconds',"$Seconds",'--verify-seconds',"$VerifySeconds")
    $launcherArgs += $selectionArgs
    $ready = $false
    for ($attempt = 0; $attempt -lt 15; $attempt++) {
        try {
            $snapshot = Invoke-RestMethod 'http://localhost:8005/api/hardware/snapshot?source=wokwi' -TimeoutSec 3
            if ($snapshot.source -eq 'wokwi') { $ready = $true; break }
        } catch { }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) { throw 'Acquisition backend did not become ready; no Wokwi simulation started.' }
    python @launcherArgs
    if ($LASTEXITCODE -ne 0) { throw 'Collective run did not pass verification. Read build/collective-runtime/status.json.' }
} finally {
    Pop-Location
}
