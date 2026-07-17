from __future__ import annotations

import argparse
import gc
import json
import os
import sys
from pathlib import Path


AI_DIR = Path(__file__).resolve().parent
TRIPOSR_DIR = AI_DIR / "TripoSR"
sys.path.insert(0, str(AI_DIR))
sys.path.insert(1, str(TRIPOSR_DIR))


def detect_device(torch, preference: str = "auto"):
    if preference == "cpu":
        return "cpu", "CPU", "Processeur"
    if torch.cuda.is_available():
        backend = "ROCm" if getattr(torch.version, "hip", None) else "CUDA"
        return "cuda:0", backend, torch.cuda.get_device_name(0)
    if hasattr(torch, "xpu") and torch.xpu.is_available():
        name = torch.xpu.get_device_name(0) if hasattr(torch.xpu, "get_device_name") else "Intel GPU"
        return "xpu:0", "Intel XPU", name
    return "cpu", "CPU", "Processeur"


def probe() -> dict:
    import torch

    device, backend, name = detect_device(torch)
    return {
        "ready": True,
        "torch_version": torch.__version__,
        "device": device,
        "backend": backend,
        "device_name": name,
    }


def download_model() -> None:
    from huggingface_hub import snapshot_download
    import rembg

    snapshot_download(
        "stabilityai/TripoSR",
        allow_patterns=["config.yaml", "model.ckpt"],
    )
    # BiRefNet améliore nettement les contours fins et les arrière-plans
    # complexes par rapport au modèle U2Net historique de rembg.
    rembg.new_session("birefnet-general")


def select_resolution(torch, device: str, requested: int) -> int:
    if requested:
        return requested
    memory_gb = 0.0
    try:
        if device.startswith("cuda"):
            memory_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        elif device.startswith("xpu") and hasattr(torch.xpu, "get_device_properties"):
            memory_gb = torch.xpu.get_device_properties(0).total_memory / (1024**3)
    except Exception:
        memory_gb = 0.0
    if memory_gb >= 10:
        return 384
    if memory_gb >= 6:
        return 320
    return 256


