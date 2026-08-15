param(
    [int[]]$Ports = @(8000, 5173, 5172)
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root "tmp\logs"

function Stop-ProcessTree {
    param([int]$ProcessId)

    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" -ErrorAction SilentlyContinue
    foreach ($child in $children) {
        Stop-ProcessTree -ProcessId $child.ProcessId
    }

    try {
        $process = Get-Process -Id $ProcessId -ErrorAction Stop
        Stop-Process -Id $ProcessId -Force
        Write-Host "stopped PID $ProcessId ($($process.ProcessName))."
    } catch {
        Write-Host "PID $ProcessId is not running."
    }
}

if (Test-Path $LogDir) {
    Get-ChildItem $LogDir -Filter "*.pid" -ErrorAction SilentlyContinue | ForEach-Object {
        $processIdText = Get-Content $_.FullName -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($processIdText -match "^\d+$") {
            Write-Host "[pid file] stopping $($_.Name)..."
            Stop-ProcessTree -ProcessId ([int]$processIdText)
        }
        Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
    }
}

foreach ($port in $Ports) {
    $connections = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue |
        Where-Object { $_.State -eq "Listen" }

    if (-not $connections) {
        Write-Host "[port $port] no listening process."
        continue
    }

    $processIds = $connections |
        Select-Object -ExpandProperty OwningProcess -Unique

    foreach ($processId in $processIds) {
        Write-Host "[port $port] stopping listening PID $processId..."
        Stop-ProcessTree -ProcessId $processId
    }
}
