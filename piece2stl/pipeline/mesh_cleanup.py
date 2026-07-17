from dataclasses import dataclass
from pathlib import Path

import pymeshlab


@dataclass
class CleanupParams:
    remove_components_diameter_ratio: float = 0.05  # vire les morceaux < 5% du diamètre du mesh
    close_holes_max_edges: int = 200
    target_face_count: int = 150_000


def clean_mesh(
    input_path: Path,
    output_path: Path,
    params: CleanupParams = CleanupParams(),
) -> None:
    ms = pymeshlab.MeshSet()
    ms.load_new_mesh(str(input_path))

    ms.meshing_remove_connected_component_by_diameter(
        mincomponentdiag=pymeshlab.PercentageValue(
            params.remove_components_diameter_ratio * 100
        )
    )

    ms.meshing_repair_non_manifold_edges()
    ms.meshing_repair_non_manifold_vertices()

    ms.meshing_close_holes(maxholesize=params.close_holes_max_edges)

    current_faces = ms.current_mesh().face_number()
    if current_faces > params.target_face_count:
        ms.meshing_decimation_quadric_edge_collapse(
            targetfacenum=params.target_face_count
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ms.save_current_mesh(str(output_path))
