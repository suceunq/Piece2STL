param(
    [ValidateSet("Auto", "AMD", "NVIDIA", "Intel", "CPU")]
    [string]$Backend = "Auto",
    [switch]$Force,
    [switch]$RuntimeOnly
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

trap {
    $technicalMessage = $_.Exception.Message
    Write-Output ("PIECE2STL_ERROR|Installation IA interrompue|{0}" -f $technicalMessage.Replace("|", "/"))
    [Console]::Error.WriteLine(($_ | Out-String))
    exit 1
}

function Write-Piece2STLProgress {
    param(
        [int]$Percent,
        [string]$Title,
        [string]$Explanation
    )
    # Ligne structurée consommée par l'interface. Ne pas utiliser le caractère | dans les textes.
    Write-Output ("PIECE2STL_PROGRESS|{0}|{1}|{2}" -f $Percent, $Title, $Explanation)
}

Write-Piece2STLProgress 2 "Préparation de l’installation" "Localisation des composants Piece2STL et création de l’espace de travail IA."
$root = Split-Path -Parent $PSScriptRoot
if (Test-Path (Join-Path $PSScriptRoot "_internal\ai")) {
    $root = $PSScriptRoot
    $aiDir = Join-Path $root "_internal\ai"
    $uv = Join-Path $root "uv.exe"
}
else {
    $aiDir = Join-Path $root "ai"
    $uvCommand = Get-Command uv.exe -ErrorAction SilentlyContinue
    if (-not $uvCommand) { throw "uv.exe est requis pour créer l'environnement IA." }
    $uv = $uvCommand.Source
}

$venv = Join-Path $root ".ai-venv"
$python = Join-Path $venv "Scripts\python.exe"
$readyMarker = Join-Path $venv "piece2stl_ai_ready.json"
$markerVersion = "2"
$runtimeReady = $false
$runtimeRoot = Join-Path $root ".ai-runtime"
$runtimePythonDir = Join-Path $runtimeRoot "python"
$env:UV_PYTHON_INSTALL_DIR = $runtimePythonDir
$env:UV_CACHE_DIR = Join-Path $runtimeRoot "cache"

function Test-Piece2STLPython {
    param([string]$Executable)
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) { return $false }
    try {
        & $Executable -c "import sys; assert sys.version_info[:2] == (3, 12)" *> $null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        # Un venv partiel ou fondé sur une jonction refusée doit être réparé,
        # pas transformer le contrôle préalable en erreur fatale.
        return $false
    }
}

function Get-Piece2STLBasePython {
    $installation = Get-ChildItem -LiteralPath $runtimePythonDir -Directory -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -like "cpython-3.12.*-windows-x86_64-none" -and
            -not ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -and
            (Test-Path -LiteralPath (Join-Path $_.FullName "python.exe") -PathType Leaf)
        } |
        Sort-Object Name -Descending |
        Select-Object -First 1
    if (-not $installation) { return $null }
    return (Join-Path $installation.FullName "python.exe")
}

function Install-Piece2STLPythonRuntime {
    Write-Piece2STLProgress 12 "Création de l’environnement IA" "Installation isolée de Python 3.12 dans Piece2STL, sans utiliser les jonctions Python globales de Windows."
    New-Item -ItemType Directory -Force -Path $runtimeRoot, $runtimePythonDir | Out-Null

    & $uv python install 3.12 --install-dir $runtimePythonDir --no-bin
    if ($LASTEXITCODE -ne 0) {
        Write-Piece2STLProgress 13 "Réparation automatique du runtime" "La première préparation de Python a échoué. Piece2STL télécharge une copie propre et réessaie automatiquement."
        & $uv python install 3.12 --install-dir $runtimePythonDir --no-bin --reinstall
        if ($LASTEXITCODE -ne 0) { throw "Impossible d’installer le runtime Python 3.12 local." }
    }

    $basePython = Get-Piece2STLBasePython
    if (-not $basePython) { throw "Le runtime Python local a été téléchargé, mais son exécutable réel est introuvable." }

    if (Test-Path -LiteralPath $venv) {
        Remove-Item -LiteralPath $venv -Recurse -Force
    }
    # Ne pas utiliser `uv venv` ici : sous Windows il peut réintroduire l’alias
    # de version sous forme de jonction dans pyvenv.cfg (ERROR_UNTRUSTED_MOUNT_POINT 448).
    & $basePython -m venv $venv
    if ($LASTEXITCODE -ne 0) {
        Write-Piece2STLProgress 14 "Nouvelle tentative de l’environnement IA" "Nettoyage de l’environnement incomplet puis nouvelle création avec le Python local vérifié."
        if (Test-Path -LiteralPath $venv) { Remove-Item -LiteralPath $venv -Recurse -Force }
        & $uv python install 3.12 --install-dir $runtimePythonDir --no-bin --reinstall
        if ($LASTEXITCODE -ne 0) { throw "Réinstallation du runtime Python local échouée." }
        $basePython = Get-Piece2STLBasePython
        if (-not $basePython) { throw "Le runtime Python réparé reste introuvable." }
        & $basePython -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw "Création de l’environnement IA échouée après la tentative de réparation." }
    }
    if (-not (Test-Piece2STLPython $python)) {
        throw "L’environnement IA a été créé, mais Python 3.12 ne démarre pas correctement."
    }
}
Write-Piece2STLProgress 5 "Détection du matériel" "Identification de la carte graphique afin de choisir automatiquement AMD ROCm, NVIDIA CUDA, Intel XPU ou le processeur."
try {
    $gpuNames = @(Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name })
}
catch {
    $gpuNames = @()
    Write-Warning "La détection WMI du GPU n’est pas disponible. Le mode CPU de secours sera utilisé."
}
$gpuText = $gpuNames -join " | "
if (-not $gpuText) { $gpuText = "Aucune carte détectée par Windows" }

