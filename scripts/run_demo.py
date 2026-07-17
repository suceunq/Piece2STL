"""Test bout-en-bout du pipeline (sans mise à l'échelle) sur le dataset synthétique.

Valide la mécanique COLMAP -> OpenMVS -> nettoyage -> export avant de tester sur
une vraie pièce photographiée.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from piece2stl.pipeline.export import export_mesh, is_watertight, load_mesh
from piece2stl.pipeline.run_pipeline import reconstruct


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    image_dir = root / "demo_data" / "images"
    workspace_dir = root / "demo_data" / "workspace"

    if not image_dir.exists():
        print(f"Dataset manquant : {image_dir}. Lance d'abord make_synthetic_dataset.py")
        sys.exit(1)

    cleaned_mesh_path = reconstruct(
        image_dir=image_dir,
        workspace_dir=workspace_dir,
        sequential=False,
    )
    print(f"\nMesh nettoyé : {cleaned_mesh_path}")

    mesh = load_mesh(cleaned_mesh_path)
    print(f"Sommets: {len(mesh.vertices)}, Faces: {len(mesh.faces)}")
    print(f"Watertight: {is_watertight(mesh)}")

    stl_path = export_mesh(mesh, workspace_dir / "demo_export.stl")
    print(f"STL exporté : {stl_path}")


if __name__ == "__main__":
    main()
