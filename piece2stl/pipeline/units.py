from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path

import numpy as np
import trimesh


DEFAULT_GENERATED_SIZE_MM = 100.0


@dataclass(frozen=True)
class UnitScaleReport:
    source_unit: str
    target_unit: str
    scale_factor: float
    dimensions_before: tuple[float, float, float]
    dimensions_after_mm: tuple[float, float, float]
    calibrated: bool
    policy: str


def _dimensions(mesh: trimesh.Trimesh) -> tuple[float, float, float]:
    values = np.asarray(mesh.extents, dtype=float)
    return tuple(float(value) for value in values)


def normalize_generated_mesh_to_mm(
    mesh: trimesh.Trimesh, target_longest_mm: float = DEFAULT_GENERATED_SIZE_MM
) -> tuple[trimesh.Trimesh, UnitScaleReport]:
    """Donne une taille d'impression cohérente à une reconstruction sans échelle."""
    before = _dimensions(mesh)
    longest = max(before)
    if not np.isfinite(longest) or longest <= 0:
        raise ValueError("Le maillage n’a aucune dimension exploitable.")
    if target_longest_mm <= 0:
        raise ValueError("La taille cible doit être positive.")
    factor = float(target_longest_mm / longest)
    result = mesh.copy()
    result.apply_scale(factor)
    result.units = "mm"
    return result, UnitScaleReport(
        source_unit="arbitrary",
        target_unit="mm",
        scale_factor=factor,
        dimensions_before=before,
        dimensions_after_mm=_dimensions(result),
        calibrated=False,
        policy=f"longest-dimension-{target_longest_mm:g}mm",
    )


def convert_declared_units_to_mm(
    mesh: trimesh.Trimesh,
) -> tuple[trimesh.Trimesh, UnitScaleReport]:
    """Convertit une unité déclarée ; sans métadonnée, considère le fichier en mm."""
    aliases = {
        "mm": 1.0,
        "millimeter": 1.0,
        "millimeters": 1.0,
        "cm": 10.0,
        "centimeter": 10.0,
        "centimeters": 10.0,
        "m": 1000.0,
        "meter": 1000.0,
        "meters": 1000.0,
        "in": 25.4,
        "inch": 25.4,
        "inches": 25.4,
        "ft": 304.8,
        "feet": 304.8,
    }
    declared_unit = getattr(mesh, "units", None)
    source_unit = str(declared_unit or "mm").lower()
    factor = aliases.get(source_unit, 1.0)
    before = _dimensions(mesh)
    result = mesh.copy()
    if factor != 1.0:
        result.apply_scale(factor)
    result.units = "mm"
    return result, UnitScaleReport(
        source_unit=source_unit,
        target_unit="mm",
        scale_factor=factor,
        dimensions_before=before,
        dimensions_after_mm=_dimensions(result),
        calibrated=bool(declared_unit and source_unit in aliases),
        policy=(
            "declared-unit-conversion"
            if declared_unit and source_unit in aliases
            else "assume-millimeters"
        ),
    )


def save_unit_scale_report(report: UnitScaleReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
    return path
