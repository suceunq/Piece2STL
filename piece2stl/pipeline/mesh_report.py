from dataclasses import asdict, dataclass
from pathlib import Path
import json

import numpy as np
import trimesh


@dataclass(frozen=True)
class MeshReport:
    vertices: int
    faces: int
    watertight: bool
    winding_consistent: bool
    is_volume: bool
    boundary_edges: int
    non_manifold_edges: int
    dimensions: tuple[float, float, float]

    @property
    def printable(self) -> bool:
        return self.watertight and self.winding_consistent and self.is_volume


def inspect_mesh(mesh: trimesh.Trimesh) -> MeshReport:
    extents = tuple(float(value) for value in mesh.extents)
    edge_occurrences = np.bincount(mesh.edges_unique_inverse)
    return MeshReport(
        vertices=len(mesh.vertices),
        faces=len(mesh.faces),
        watertight=bool(mesh.is_watertight),
        winding_consistent=bool(mesh.is_winding_consistent),
        is_volume=bool(mesh.is_volume),
        boundary_edges=int(np.count_nonzero(edge_occurrences == 1)),
        non_manifold_edges=int(np.count_nonzero(edge_occurrences > 2)),
        dimensions=extents,
    )


def save_report(report: MeshReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(report)
    data["printable"] = report.printable
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path
