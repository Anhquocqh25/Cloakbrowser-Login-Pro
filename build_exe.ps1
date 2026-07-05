$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectDir ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $PythonCommand) {
        throw "Python was not found. Create .venv or install Python first."
    }
    $Python = $PythonCommand.Source
}

$PreviousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath (Join-Path $ProjectDir "dist") `
    --workpath (Join-Path $ProjectDir "build") `
    (Join-Path $ProjectDir "CloakBrowser Login.spec")
$BuildExitCode = $LASTEXITCODE
$ErrorActionPreference = $PreviousErrorActionPreference

if ($BuildExitCode -ne 0) {
    throw "PyInstaller build failed with exit code $BuildExitCode."
}

$Exe = Join-Path $ProjectDir "dist\CloakBrowser Login\CloakBrowser Login.exe"
if (-not (Test-Path -LiteralPath $Exe)) {
    throw "Build completed but the EXE was not found: $Exe"
}

Write-Host "Build complete: $Exe"
