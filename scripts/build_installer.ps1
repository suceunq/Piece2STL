param([switch]$SkipAppBuild)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not $SkipAppBuild) {
    & (Join-Path $PSScriptRoot "build_windows.ps1")
    if ($LASTEXITCODE -ne 0) { throw "La construction de l'application a échoué." }
}

$isccCandidates = @(
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
)
$iscc = $isccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 est requis pour créer l'installateur." }

& $iscc (Join-Path $root "installer\Piece2STL.iss")
if ($LASTEXITCODE -ne 0) { throw "La création de l'installateur a échoué." }

$installer = Get-Item (Join-Path $root "dist\installer\Piece2STL-Setup-0.4.0.exe")
$hash = (Get-FileHash -Algorithm SHA256 $installer.FullName).Hash.ToLowerInvariant()
Set-Content -Path ($installer.FullName + ".sha256") -Value "$hash  $($installer.Name)" -Encoding ascii
Write-Host "Installateur créé : $($installer.FullName)"
