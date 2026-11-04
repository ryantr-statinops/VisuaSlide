from unittest.mock import Mock

import pytest

from visuaslide.exceptions import PublishingError
from visuaslide.google_template import GoogleSlidesTemplate, template_object_id
from visuaslide.layouts import PresentationLayout, SlideLayout


def _layout() -> PresentationLayout:
    return PresentationLayout(
        slides=(
            SlideLayout(
                slide_key="cover", role="cover", title="Khảo sát", text_ids=("sample_size",)
            ),
        )
    )


def test_template_builds_stable_slide_and_vietnamese_text_shapes() -> None:
    slides = Mock()
    slides.presentations.return_value.get.return_value.execute.return_value = {
        "pageSize": {
            "width": {"magnitude": 9144000},
            "height": {"magnitude": 5143500},
        },
        "slides": [],
    }
    outputs = Mock()
    outputs.bootstrap_file.return_value = "template-id"

    result = GoogleSlidesTemplate(slides, outputs).bootstrap(_layout())

    assert result == "template-id"
    outputs.bootstrap_file.assert_called_once_with("template", "VisuaSlide 16:9 template")
    body = slides.presentations.return_value.batchUpdate.call_args.kwargs["body"]
    requests = body["requests"]
    assert requests[0]["createSlide"]["objectId"] == template_object_id("slide:cover")
    assert any(item.get("insertText", {}).get("text") == "Khảo sát" for item in requests)
    assert any(item.get("insertText", {}).get("text") == "{{sample_size}}" for item in requests)
    assert sum("updateTextStyle" in item for item in requests) == 2


def test_template_rejects_non_widescreen_file_before_writing() -> None:
    slides = Mock()
    slides.presentations.return_value.get.return_value.execute.return_value = {
        "pageSize": {"width": {"magnitude": 720}, "height": {"magnitude": 540}}
    }
    outputs = Mock()
    outputs.bootstrap_file.return_value = "template-id"
    with pytest.raises(PublishingError, match="16:9"):
        GoogleSlidesTemplate(slides, outputs).bootstrap(_layout())
    slides.presentations.return_value.batchUpdate.assert_not_called()
