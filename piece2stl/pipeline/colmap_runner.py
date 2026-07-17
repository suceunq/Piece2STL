from pathlib import Path

from ..config import COLMAP_EXE
from .process import CancelCallback, LogCallback, ProgressCallback, run_command


def run_sparse_reconstruction(
    image_dir: Path,
    workspace_dir: Path,
    sequential: bool = False,
    log: LogCallback | None = None,
    cancel: CancelCallback | None = None,
    progress: ProgressCallback | None = None,
) -> Path:
    """Reconstruction SfM CPU-only, puis undistortion pour préparer l'entrée OpenMVS.

    Retourne le dossier "dense" (contient sparse/ + images/) attendu par InterfaceCOLMAP.
    """
    workspace_dir.mkdir(parents=True, exist_ok=True)
    database_path = workspace_dir / "database.db"
    sparse_dir = workspace_dir / "sparse"
    sparse_dir.mkdir(exist_ok=True)
    dense_dir = workspace_dir / "dense"

    if progress:
        progress(12, "Détection des détails dans les images")

    run_command(
        [
            COLMAP_EXE,
            "feature_extractor",
            "--database_path",
            database_path,
            "--image_path",
            image_dir,
            "--ImageReader.camera_model",
            "PINHOLE",
            "--FeatureExtraction.use_gpu",
            "0",
        ],
        log=log,
        cancel=cancel,
    )

    matcher_cmd = "sequential_matcher" if sequential else "exhaustive_matcher"
    if progress:
        progress(28, "Mise en correspondance des images")
    run_command(
        [
            COLMAP_EXE,
            matcher_cmd,
            "--database_path",
            database_path,
            "--FeatureMatching.use_gpu",
            "0",
        ],
        log=log,
        cancel=cancel,
    )

    if progress:
        progress(43, "Calcul des positions de caméra")
    run_command(
        [
            COLMAP_EXE,
            "mapper",
            "--database_path",
            database_path,
            "--image_path",
            image_dir,
            "--output_path",
            sparse_dir,
        ],
        log=log,
        cancel=cancel,
    )

    model_dir = _pick_best_model(sparse_dir, workspace_dir, log=log, cancel=cancel)

    if progress:
        progress(55, "Préparation de la reconstruction dense")
    run_command(
        [
            COLMAP_EXE,
            "image_undistorter",
            "--image_path",
            image_dir,
            "--input_path",
            model_dir,
            "--output_path",
            dense_dir,
            "--output_type",
            "COLMAP",
        ],
        log=log,
        cancel=cancel,
    )

    return dense_dir


def count_registered_images(
    model_dir: Path,
    txt_dir: Path,
    log: LogCallback | None = None,
    cancel: CancelCallback | None = None,
) -> int:
    """Convertit le modèle sparse en TXT et compte les images enregistrées (recoupées avec succès)."""
    txt_dir.mkdir(parents=True, exist_ok=True)
    run_command(
        [
            COLMAP_EXE,
            "model_converter",
            "--input_path",
            model_dir,
            "--output_path",
            txt_dir,
            "--output_type",
            "TXT",
        ],
        log=log,
        cancel=cancel,
    )
    images_txt = txt_dir / "images.txt"
    count = 0
    with open(images_txt, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split()
            if len(parts) > 0 and parts[0].isdigit():
                count += 1
    return count


def _pick_best_model(
    sparse_dir: Path,
    workspace_dir: Path,
    log: LogCallback | None = None,
    cancel: CancelCallback | None = None,
) -> Path:
    """COLMAP peut produire plusieurs sous-modèles disjoints (sparse/0, sparse/1, ...)
    quand toutes les images ne se recoupent pas en un seul morceau. On garde celui
    qui a enregistré le plus d'images, pas forcément sparse/0."""
    candidates = sorted(
        (p for p in sparse_dir.iterdir() if p.is_dir() and p.name.isdigit()),
        key=lambda p: int(p.name),
    )
    if not candidates:
        raise RuntimeError(
            "COLMAP n'a produit aucun modèle sparse. "
            "Reconstruction échouée — trop peu d'images se recoupent probablement."
        )
    if len(candidates) == 1:
        return candidates[0]

    counts_dir = workspace_dir / "sparse_txt"
    best_model, best_count = candidates[0], -1
    for candidate in candidates:
        count = count_registered_images(
            candidate, counts_dir / candidate.name, log=log, cancel=cancel
        )
        if log:
            log(f"Modèle sparse/{candidate.name}: {count} images enregistrées")
        if count > best_count:
            best_model, best_count = candidate, count

    return best_model