def prepare_image(image_path: Path, processed_output: Path | None = None):
    import numpy as np
    import rembg
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps

    print("Préparation haute qualité de l’image…", flush=True)
    source = ImageOps.exif_transpose(Image.open(image_path)).convert("RGBA")
    alpha = np.asarray(source.getchannel("A"))
    foreground_ratio = float(np.count_nonzero(alpha > 8) / alpha.size)
    has_transparency = alpha.min() < 250 and 0.01 < foreground_ratio < 0.99

    if has_transparency:
        print("Arrière-plan transparent détecté : conservation du détourage original.", flush=True)
        cutout = source
        segmentation = "alpha-source"
    else:
        print("Suppression de l’arrière-plan avec BiRefNet haute résolution…", flush=True)
        try:
            session = rembg.new_session("birefnet-general")
            cutout = rembg.remove(source, session=session, post_process_mask=True)
            segmentation = "birefnet-general"
        except Exception as exc:
            print(f"BiRefNet indisponible ({exc}) : repli sur U2Net…", flush=True)
            cutout = rembg.remove(source, session=rembg.new_session("u2net"))
            segmentation = "u2net-fallback"

    cutout = cutout.convert("RGBA")
    alpha = np.asarray(cutout.getchannel("A"))
    ys, xs = np.where(alpha > 4)
    if not len(xs) or not len(ys):
        raise ValueError("Le détourage n’a détecté aucun objet exploitable.")

    # Recadrage exact, puis marge régulière : le modèle voit un objet centré,
    # grand, sans couper les extrémités ou les détails fins.
    cropped = cutout.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))
    side = max(cropped.size)
    canvas_side = max(512, int(round(side / 0.86)))
    canvas_side = min(canvas_side, 1024)
    if max(cropped.size) > int(canvas_side * 0.86):
        scale = (canvas_side * 0.86) / max(cropped.size)
        cropped = cropped.resize(
            (max(1, round(cropped.width * scale)), max(1, round(cropped.height * scale))),
            Image.Resampling.LANCZOS,
        )

    # Une légère accentuation compense les redimensionnements et la compression
    # fréquente des images Web sans inventer de nouveaux détails.
    rgb = ImageEnhance.Contrast(cropped.convert("RGB")).enhance(1.03)
    rgb = rgb.filter(ImageFilter.UnsharpMask(radius=1.0, percent=55, threshold=3))
    refined_alpha = cropped.getchannel("A").filter(ImageFilter.GaussianBlur(radius=0.25))
    cropped = rgb.convert("RGBA")
    cropped.putalpha(refined_alpha)

    canvas = Image.new("RGBA", (canvas_side, canvas_side), (0, 0, 0, 0))
    canvas.alpha_composite(
        cropped,
        ((canvas_side - cropped.width) // 2, (canvas_side - cropped.height) // 2),
    )
    rgba = np.asarray(canvas).astype(np.float32) / 255.0
    composite = rgba[:, :, :3] * rgba[:, :, 3:4] + (1 - rgba[:, :, 3:4]) * 0.5
    prepared = Image.fromarray((composite * 255.0).astype(np.uint8), mode="RGB")

    if processed_output:
        processed_output.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(processed_output)
    return prepared, segmentation


def _run_model(prepared, device: str, resolution: int):
    import torch
    from tsr.system import TSR

    model = TSR.from_pretrained(
        "stabilityai/TripoSR",
        config_name="config.yaml",
        weight_name="model.ckpt",
    )
    model.renderer.set_chunk_size(4096 if device == "cpu" else 8192)
    model.to(device)
    model.eval()
    with torch.inference_mode():
        scene_codes = model([prepared], device=device)
        return model.extract_mesh(
            scene_codes,
            has_vertex_color=True,
            resolution=resolution,
        )


def generate(
    image_path: Path,
    output_path: Path,
    resolution: int,
    device_preference: str = "auto",
    processed_output: Path | None = None,
) -> dict:
    import torch

    device, preferred_backend, device_name = detect_device(torch, device_preference)
    backend = preferred_backend
    selected_resolution = select_resolution(torch, device, resolution)
    print(f"Backend IA : {preferred_backend} — {device_name}", flush=True)
    print(
        f"Résolution géométrique sélectionnée : {selected_resolution} "
        f"({'automatique' if resolution == 0 else 'manuelle'})",
        flush=True,
    )

    prepared, segmentation = prepare_image(image_path, processed_output)

    print("Chargement du modèle TripoSR…", flush=True)
    print("Génération de la géométrie 3D…", flush=True)
    try:
        meshes = _run_model(prepared, device, selected_resolution)
    except Exception as gpu_error:
        if device == "cpu":
            raise
        print(
            f"Le backend {preferred_backend} a échoué ({gpu_error}). "
            "Nouvelle tentative automatique sur CPU…",
            flush=True,
        )
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        if hasattr(torch, "xpu") and torch.xpu.is_available():
            torch.xpu.empty_cache()
        device = "cpu"
        backend = f"CPU fallback ({preferred_backend})"
        # Le mode CPU privilégie une résolution raisonnable pour éviter des
        # temps de plusieurs dizaines de minutes et une consommation excessive.
        selected_resolution = min(selected_resolution, 256)
        meshes = _run_model(prepared, device, selected_resolution)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    meshes[0].export(output_path)
    result = {
        "output": str(output_path),
        "backend": backend,
        "preferred_backend": preferred_backend,
        "device_name": device_name,
        "resolution": selected_resolution,
        "requested_resolution": resolution,
        "segmentation": segmentation,
        "vertices": len(meshes[0].vertices),
        "faces": len(meshes[0].faces),
    }
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", nargs="?", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--resolution", type=int, default=0)
    parser.add_argument("--processed-output", type=Path)
    parser.add_argument("--device", choices=["auto", "cpu"], default="auto")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--download-model", action="store_true")
    args = parser.parse_args()

    if args.probe:
        print(json.dumps(probe(), ensure_ascii=False))
        return 0
    if args.download_model:
        download_model()
        print("Modèle TripoSR téléchargé.")
        return 0
    if not args.image or not args.output:
        parser.error("image et --output sont requis")
    if args.resolution != 0 and not 128 <= args.resolution <= 384:
        parser.error("--resolution doit valoir 0 (auto) ou être compris entre 128 et 384")
    generate(
        args.image,
        args.output,
        args.resolution,
        args.device,
        args.processed_output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
