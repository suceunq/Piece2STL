"""Ouvre le mesh dans une fenêtre 3D interactive : clique 2 points, indique la
distance réelle entre eux (mm), et le script exporte un STL + 3MF à l'échelle.

Usage:
  python scripts/pick_scale.py chemin/vers/mesh_cleaned.ply

Contrôles dans la fenêtre :
  - Clique gauche sur 2 points du mesh (ex: les deux extrémités d'une cote connue)
  - Ferme la fenêtre une fois les 2 points choisis
"""

import sys
from pathlib import Path

import numpy as np
import pyvista as pv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from piece2stl.pipeline.export import export_mesh, load_mesh
from piece2stl.pipeline.scale import apply_scale, scale_factor_from_two_points


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/pick_scale.py chemin/vers/mesh.ply")
        sys.exit(1)

    mesh_path = Path(sys.argv[1])
    mesh = pv.read(str(mesh_path))

    picked_points: list[np.ndarray] = []

    def on_pick(point):
        picked_points.append(np.array(point))
        label = f"P{len(picked_points)}"
        plotter.add_point_labels([point], [label], point_size=15, font_size=20)
        print(f"{label}: {point}")

    plotter = pv.Plotter()
    plotter.add_mesh(mesh, color="tan")
    plotter.enable_point_picking(callback=on_pick, show_message=True, use_mesh=True)
    plotter.add_text(
        "Clique 2 points formant une cote connue, puis ferme la fenêtre", font_size=12
    )
    plotter.show()

    if len(picked_points) < 2:
        print("Moins de 2 points sélectionnés, abandon (relance le script).")
        sys.exit(1)

    p1, p2 = picked_points[-2], picked_points[-1]
    real_distance_mm = float(input(f"Distance réelle entre les 2 derniers points cliqués (mm) : "))

    factor = scale_factor_from_two_points(p1, p2, real_distance_mm)
    print(f"Facteur d'échelle appliqué : {factor:.6f}")

    trimesh_mesh = load_mesh(mesh_path)
    scaled = apply_scale(trimesh_mesh, factor)

    out_stl = mesh_path.with_name(mesh_path.stem + "_scaled.stl")
    out_3mf = mesh_path.with_name(mesh_path.stem + "_scaled.3mf")
    export_mesh(scaled, out_stl)
    export_mesh(scaled, out_3mf)
    print(f"Exporté : {out_stl}")
    print(f"Exporté : {out_3mf}")


if __name__ == "__main__":
    main()
