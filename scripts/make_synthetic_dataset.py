"""Génère un petit jeu de photos synthétiques (objet texturé, bosselé, vu sous
plusieurs angles) pour valider la mécanique du pipeline COLMAP -> OpenMVS ->
nettoyage -> export, sans dépendre d'un gros dataset externe.
"""

import math
import sys
from pathlib import Path

import numpy as np
import pyvista as pv

pv.OFF_SCREEN = True


def make_bumpy_textured_sphere() -> pv.PolyData:
    sphere = pv.Sphere(theta_resolution=80, phi_resolution=80)

    # Ellipsoïde asymétrique (pas de bruit géométrique à haute fréquence : ça
    # dégénère en oursin). La texture suffit à fournir des points d'intérêt SIFT.
    sphere.points[:, 0] *= 1.0
    sphere.points[:, 1] *= 0.75
    sphere.points[:, 2] *= 1.3

    sphere.texture_map_to_sphere(inplace=True)
    return sphere


def make_checker_texture(size: int = 512, cells: int = 12) -> pv.Texture:
    rng = np.random.default_rng(7)
    img = np.zeros((size, size, 3), dtype=np.uint8)
    cell_size = size // cells
    for i in range(cells):
        for j in range(cells):
            color = rng.integers(40, 255, size=3)
            img[i * cell_size : (i + 1) * cell_size, j * cell_size : (j + 1) * cell_size] = color
    return pv.Texture(img)


def render_views(output_dir: Path, n_azimuth: int = 24, elevations=(10, 30)) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    mesh = make_bumpy_textured_sphere()
    texture = make_checker_texture()

    plotter = pv.Plotter(off_screen=True, window_size=[640, 480])
    plotter.set_background("gray")
    plotter.add_mesh(mesh, texture=texture)

    radius = 3.5
    paths = []
    index = 0
    for elevation_deg in elevations:
        elevation = math.radians(elevation_deg)
        for k in range(n_azimuth):
            azimuth = math.radians(360 * k / n_azimuth)
            x = radius * math.cos(elevation) * math.cos(azimuth)
            y = radius * math.cos(elevation) * math.sin(azimuth)
            z = radius * math.sin(elevation)

            plotter.camera_position = [(x, y, z), (0, 0, 0), (0, 0, 1)]
            plotter.camera.view_angle = 40
            plotter.render()

            out_path = output_dir / f"view_{index:03d}.jpg"
            plotter.screenshot(str(out_path))
            paths.append(out_path)
            index += 1

    plotter.close()
    return paths


if __name__ == "__main__":
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("demo_data/images")
    views = render_views(out_dir)
    print(f"{len(views)} images générées dans {out_dir}")
