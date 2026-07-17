import numpy as np
import trimesh


def scale_factor_from_two_points(
    point_a: np.ndarray, point_b: np.ndarray, real_distance_mm: float
) -> float:
    """Calcule le facteur d'échelle à appliquer pour que la distance entre les deux
    points cliqués corresponde à `real_distance_mm` (en mm, unité cible du mesh)."""
    measured_distance = float(np.linalg.norm(np.asarray(point_a) - np.asarray(point_b)))
    if measured_distance <= 0:
        raise ValueError("Les deux points sélectionnés sont confondus.")
    if real_distance_mm <= 0:
        raise ValueError("La distance réelle doit être strictement positive.")
    return real_distance_mm / measured_distance


def apply_scale(mesh: trimesh.Trimesh, factor: float) -> trimesh.Trimesh:
    scaled = mesh.copy()
    scaled.apply_scale(factor)
    return scaled
