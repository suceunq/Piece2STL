from dataclasses import asdict, dataclass
import json
from pathlib import Path

from .pipeline.frames import FrameInfo


@dataclass(frozen=True)
class InputQualityReport:
    total_images: int
    blurry_images: int
    selected_images: int
    blurry_files: tuple[str, ...]
    excluded_blurry: bool

    @property
    def blurry_ratio(self) -> float:
        return self.blurry_images / self.total_images if self.total_images else 0.0


def select_images(
    infos: list[FrameInfo], exclude_blurry: bool, minimum_images: int = 10
) -> tuple[list[Path], InputQualityReport]:
    selected = [info.path for info in infos if not (exclude_blurry and info.is_blurry)]
    if len(selected) < minimum_images:
        raise ValueError(
            f"Seulement {len(selected)} images resteraient après filtrage; "
            f"il en faut au moins {minimum_images}. Désactivez l’exclusion automatique "
            "ou améliorez la prise de vue."
        )
    blurry = [info for info in infos if info.is_blurry]
    return selected, InputQualityReport(
        total_images=len(infos),
        blurry_images=len(blurry),
        selected_images=len(selected),
        blurry_files=tuple(info.path.name for info in blurry),
        excluded_blurry=exclude_blurry,
    )


def save_quality_report(report: InputQualityReport, path: Path) -> Path:
    data = asdict(report)
    data["blurry_ratio"] = report.blurry_ratio
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path
