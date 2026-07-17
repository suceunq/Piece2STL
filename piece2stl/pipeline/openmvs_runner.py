from pathlib import Path

from ..config import (
    OPENMVS_DENSIFY,
    OPENMVS_INTERFACE_COLMAP,
    OPENMVS_RECONSTRUCT_MESH,
)
from .process import CancelCallback, LogCallback, ProgressCallback, run_command


def _run_openmvs_tool(
    exe: Path,
    args: list,
    dense_dir: Path,
    log: LogCallback | None,
    cancel: CancelCallback | None = None,
) -> None:
    """OpenMVS n'écrit pas sa progression sur stdout, seulement dans un fichier
    <Outil>-<timestamp>.log dans le dossier de travail. On le relit après coup
    pour que l'appelant (GUI ou CLI) voie quand même ce qui s'est passé."""
    existing_logs = set(dense_dir.glob(f"{exe.stem}-*.log"))
    try:
        run_command(
            [exe, *args, "-w", dense_dir], cwd=dense_dir, log=log, cancel=cancel
        )
    finally:
        new_logs = set(dense_dir.glob(f"{exe.stem}-*.log")) - existing_logs
        log_fn = log or (lambda line: print(line))
        for log_file in sorted(new_logs):
            for line in log_file.read_text(encoding="utf-8", errors="replace").splitlines():
                log_fn(line)


def dense_reconstruction(
    dense_dir: Path,
    log: LogCallback | None = None,
    cancel: CancelCallback | None = None,
    progress: ProgressCallback | None = None,
) -> Path:
    """Chaîne OpenMVS complète : COLMAP dense/ -> scene.mvs -> nuage dense -> mesh brut.

    `dense_dir` est le dossier produit par `colmap image_undistorter`
    (contient sparse/ + images/). Retourne le chemin du mesh .ply brut.
    """
    # Chemin absolu obligatoire : OpenMVS combine son cwd (= dense_dir) avec
    # l'argument -w, donc un dense_dir relatif produit un double chemin invalide.
    dense_dir = dense_dir.resolve()
    scene_mvs = dense_dir / "scene.mvs"

    if progress:
        progress(63, "Conversion vers OpenMVS")
    _run_openmvs_tool(
        OPENMVS_INTERFACE_COLMAP,
        ["-i", ".", "-o", scene_mvs.name],
        dense_dir,
        log,
        cancel,
    )

    if progress:
        progress(72, "Création du nuage de points dense")
    _run_openmvs_tool(OPENMVS_DENSIFY, [scene_mvs.name], dense_dir, log, cancel)

    dense_mvs = dense_dir / "scene_dense.mvs"
    if not dense_mvs.exists():
        raise RuntimeError("OpenMVS DensifyPointCloud n'a pas produit scene_dense.mvs")

    if progress:
        progress(85, "Création du maillage")
    _run_openmvs_tool(
        OPENMVS_RECONSTRUCT_MESH, [dense_mvs.name], dense_dir, log, cancel
    )

    mesh_path = dense_dir / "scene_dense_mesh.ply"
    if not mesh_path.exists():
        raise RuntimeError("OpenMVS ReconstructMesh n'a pas produit scene_dense_mesh.ply")

    return mesh_path
