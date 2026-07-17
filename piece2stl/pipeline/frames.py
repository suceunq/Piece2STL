from dataclasses import dataclass
from pathlib import Path

import cv2

from ..config import find_ffmpeg
from .process import CancelCallback, LogCallback, run_command


@dataclass
class FrameInfo:
    path: Path
    blur_score: float
    is_blurry: bool


def extract_frames(
    video_path: Path,
    output_dir: Path,
    target_count: int = 60,
    log: LogCallback | None = None,
    cancel: CancelCallback | None = None,
) -> list[Path]:
    """Échantillonne ~target_count frames régulièrement réparties sur la vidéo."""
    output_dir.mkdir(parents=True, exist_ok=True)
    duration = _probe_duration_seconds(video_path)
    fps = max(target_count / duration, 0.1) if duration else 1.0

    pattern = str(output_dir / "frame_%04d.jpg")
    run_command(
        [
            find_ffmpeg(),
            "-y",
            "-i",
            str(video_path),
            "-vf",
            f"fps={fps:.4f}",
            "-q:v",
            "2",
            pattern,
        ],
        log=log,
        cancel=cancel,
    )
    return sorted(output_dir.glob("frame_*.jpg"))


def _probe_duration_seconds(video_path: Path) -> float:
    cap = cv2.VideoCapture(str(video_path))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        if fps <= 0 or frame_count <= 0:
            return 0.0
        return frame_count / fps
    finally:
        cap.release()


def blur_score(image_path: Path) -> float:
    """Variance du Laplacien : plus c'est bas, plus l'image est floue."""
    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        return 0.0
    return float(cv2.Laplacian(image, cv2.CV_64F).var())


def score_images(
    image_paths: list[Path], blur_threshold: float = 60.0
) -> list[FrameInfo]:
    infos = []
    for path in image_paths:
        score = blur_score(path)
        infos.append(FrameInfo(path=path, blur_score=score, is_blurry=score < blur_threshold))
    return infos
