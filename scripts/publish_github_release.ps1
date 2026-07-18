param(
    [string]$Repository = "suceunq/Piece2STL",
    [string]$Version = "0.4.1"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$installer = Join-Path $root "dist\installer\Piece2STL-Setup-$Version.exe"
$checksum = "$installer.sha256"
if (-not (Test-Path $installer) -or -not (Test-Path $checksum)) {
    throw "Construisez d'abord l'installateur et sa somme SHA-256."
}
& gh repo view $Repository *> $null
if ($LASTEXITCODE -ne 0) { throw "Le dépôt GitHub $Repository n'existe pas ou n'est pas accessible." }
& gh release create "v$Version" $installer $checksum `
    --repo $Repository `
    --title "Piece2STL $Version" `
    --notes-file (Join-Path $root "RELEASE_NOTES.md")
if ($LASTEXITCODE -ne 0) { throw "La publication GitHub a échoué." }
