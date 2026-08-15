param(
    [switch]$Install,
    [switch]$InitDb
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"
$LogDir = Join-Path $Root "tmp\logs"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Test-PortInUse {
    param([int]$Port)

    $connection = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
        Where-Object { $_.State -eq "Listen" } |
        Select-Object -First 1

    return $null -ne $connection
}

function Assert-Command {
    param([string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Command '$Name' was not found. Please install it or add it to PATH."
    }
}

function Start-HomeFlowProcess {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory,
        [int]$Port,
        [string]$LogPrefix
    )

    if (Test-PortInUse -Port $Port) {
        Write-Host "[$Name] port $Port is already in use, skip starting."
        return
    }

    $stdoutLog = Join-Path $LogDir "$LogPrefix.out.log"
    $stderrLog = Join-Path $LogDir "$LogPrefix.err.log"
    $process = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -WindowStyle Hidden `
        -PassThru

    $pidFile = Join-Path $LogDir "$LogPrefix.pid"
    Set-Content -Path $pidFile -Value $process.Id -Encoding ASCII

    Write-Host "[$Name] started on port $Port. PID: $($process.Id)"
    Write-Host "[$Name] logs: $stdoutLog / $stderrLog"
}

Assert-Command "python"
Assert-Command "node"
Assert-Command "npm"

if ($Install) {
    Write-Host "[frontend] installing npm dependencies..."
    Push-Location $FrontendDir
    npm install
    Pop-Location

    Write-Host "[backend] installing python dependencies..."
    Push-Location $BackendDir
    python -m pip install -r requirements.txt
    Pop-Location
}

if ($InitDb) {
    Write-Host "[backend] initializing database..."
    Push-Location $BackendDir
    python scripts/init_db.py
    Pop-Location
}

Start-HomeFlowProcess `
    -Name "backend" `
    -FilePath "python" `
    -ArgumentList @("-m", "uvicorn", "app.main:app", "--reload", "--host", "0.0.0.0", "--port", "8000") `
    -WorkingDirectory $BackendDir `
    -Port 8000 `
    -LogPrefix "backend"

Start-HomeFlowProcess `
    -Name "pc" `
    -FilePath "npm.cmd" `
    -ArgumentList @("run", "dev", "--", "--host", "0.0.0.0", "--port", "5173") `
    -WorkingDirectory $FrontendDir `
    -Port 5173 `
    -LogPrefix "frontend-pc"

Start-HomeFlowProcess `
    -Name "h5" `
    -FilePath "npm.cmd" `
    -ArgumentList @("run", "h5:dev", "--", "--host", "0.0.0.0", "--port", "5172") `
    -WorkingDirectory $FrontendDir `
    -Port 5172 `
    -LogPrefix "frontend-h5"

Write-Host ""
Write-Host "home-flow local services:"
Write-Host "  Backend: http://localhost:8000"
Write-Host "  PC:      http://localhost:5173"
Write-Host "  H5:      http://localhost:5172"
Write-Host ""
Write-Host "Stop services with: .\scripts\stop-local.ps1"
