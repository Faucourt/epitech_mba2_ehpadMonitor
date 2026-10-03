param([switch]$Full, [switch]$Check, [switch]$Browser)
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    if ($Full -and $Browser) { throw 'Choisir -Full ou -Browser, pas les deux.' }
    python firmware/all_sensors/tools/run_collective.py --pilot --check
    if ($LASTEXITCODE -ne 0) { throw 'Les firmwares du pilote sont absents ou perimes.' }
    $token = $env:WOKWI_CLI_TOKEN
    if (-not $token) { $token = [Environment]::GetEnvironmentVariable('WOKWI_CLI_TOKEN','User') }
    Write-Host ('Jeton Wokwi CI configure : ' + [bool]$token)
    Write-Host 'Dashboard : http://localhost:3005/?source=wokwi'
    if ($Check) { return }
    if (($Full -or $token) -and -not $Browser) {
        if (-not $token) { throw 'Configurer WOKWI_CLI_TOKEN dans les variables utilisateur Windows pour les 3 patients et les 20 zones ensemble.' }
        if ($token -notmatch '^wok_[A-Za-z0-9_-]{40}$') { throw 'Le format du jeton Wokwi CI est invalide.' }
        $activeFleet = Get-CimInstance Win32_Process | Where-Object {
            $_.Name -match '^python' -and $_.CommandLine -match 'run_collective\.py' -and $_.CommandLine -match '--pilot'
        }
        if ($activeFleet) { Write-Host 'Les 23 simulations sont deja supervisees. Voir http://localhost:3005/?source=wokwi'; return }
        # Avoid two simulators publishing different boots for the same residents.
        $oldStatus = Join-Path $PSScriptRoot 'build/browser-pilot/status.json'
        if (Test-Path -LiteralPath $oldStatus) {
            $old = Get-Content -LiteralPath $oldStatus -Raw | ConvertFrom-Json
            $owned = Get-CimInstance Win32_Process -Filter "ProcessId = $($old.pid)" -ErrorAction SilentlyContinue
            if ($owned -and $owned.CommandLine -like '*browser_pilot.cjs*') {
                taskkill /PID $owned.ProcessId /T /F | Out-Null
                if ($LASTEXITCODE -ne 0) { throw 'Arret de la passerelle navigateur impossible.' }
            }
        }
        & ./firmware/all_sensors/Start-Collective.ps1 -Pilot -Seconds 0
        return
    }
    Write-Host 'Mode navigateur : R001, R002, R003 et entree. Les 19 autres zones restent hors ligne.'
    $statusFile = Join-Path $PSScriptRoot 'build/browser-pilot/status.json'
    if (Test-Path -LiteralPath $statusFile) {
        $status = Get-Content -LiteralPath $statusFile -Raw | ConvertFrom-Json
        $existing = Get-CimInstance Win32_Process -Filter "ProcessId = $($status.pid)" -ErrorAction SilentlyContinue
        if ($existing -and $existing.CommandLine -like '*browser_pilot.cjs*') {
            Write-Host 'La passerelle navigateur est deja lancee.'
            return
        }
    }
    docker compose -p ehpad-hardware -f docker-compose.hardware-lab.yml up -d
    if ($LASTEXITCODE -ne 0) { throw 'Echec du demarrage Docker.' }
    $null = Invoke-RestMethod 'http://localhost:8005/health' -TimeoutSec 15
    python -c 'import paho.mqtt.client'
    if ($LASTEXITCODE -ne 0) { throw 'Installer les dependances : python -m pip install -r firmware/all_sensors/requirements-collective.txt' }
    $deps = Join-Path $PSScriptRoot 'build/browser-deps'
    if (-not (Test-Path -LiteralPath (Join-Path $deps 'node_modules/playwright'))) {
        npm install --prefix $deps playwright@1.58.2 --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw 'Installation de Playwright impossible.' }
    }
    node (Join-Path $deps 'node_modules/playwright/cli.js') install chromium
    if ($LASTEXITCODE -ne 0) { throw 'Installation du navigateur de test impossible.' }
    $previousNodePath = $env:NODE_PATH
    try {
        $env:NODE_PATH = Join-Path $deps 'node_modules'
        node firmware/all_sensors/tools/browser_pilot.cjs
        if ($LASTEXITCODE -ne 0) { throw 'La passerelle est arretee. Consulter build/browser-pilot/status.json.' }
    } finally { $env:NODE_PATH = $previousNodePath }
} finally { Pop-Location }
