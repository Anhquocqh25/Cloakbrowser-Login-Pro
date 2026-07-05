$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectDir ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Application environment is missing. Run .\setup.ps1 first."
}

Push-Location $ProjectDir
try {
    & $Python main.py
}
finally {
    Pop-Location
}
