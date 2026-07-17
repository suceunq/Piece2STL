$ErrorActionPreference = "Stop"

$version = "0.4.0"
$source = $PSScriptRoot
$sourceExe = Join-Path $source "Piece2STL.exe"
if (-not (Test-Path $sourceExe)) {
    throw "Piece2STL.exe est introuvable a cote de l'installateur."
}

$destination = Join-Path $env:LOCALAPPDATA "Piece2STL\$version"
New-Item -ItemType Directory -Force -Path $destination | Out-Null
Copy-Item -Path (Join-Path $source "*") -Destination $destination -Recurse -Force

$installedExe = Join-Path $destination "Piece2STL.exe"
$shell = New-Object -ComObject WScript.Shell

$desktopShortcut = $shell.CreateShortcut(
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "Piece2STL.lnk")
)
$desktopShortcut.TargetPath = $installedExe
$desktopShortcut.WorkingDirectory = $destination
$desktopShortcut.Save()

$startMenu = Join-Path ([Environment]::GetFolderPath("Programs")) "Piece2STL"
New-Item -ItemType Directory -Force -Path $startMenu | Out-Null
$startShortcut = $shell.CreateShortcut((Join-Path $startMenu "Piece2STL.lnk"))
$startShortcut.TargetPath = $installedExe
$startShortcut.WorkingDirectory = $destination
$startShortcut.Save()

Start-Process -FilePath $installedExe
Write-Host "Piece2STL $version installe dans $destination"
