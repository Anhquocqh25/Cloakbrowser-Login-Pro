param(
    [string]$ReleaseRoot = "",
    [string]$Notes = "Stability and user experience improvements."
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ConfigText = Get-Content -LiteralPath (Join-Path $ProjectDir "config.py") -Raw
$VersionMatch = [regex]::Match($ConfigText, 'APP_VERSION\s*=\s*"([^"]+)"')
if (-not $VersionMatch.Success) { throw "Could not read APP_VERSION from config.py" }
$Version = $VersionMatch.Groups[1].Value
if (-not $ReleaseRoot) { $ReleaseRoot = Join-Path (Split-Path -Parent $ProjectDir) "release" }
$ReleaseRoot = [System.IO.Path]::GetFullPath($ReleaseRoot)
$Target = [System.IO.Path]::GetFullPath((Join-Path $ReleaseRoot "CloakBrowser Login $Version"))
if (-not $Target.StartsWith($ReleaseRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Release target escaped the release root."
}

& (Join-Path $ProjectDir "build_exe.ps1")
$Built = Join-Path $ProjectDir "dist\CloakBrowser Login"
if (-not (Test-Path -LiteralPath (Join-Path $Built "CloakBrowser Login.exe"))) { throw "Built app is incomplete." }
New-Item -ItemType Directory -Path $ReleaseRoot -Force | Out-Null
if (Test-Path -LiteralPath $Target) { Remove-Item -LiteralPath $Target -Recurse -Force }
Copy-Item -LiteralPath $Built -Destination $Target -Recurse -Force

$Portable = Join-Path $ReleaseRoot "CloakBrowser-Login-$Version-Windows.zip"
if (Test-Path -LiteralPath $Portable) { Remove-Item -LiteralPath $Portable -Force }
Compress-Archive -Path $Target -DestinationPath $Portable -CompressionLevel Optimal
& (Join-Path $ProjectDir "build_installer.ps1") -ReleaseRoot $ReleaseRoot

$Python = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$PythonArgs = @()
if (-not (Test-Path -LiteralPath $Python)) {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($PythonCommand) {
        $Python = $PythonCommand.Source
    } else {
        $PythonCommand = Get-Command py -ErrorAction SilentlyContinue
        if (-not $PythonCommand) { throw "Python was not found. Create .venv or install Python first." }
        $Python = $PythonCommand.Source
        $PythonArgs = @("-3")
    }
}
& $Python @PythonArgs (Join-Path $ProjectDir "tools\update_release_manifest.py") --version $Version --release-root $ReleaseRoot --notes $Notes
if ($LASTEXITCODE -ne 0) { throw "Could not create release manifest." }
Write-Host "Release $Version complete: $ReleaseRoot"
