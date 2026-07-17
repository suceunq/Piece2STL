$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "Environnement Python introuvable : $python"
}

& $python -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller manque. Installez requirements-build.txt."
}

Push-Location $root
try {
    & $python -m PyInstaller --noconfirm --clean "piece2stl.spec"
    if ($LASTEXITCODE -ne 0) {
        throw "La construction PyInstaller a échoué."
    }
    $distribution = Join-Path $root "dist\Piece2STL"
    Copy-Item (Join-Path $root "Installer Piece2STL.bat") $distribution -Force
    Copy-Item (Join-Path $root "install_windows.ps1") $distribution -Force
    Copy-Item (Join-Path $root "Installer IA Piece2STL.bat") $distribution -Force
    Copy-Item (Join-Path $root "scripts\setup_ai.ps1") $distribution -Force
    Copy-Item (Join-Path $root "README.md") $distribution -Force
    Copy-Item (Join-Path $root "RELEASE_NOTES.md") $distribution -Force
    $uv = (Get-Command uv.exe -ErrorAction Stop).Source
    Copy-Item $uv (Join-Path $distribution "uv.exe") -Force
    Write-Host "Distribution créée : $root\dist\Piece2STL\Piece2STL.exe"
}
finally {
    Pop-Location
}