if ($Backend -eq "Auto") {
    if ($gpuText -match "NVIDIA|GeForce|Quadro") { $Backend = "NVIDIA" }
    elseif ($gpuText -match "AMD|Radeon") { $Backend = "AMD" }
    elseif ($gpuText -match "Intel|Arc") { $Backend = "Intel" }
    else { $Backend = "CPU" }
}

Write-Host "Cartes détectées : $gpuText"
Write-Host "Backend sélectionné : $Backend"
Write-Piece2STLProgress 8 "Moteur sélectionné : $Backend" "La sélection est automatique et un repli sur le processeur reste disponible si le pilote GPU n’est pas compatible."

if (-not (Test-Path (Join-Path $aiDir "TripoSR\tsr"))) {
    Write-Piece2STLProgress 10 "Récupération du moteur 3D" "Téléchargement des sources open source de TripoSR utilisées localement pour reconstruire l’objet."
    Write-Host "Téléchargement du moteur open source TripoSR…"
    $archive = Join-Path $env:TEMP "piece2stl-triposr.zip"
    $extract = Join-Path $env:TEMP "piece2stl-triposr-source"
    Invoke-WebRequest "https://github.com/VAST-AI-Research/TripoSR/archive/refs/heads/main.zip" -OutFile $archive
    if (Test-Path $extract) { Remove-Item -LiteralPath $extract -Recurse -Force }
    Expand-Archive -LiteralPath $archive -DestinationPath $extract -Force
    New-Item -ItemType Directory -Force -Path $aiDir | Out-Null
    Move-Item -LiteralPath (Join-Path $extract "TripoSR-main") -Destination (Join-Path $aiDir "TripoSR")
}
if (-not (Test-Piece2STLPython $python)) {
    Install-Piece2STLPythonRuntime
}
if ($RuntimeOnly) {
    Write-Piece2STLProgress 100 "Runtime Python validé" "Python 3.12 a été installé localement sans traverser de jonction Windows."
    exit 0
}
if ((Test-Path $readyMarker) -and (-not $Force)) {
    Write-Piece2STLProgress 35 "Vérification de l’installation existante" "Contrôle rapide du moteur déjà présent et du périphérique de calcul disponible."
    & $python (Join-Path $aiDir "triposr_worker.py") --probe
    if ($LASTEXITCODE -eq 0) {
        $runtimeReady = $true
        try { $marker = Get-Content -Raw $readyMarker | ConvertFrom-Json } catch { $marker = $null }
        if ($marker -and ([string]$marker.version -eq $markerVersion)) {
            Write-Host "Le mode IA est déjà installé. Utilisez -Force pour le réinstaller."
            Write-Piece2STLProgress 100 "IA locale déjà prête" "Le moteur existant fonctionne correctement. Vous pouvez lancer une reconstruction sans redémarrer l’application."
            exit 0
        }
        Write-Piece2STLProgress 50 "Mise à niveau de la qualité IA" "Le moteur GPU existant est conservé. Ajout du détourage BiRefNet et des nouveaux réglages haute définition."
    }
}

