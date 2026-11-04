"""Save private Google Slides thumbnails for local visual review."""

from __future__ import annotations

from pathlib import Path
from urllib.request import urlopen

from googleapiclient.discovery import build

from visuaslide.config import ProjectConfig
from visuaslide.exceptions import PublishingError
from visuaslide.google_auth import GoogleCredentialStore
from visuaslide.google_outputs import ManagedOutputStore, verify_managed_output


def download_review_thumbnails(config: ProjectConfig) -> tuple[Path, ...]:
    """Download each slide thumbnail into ignored project runtime storage."""
    credentials = GoogleCredentialStore(config.project_dir).load()
    drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
    slides = build("slides", "v1", credentials=credentials, cache_discovery=False)
    registry = ManagedOutputStore(config.project_dir).load_or_create()
    deck_id = registry.files.get("presentation")
    if deck_id is None:
        raise PublishingError("Bootstrap the managed presentation before layout review.")
    verify_managed_output(
        drive,
        file_id=deck_id,
        role="presentation",
        project_id=registry.project_id,
        source_spreadsheet_id=config.source.spreadsheet_id,
    )
    try:
        deck = (
            slides.presentations()
            .get(presentationId=deck_id, fields="pageSize,slides(objectId)")
            .execute()
        )
    except Exception as exc:
        raise PublishingError("Could not inspect the managed presentation for review.") from exc
    size = deck.get("pageSize", {})
    width = size.get("width", {}).get("magnitude")
    height = size.get("height", {}).get("magnitude")
    if not width or not height or abs(width / height - 16 / 9) > 0.01:
        raise PublishingError("The managed presentation is not widescreen 16:9.")
    output_dir = Path(config.project_dir).resolve() / "visual_review"
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for index, slide in enumerate(deck.get("slides", []), start=1):
        try:
            thumbnail = (
                slides.presentations()
                .pages()
                .getThumbnail(
                    presentationId=deck_id,
                    pageObjectId=slide["objectId"],
                    thumbnailProperties_thumbnailSize="LARGE",
                )
                .execute()
            )
            with urlopen(thumbnail["contentUrl"], timeout=20) as response:
                image_data = response.read()
        except Exception as exc:
            raise PublishingError("Could not download a private slide thumbnail.") from exc
        path = output_dir / f"slide-{index:02d}.png"
        path.write_bytes(image_data)
        paths.append(path)
    return tuple(paths)
