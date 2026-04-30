#Requires -Version 5.1
$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
$DashboardUrl = 'http://localhost:3002'
$BackendUrl = 'http://localhost:8001/health'
$DockerTimeout = 180
$ServiceTimeout = 180

function Step($msg) {
  Write-Host "==> $msg" -ForegroundColor Cyan
}

function HasCmd($cmd) {
  $null -ne (Get-Command $cmd -ErrorAction SilentlyContinue)
}

function DockerReady {
  try {
    docker info 2>$null | Out-Null
    return $true
  } catch {
    return $false
  }
}

function FindDockerDesktop {
  $candidates = @(
    "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe",
    "$env:LOCALAPPDATA\Programs\Docker\Docker\Docker Desktop.exe"
  )

  foreach ($candidate in $candidates) {
    if (Test-Path $candidate) {
      return $candidate
    }
  }

  return $null
}

function StartDockerDesktop {
  if (DockerReady) {
    Step "Docker daemon deja disponible"
    return
  }

  $exe = FindDockerDesktop
  if (-not $exe) {
    Write-Error "Docker Desktop introuvable. Installe-le puis relance."
    exit 1
  }

  Step "Demarrage de Docker Desktop"
  Start-Process $exe

  Step "Attente du daemon Docker (max ${DockerTimeout}s)"
  $start = [int][double]::Parse((Get-Date -UFormat %s))
  while ($true) {
    if (DockerReady) {
      Step "Docker daemon pret"
      return
    }

    $now = [int][double]::Parse((Get-Date -UFormat %s))
    if (($now - $start) -ge $DockerTimeout) {
      Write-Error "Timeout Docker."
      exit 1
    }

    Start-Sleep 4
  }
}

function WaitHttp($url, $timeout) {
  $start = [int][double]::Parse((Get-Date -UFormat %s))
  while ($true) {
    try {
      $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
      if ($response.StatusCode -lt 400) {
        return $true
      }
    } catch {}

    $now = [int][double]::Parse((Get-Date -UFormat %s))
    if (($now - $start) -ge $timeout) {
      return $false
    }

    Start-Sleep 3
  }
}

function ShowFailureContext {
  Write-Host ""
  Write-Host "Etat Docker Compose :" -ForegroundColor Yellow
  docker compose ps

  Write-Host ""
  Write-Host "Derniers logs :" -ForegroundColor Yellow
  docker compose logs --tail=60 backend dashboard simulator
}

Set-Location $ProjectRoot

if (-not (HasCmd 'docker')) {
  Write-Error "Docker introuvable. Installe Docker Desktop puis relance."
  exit 1
}

Step "Verification Docker Desktop"
StartDockerDesktop

Step "Validation de la configuration"
docker compose config | Out-Null

Step "Construction et demarrage de la stack EPicare Palace"
docker compose up --build -d

Step "Attente du backend (port 8001)"
if (-not (WaitHttp $BackendUrl $ServiceTimeout)) {
  ShowFailureContext
  Write-Error "Le backend ne repond pas sur $BackendUrl"
  exit 1
}

Step "Attente du dashboard (port 3002)"
if (-not (WaitHttp $DashboardUrl $ServiceTimeout)) {
  ShowFailureContext
  Write-Error "Le dashboard ne repond pas sur $DashboardUrl"
  exit 1
}

Write-Host ""
Write-Host "EPicare Palace - Stack prete" -ForegroundColor Green
Write-Host "Dashboard soignant : http://localhost:3002" -ForegroundColor Green
Write-Host "API backend        : http://localhost:8001" -ForegroundColor Green
Write-Host "Docs API           : http://localhost:8001/docs" -ForegroundColor Green
Write-Host ""
Write-Host "Logs en direct : docker compose logs -f --tail=200"
Write-Host "Arret complet  : docker compose down"
Write-Host ""

Step "Ouverture du dashboard"
Start-Process $DashboardUrl
