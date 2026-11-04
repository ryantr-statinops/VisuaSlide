from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch

from visuaslide.config import load_config
from visuaslide.google_layout_review import download_review_thumbnails
from visuaslide.google_outputs import ManagedOutputStore

ROOT = Path(__file__).parents[2]


def test_thumbnail_review_saves_private_image_only_in_runtime(tmp_path) -> None:
    config = load_config(ROOT / "examples/survey.example.toml").model_copy(
        update={"project_dir": tmp_path}
    )
    store = ManagedOutputStore(tmp_path)
    registry = store.load_or_create()
    store.save(registry.model_copy(update={"files": {"presentation": "deck-id"}}))
    drive, slides = Mock(), Mock()
    drive.files.return_value.get.return_value.execute.return_value = {
        "id": "deck-id",
        "mimeType": "application/vnd.google-apps.presentation",
        "appProperties": {
            "visuaslide_project": registry.project_id,
            "visuaslide_role": "presentation",
        },
    }
    slides.presentations.return_value.get.return_value.execute.return_value = {
        "pageSize": {
            "width": {"magnitude": 9144000},
            "height": {"magnitude": 5143500},
        },
        "slides": [{"objectId": "slide-id"}],
    }
    pages = slides.presentations.return_value.pages.return_value
    pages.getThumbnail.return_value.execute.return_value = {
        "contentUrl": "https://private.example/short-lived"
    }
    with (
        patch("visuaslide.google_layout_review.GoogleCredentialStore.load"),
        patch("visuaslide.google_layout_review.build", side_effect=[drive, slides]),
        patch("visuaslide.google_layout_review.urlopen", return_value=BytesIO(b"PNG")) as open_url,
    ):
        paths = download_review_thumbnails(config)

    assert len(paths) == 1
    assert paths[0] == tmp_path / "visual_review" / "slide-01.png"
    assert paths[0].read_bytes() == b"PNG"
    open_url.assert_called_once_with("https://private.example/short-lived", timeout=20)
