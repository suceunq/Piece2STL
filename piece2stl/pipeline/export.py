from pathlib import Path

import trimesh


def load_mesh(path: Path) -> trimesh.Trimesh:
    mesh = trimesh.load(str(path), force="mesh")
    if not isinstance(mesh, trimesh.Trimesh):
        raise TypeError(f"{path} ne contient pas un maillage triangulaire exploitable.")
    return mesh


def is_watertight(mesh: trimesh.Trimesh) -> bool:
    return bool(mesh.is_watertight)


def export_mesh(mesh: trimesh.Trimesh, output_path: Path) -> Path:
    """Exporte la géométrie, exprimée en millimètres dans Piece2STL."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(str(output_path))
    return output_path
