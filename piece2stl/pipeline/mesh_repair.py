from dataclasses import asdict, dataclass
import json
from pathlib import Path

import pymeshlab

from .export import load_mesh
from .mesh_report import MeshReport, inspect_mesh


@dataclass(frozen=True)
class RepairParams:
    close_holes_max_edges: int = 200
    remove_components_below_faces: int = 0
    prevent_self_intersections: bool = True


@dataclass(frozen=True)
class RepairResult:
    output_path: Path
    before: MeshReport
    after: MeshReport

    @property
    def improved(self) -> bool:
        before_score = sum(
            (self.before.watertight, self.before.winding_consistent, self.before.is_volume)
        )
        after_score = sum(
            (self.after.watertight, self.after.winding_consistent, self.after.is_volume)
        )
        return after_score > before_score


def repair_mesh(
    input_path: Path,
    output_path: Path,
    params: RepairParams = RepairParams(),
) -> RepairResult:
    """Répare un maillage sans modifier le fichier source."""
    if params.close_holes_max_edges <= 0:
        raise ValueError("La taille maximale des trous doit être positive.")
    if params.remove_components_below_faces < 0:
        raise ValueError("Le seuil des composants ne peut pas être négatif.")

    before = inspect_mesh(load_mesh(input_path))
    mesh_set = pymeshlab.MeshSet()
    mesh_set.load_new_mesh(str(input_path))

    mesh_set.meshing_remove_duplicate_vertices()
    mesh_set.meshing_remove_duplicate_faces()
    mesh_set.meshing_remove_unreferenced_vertices()

    if params.remove_components_below_faces:
        mesh_set.meshing_remove_connected_component_by_face_number(
            mincomponentsize=params.remove_components_below_faces,
            removeunref=True,
        )

    mesh_set.meshing_repair_non_manifold_edges(method="Remove Faces")
    mesh_set.meshing_repair_non_manifold_vertices()
    mesh_set.meshing_close_holes(
        maxholesize=params.close_holes_max_edges,
        selfintersection=params.prevent_self_intersections,
        refinehole=False,
    )
    mesh_set.meshing_remove_duplicate_faces()
    mesh_set.meshing_remove_unreferenced_vertices()
    mesh_set.meshing_re_orient_faces_coherently()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    mesh_set.save_current_mesh(str(output_path))
    after = inspect_mesh(load_mesh(output_path))
    return RepairResult(output_path=output_path, before=before, after=after)


def save_repair_report(result: RepairResult, path: Path) -> Path:
    data = {
        "input": asdict(result.before),
        "output": asdict(result.after),
        "improved": result.improved,
        "printable": result.after.printable,
        "output_path": str(result.output_path),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path
