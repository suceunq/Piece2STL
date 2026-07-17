from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path

import pymeshlab

from .export import load_mesh
from .mesh_report import MeshReport, inspect_mesh


@dataclass(frozen=True)
class AIPostProcessReport:
    input: MeshReport
    output: MeshReport
    component_face_threshold: int
    removed_faces: int
    smoothing_steps: int


def optimize_ai_mesh(input_path: Path, output_path: Path) -> AIPostProcessReport:
    """Nettoie et lisse légèrement un maillage IA en conservant ses couleurs."""
    before = inspect_mesh(load_mesh(input_path))
    mesh_set = pymeshlab.MeshSet()
    mesh_set.load_new_mesh(str(input_path))

    mesh_set.meshing_remove_duplicate_vertices()
    mesh_set.meshing_remove_duplicate_faces()
    mesh_set.meshing_remove_null_faces()
    mesh_set.meshing_remove_unreferenced_vertices()

    # Élimine uniquement les poussières géométriques minuscules. Le seuil
    # relatif reste assez bas pour préserver les accessoires détachés utiles.
    component_threshold = max(32, int(before.faces * 0.001))
    mesh_set.meshing_remove_connected_component_by_face_number(
        mincomponentsize=component_threshold,
        removeunref=True,
    )

    if before.non_manifold_edges:
        mesh_set.meshing_repair_non_manifold_edges(method="Remove Faces")
        mesh_set.meshing_repair_non_manifold_vertices()
    if before.boundary_edges:
        mesh_set.meshing_close_holes(
            maxholesize=200,
            selfintersection=True,
            refinehole=False,
        )

    current_faces = mesh_set.current_mesh().face_number()
    smoothing_steps = 6 if current_faces >= 100_000 else (5 if current_faces >= 50_000 else 3)
    mesh_set.apply_coord_taubin_smoothing(
        lambda_=0.5,
        mu=-0.53,
        stepsmoothnum=smoothing_steps,
        selected=False,
    )
    mesh_set.meshing_remove_duplicate_faces()
    mesh_set.meshing_remove_unreferenced_vertices()
    mesh_set.meshing_re_orient_faces_coherently()
    mesh_set.compute_normal_per_face()
    mesh_set.compute_normal_per_vertex(weightmode="By Angle")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    mesh_set.save_current_mesh(str(output_path))
    after = inspect_mesh(load_mesh(output_path))

    # Le lissage ne doit jamais dégrader un maillage initialement imprimable.
    if before.printable and not after.printable:
        raise RuntimeError(
            "Le post-traitement a dégradé la topologie d’un maillage imprimable."
        )

    return AIPostProcessReport(
        input=before,
        output=after,
        component_face_threshold=component_threshold,
        removed_faces=max(0, before.faces - after.faces),
        smoothing_steps=smoothing_steps,
    )


def save_ai_postprocess_report(report: AIPostProcessReport, path: Path) -> Path:
    data = asdict(report)
    data["input"]["printable"] = report.input.printable
    data["output"]["printable"] = report.output.printable
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path
