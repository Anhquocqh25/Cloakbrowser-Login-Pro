param(
    [string]$ReleaseRoot = ""
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ConfigText = Get-Content -LiteralPath (Join-Path $ProjectDir "config.py") -Raw
$VersionMatch = [regex]::Match($ConfigText, 'APP_VERSION\s*=\s*"([^"]+)"')
if (-not $VersionMatch.Success) { throw "Could not read APP_VERSION from config.py" }
$Version = $VersionMatch.Groups[1].Value
if (-not $ReleaseRoot) { $ReleaseRoot = Join-Path (Split-Path -Parent $ProjectDir) "release" }
$ReleaseRoot = [System.IO.Path]::GetFullPath($ReleaseRoot)
$AppSourceDir = Join-Path $ReleaseRoot "CloakBrowser Login $Version"
$OutputDir = $ReleaseRoot
$Script = Join-Path $ProjectDir "installer\cloakbrowser-login-pro.iss"

$Candidates = @(
    (Join-Path (Split-Path -Parent $ProjectDir) "tools\Inno Setup 6\ISCC.exe"),
    "D:\Vs Code Ai Agent\CloakBrowser Login\tools\Inno Setup 6\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)

$ISCC = $Candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $ISCC) {
    throw "Inno Setup 6 compiler was not found. Install Inno Setup or place it in ..\tools\Inno Setup 6."
}

if (-not (Test-Path -LiteralPath $AppSourceDir)) {
    throw "App release folder was not found: $AppSourceDir"
}

New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

& $ISCC "/DMyAppVersion=$Version" "/DAppSourceDir=$AppSourceDir" "/DOutputDir=$OutputDir" $Script
if ($LASTEXITCODE -ne 0) {
    throw "Installer build failed with exit code $LASTEXITCODE."
}

$Setup = Join-Path $OutputDir "CloakBrowser-Login-Pro-Setup-$Version-Windows.exe"
if (-not (Test-Path -LiteralPath $Setup)) {
    throw "Installer finished but the output file was not found: $Setup"
}

Write-Host "Installer build complete: $Setup"
