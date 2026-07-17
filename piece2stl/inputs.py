from pathlib import Path


SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def list_images(image_dir: Path) -> list[Path]:
    """Retourne les images prises en charge, sans dépendre de la casse."""
    if not image_dir.is_dir():
        return []
    return sorted(
        path
        for path in image_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
    )


def validate_source(
    image_dir: Path | None = None, video_path: Path | None = None
) -> list[str]:
    errors: list[str] = []
    if bool(image_dir) == bool(video_path):
        return ["Choisissez soit un dossier de photos, soit une vidéo."]

    if image_dir:
        if not image_dir.is_dir():
            errors.append("Le dossier de photos n'existe pas.")
        elif not list_images(image_dir):
            errors.append("Aucune image JPG, JPEG ou PNG n'a été trouvée.")

    if video_path and not video_path.is_file():
        errors.append("Le fichier vidéo n'existe pas.")
    return errors
