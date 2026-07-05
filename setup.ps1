$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating Python 3.11 environment..."
    py -3.11 -m venv (Join-Path $ProjectDir ".venv")
}

Write-Host "Installing application dependencies..."
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r (Join-Path $ProjectDir "requirements.txt")
Write-Host "Setup complete. Run .\run.ps1 to open CloakBrowser Login."
