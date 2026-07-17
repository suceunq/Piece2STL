"""CLI : photos ou vidéo d'une vraie pièce -> mesh nettoyé -> STL (non mis à l'échelle).

Usage:
  python scripts/scan_to_stl.py --images real_data/ma_piece/images --workspace real_data/ma_piece/workspace
  python scripts/scan_to_stl.py --video real_data/ma_piece/scan.mp4 --workspace real_data/ma_piece/workspace

Ensuite, pour mettre à l'échelle : python scripts/pick_scale.py <workspace>/mesh_cleaned.ply
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from piece2stl.pipeline.export import export_mesh, is_watertight, load_mesh
from piece2stl.pipeline.frames import extract_frames, score_images
from piece2stl.pipeline.run_pipeline import reconstruct
from piece2stl.inputs import list_images


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, help="Dossier contenant les photos")
    parser.add_argument("--video", type=Path, help="Fichier vidéo à découper en frames")
    parser.add_argument("--workspace", type=Path, required=True, help="Dossier de travail")
    parser.add_argument(
        "--target-frames", type=int, default=60, help="Nb de frames à extraire si --video"
    )
    args = parser.parse_args()

    if bool(args.images) == bool(args.video):
        parser.error("Fournis soit --images, soit --video")

    args.workspace = args.workspace.resolve()
    if args.images:
        args.images = args.images.resolve()
    if args.video:
        args.video = args.video.resolve()

    workspace = args.workspace
    workspace.mkdir(parents=True, exist_ok=True)

    if args.video:
        image_dir = workspace / "frames"
        print(f"Extraction de frames depuis {args.video}...")
        frame_paths = extract_frames(args.video, image_dir, target_count=args.target_frames)
        infos = score_images(frame_paths)
        blurry = [i for i in infos if i.is_blurry]
        print(f"{len(frame_paths)} frames extraites, {len(blurry)} flaguées floues (score bas).")
        for info in blurry:
            print(f"  flou: {info.path.name} (score={info.blur_score:.1f})")
    else:
        image_dir = args.images
        image_paths = list_images(image_dir)
        image_count = len(image_paths)
        if image_count < 20:
            print(
                f"Attention : seulement {image_count} images trouvées dans {image_dir}. "
                "20-30 minimum recommandées pour une bonne reconstruction."
            )
        infos = score_images(image_paths)
        blurry = [i for i in infos if i.is_blurry]
        if blurry:
            print(f"{len(blurry)} images flaguées floues (score bas) :")
            for info in blurry:
                print(f"  {info.path.name} (score={info.blur_score:.1f})")

    print(f"\nReconstruction en cours (peut prendre plusieurs minutes en CPU)...\n")
    cleaned_mesh_path = reconstruct(
        image_dir=image_dir, workspace_dir=workspace, sequential=bool(args.video)
    )

    mesh = load_mesh(cleaned_mesh_path)
    print(f"\nMesh nettoyé : {cleaned_mesh_path}")
    print(f"Sommets: {len(mesh.vertices)}, Faces: {len(mesh.faces)}")
    watertight = is_watertight(mesh)
    print(f"Watertight: {watertight}")
    if not watertight:
        print(
            "Le mesh n'est pas étanche - probablement des trous dus à une couverture "
            "incomplète (angles manquants) ou une surface trop réfléchissante/transparente."
        )

    stl_path = export_mesh(mesh, workspace / "export_unscaled.stl")
    print(f"\nSTL exporté (PAS encore à l'échelle réelle) : {stl_path}")
    print(f"Pour mettre à l'échelle : python scripts/pick_scale.py {cleaned_mesh_path}")


if __name__ == "__main__":
    main()
