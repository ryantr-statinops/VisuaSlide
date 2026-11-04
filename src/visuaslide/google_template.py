"""Default managed Google Slides template built from the offline layout."""

from __future__ import annotations

import uuid
from typing import Any

from visuaslide.exceptions import PublishingError
from visuaslide.google_outputs import GoogleOutputManager
from visuaslide.layouts import PresentationLayout

_OBJECT_NAMESPACE = uuid.UUID("3f73634d-46d4-448e-b99e-691cb25a88a4")


def template_object_id(key: str) -> str:
    """Stable Slides-compatible object ID for a managed layout element."""
    return "vs_" + uuid.uuid5(_OBJECT_NAMESPACE, key).hex


class GoogleSlidesTemplate:
    def __init__(self, slides_service: Any, outputs: GoogleOutputManager) -> None:
        self.slides = slides_service
        self.outputs = outputs

    def bootstrap(self, layout: PresentationLayout) -> str:
        """Create the default template once and repair missing generated elements."""
        template_id = self.outputs.bootstrap_file("template", "VisuaSlide 16:9 template")
        try:
            presentation = self.slides.presentations().get(presentationId=template_id).execute()
        except Exception as exc:
            raise PublishingError("Could not inspect the Google Slides template.") from exc
        page_size = presentation.get("pageSize", {})
        width = page_size.get("width", {}).get("magnitude")
        height = page_size.get("height", {}).get("magnitude")
        if not width or not height or abs(width / height - 16 / 9) > 0.01:
            raise PublishingError("The managed presentation is not widescreen 16:9.")
        existing_slides = {slide["objectId"]: slide for slide in presentation.get("slides", [])}
        requests: list[dict[str, object]] = []
        for slide in layout.slides:
            slide_id = template_object_id(f"slide:{slide.slide_key}")
            existing = existing_slides.get(slide_id)
            if existing is None:
                requests.append(
                    {
                        "createSlide": {
                            "objectId": slide_id,
                            "slideLayoutReference": {"predefinedLayout": "BLANK"},
                        }
                    }
                )
            existing_elements = (
                {item["objectId"] for item in existing.get("pageElements", [])}
                if existing
                else set()
            )
            elements = [(f"title:{slide.slide_key}", slide.title)]
            elements.extend((f"text:{text_id}", f"{{{{{text_id}}}}}") for text_id in slide.text_ids)
            for index, (key, text) in enumerate(elements):
                object_id = template_object_id(key)
                if object_id in existing_elements:
                    continue
                requests.extend(self._text_box(slide_id, object_id, text, index))
        if requests:
            try:
                self.slides.presentations().batchUpdate(
                    presentationId=template_id, body={"requests": requests}
                ).execute()
            except Exception as exc:
                raise PublishingError("Could not build the managed Slides template.") from exc
        return template_id

    @staticmethod
    def _text_box(slide_id: str, object_id: str, text: str, index: int) -> list[dict]:
        return [
            {
                "createShape": {
                    "objectId": object_id,
                    "shapeType": "TEXT_BOX",
                    "elementProperties": {
                        "pageObjectId": slide_id,
                        "size": {
                            "width": {"magnitude": 640, "unit": "PT"},
                            "height": {"magnitude": 60, "unit": "PT"},
                        },
                        "transform": {
                            "scaleX": 1,
                            "scaleY": 1,
                            "translateX": 40,
                            "translateY": 24 + 76 * index,
                            "unit": "PT",
                        },
                    },
                }
            },
            {"insertText": {"objectId": object_id, "text": text}},
            {
                "updateTextStyle": {
                    "objectId": object_id,
                    "textRange": {"type": "ALL"},
                    "style": {"fontFamily": "Arial"},
                    "fields": "fontFamily",
                }
            },
        ]
