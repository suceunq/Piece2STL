"""Remplacement portable de torchmcubes basé sur scikit-image.

TripoSR importe ``torchmcubes.marching_cubes``. L'extension d'origine dépend de
CUDA ou d'une compilation C++; cette version déplace uniquement le champ de
densité final sur CPU et fonctionne avec ROCm, CUDA, XPU et CPU.
"""

import numpy as np
import torch
from skimage import measure


def marching_cubes(volume: torch.Tensor, threshold: float):
    array = volume.detach().float().cpu().numpy()
    vertices, faces, _normals, _values = measure.marching_cubes(
        array, level=float(threshold), allow_degenerate=False
    )
    return (
        torch.from_numpy(np.ascontiguousarray(vertices)).float(),
        torch.from_numpy(np.ascontiguousarray(faces.astype(np.int64))).long(),
    )