if (-not $runtimeReady) {
if ($Backend -eq "AMD") {
    Write-Piece2STLProgress 18 "Installation du moteur AMD ROCm" "Téléchargement des bibliothèques officielles permettant d’utiliser la carte Radeon pour accélérer l’IA. Cette étape peut être longue."
    Write-Host "Installation du backend AMD ROCm 7.2.1…"
    & $python -m pip install --no-cache-dir `
        "https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1/rocm_sdk_core-7.2.1-py3-none-win_amd64.whl" `
        "https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1/rocm_sdk_devel-7.2.1-py3-none-win_amd64.whl" `
        "https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1/rocm_sdk_libraries_custom-7.2.1-py3-none-win_amd64.whl" `
        "https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1/rocm-7.2.1.tar.gz"
    if ($LASTEXITCODE -ne 0) { throw "Installation du SDK ROCm échouée." }
    & $python -m pip install --no-cache-dir `
        "https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1/torch-2.9.1%2Brocm7.2.1-cp312-cp312-win_amd64.whl" `
        "https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1/torchvision-0.24.1%2Brocm7.2.1-cp312-cp312-win_amd64.whl"
}
elseif ($Backend -eq "NVIDIA") {
    Write-Piece2STLProgress 18 "Installation du moteur NVIDIA CUDA" "Téléchargement de PyTorch CUDA pour exécuter le modèle directement sur la carte NVIDIA."
    Write-Host "Installation du backend NVIDIA CUDA…"
    & $python -m pip install "torch==2.9.0" --index-url "https://download.pytorch.org/whl/cu129"
}
elseif ($Backend -eq "Intel") {
    Write-Piece2STLProgress 18 "Installation du moteur Intel XPU" "Téléchargement de PyTorch XPU pour utiliser l’accélération des cartes Intel compatibles."
    Write-Host "Installation du backend Intel XPU…"
    & $python -m pip install "torch==2.9.1" --index-url "https://download.pytorch.org/whl/xpu"
}
else {
    Write-Piece2STLProgress 18 "Installation du moteur processeur" "Mise en place du mode CPU universel. Il est plus lent, mais fonctionne sans carte graphique compatible."
    Write-Host "Aucun GPU pris en charge détecté : installation du repli CPU."
    & $python -m pip install "torch==2.9.1" --index-url "https://download.pytorch.org/whl/cpu"
}
if ($LASTEXITCODE -ne 0) { throw "Installation de PyTorch échouée." }

Write-Piece2STLProgress 58 "Vérification de l’accélération" "Test réel de PyTorch sur le périphérique sélectionné avant d’installer le reste du moteur."
if ($Backend -eq "AMD" -or $Backend -eq "NVIDIA") {
    & $python -c "import torch; assert torch.cuda.is_available()"
}
elseif ($Backend -eq "Intel") {
    & $python -c "import torch; assert hasattr(torch, 'xpu') and torch.xpu.is_available()"
}
if ($LASTEXITCODE -ne 0) {
    Write-Piece2STLProgress 60 "Activation du mode de secours CPU" "Le pilote GPU n’a pas répondu au test. Piece2STL installe automatiquement une solution compatible avec le processeur."
    Write-Warning "Le backend GPU n'est pas opérationnel avec ce pilote. Repli automatique sur CPU."
    & $python -m pip uninstall -y torch torchvision
    & $python -m pip install "torch==2.9.1" --index-url "https://download.pytorch.org/whl/cpu"
    if ($LASTEXITCODE -ne 0) { throw "Installation du repli CPU échouée." }
    $Backend = "CPU"
}
}

Write-Piece2STLProgress 65 "Installation des composants IA" "Ajout du détourage automatique, du traitement d’image et des outils de création du maillage 3D."
& $python -m pip install -r (Join-Path $aiDir "requirements-worker.txt")
if ($LASTEXITCODE -ne 0) { throw "Installation des dépendances TripoSR échouée." }

Write-Piece2STLProgress 86 "Test du moteur IA" "Vérification de la version de PyTorch, de la mémoire disponible et du périphérique qui exécutera les calculs."
& $python (Join-Path $aiDir "triposr_worker.py") --probe
if ($LASTEXITCODE -ne 0) { throw "Le backend IA ne détecte aucun périphérique valide." }
Write-Piece2STLProgress 91 "Téléchargement des modèles haute qualité" "Récupération de TripoSR et du détourage BiRefNet. Ils seront conservés sur l’ordinateur pour les prochaines utilisations."
& $python (Join-Path $aiDir "triposr_worker.py") --download-model
if ($LASTEXITCODE -ne 0) { throw "Téléchargement du modèle TripoSR échoué." }

Write-Piece2STLProgress 98 "Finalisation" "Enregistrement de la configuration validée pour que Piece2STL puisse démarrer l’IA immédiatement."
@{
    installed_at = (Get-Date).ToString("o")
    gpu = $gpuText
    version = $markerVersion
} | ConvertTo-Json | Set-Content -Path $readyMarker -Encoding UTF8

Write-Host "Mode IA installé avec succès."
Write-Piece2STLProgress 100 "IA locale prête" "Installation terminée et vérifiée. Vous pouvez créer un modèle à partir d’une photo, sans redémarrer Piece2STL."
