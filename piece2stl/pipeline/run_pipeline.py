from pathlib import Path

from ..config import check_vendor_binaries
from .colmap_runner import run_sparse_reconstruction
from .mesh_cleanup import CleanupParams, clean_mesh
from .openmvs_runner import dense_reconstruction
from .process import CancelCallback, LogCallback, ProgressCallback


def reconstruct(
    image_dir: Path,
    workspace_dir: Path,
    sequential: bool = False,
    cleanup_params: CleanupParams = CleanupParams(),
    log: LogCallback | None = None,
    cancel: CancelCallback | None = None,
    progress: ProgressCallback | None = None,
) -> Path:
    """Photos -> mesh nettoyé (non mis à l'échelle). Retourne le chemin du .ply nettoyé."""
    if progress:
        progress(5, "Vérification des composants")
    check_vendor_binaries()

    dense_dir = run_sparse_reconstruction(
        image_dir=image_dir,
        workspace_dir=workspace_dir,
        sequential=sequential,
        log=log,
        cancel=cancel,
        progress=progress,
    )

    raw_mesh_path = dense_reconstruction(
        dense_dir, log=log, cancel=cancel, progress=progress
    )

    if progress:
        progress(94, "Nettoyage du maillage")
    cleaned_mesh_path = workspace_dir / "mesh_cleaned.ply"
    clean_mesh(raw_mesh_path, cleaned_mesh_path, params=cleanup_params)

    if progress:
        progress(100, "Reconstruction terminée")

    return cleaned_mesh_path
