"""Create the three application-managed Google reporting files."""

from __future__ import annotations

from googleapiclient.discovery import build

from visuaslide.config import ProjectConfig
from visuaslide.google_auth import GoogleCredentialStore
from visuaslide.google_outputs import GoogleOutputManager, verify_configured_output_ids
from visuaslide.google_template import GoogleSlidesTemplate
from visuaslide.layouts import PresentationLayout, SlideLayout


def project_template_layout(config: ProjectConfig) -> PresentationLayout:
    """Build stable template slide roles from configured analysis IDs."""
    slides = [
        SlideLayout(
            slide_key="cover",
            role="cover",
            title=config.report.title,
            text_ids=("research_question",),
        ),
        SlideLayout(
            slide_key="context",
            role="context",
            title="Phương pháp và mẫu",
            text_ids=("sampling_method", "collection_period", "sample_size"),
        ),
    ]
    for specification in config.analysis.specifications:
        slides.append(
            SlideLayout(
                slide_key=f"analysis_{specification.id}",
                role="analysis",
                title=specification.id.replace("_", " ").capitalize(),
                text_ids=(f"caption_{specification.id}",),
                table_ids=(f"table_{specification.id}",),
                chart_ids=(f"chart_{specification.id}",)
                if specification.kind != "numeric_summary"
                else (),
            )
        )
    slides.append(
        SlideLayout(
            slide_key="conclusion",
            role="conclusion",
            title="Kết luận",
            text_ids=("conclusion",),
        )
    )
    return PresentationLayout(locale=config.report.locale, slides=tuple(slides))


class GoogleBootstrapper:
    def __init__(self, config: ProjectConfig) -> None:
        self.config = config

    def bootstrap_outputs(self) -> dict[str, str]:
        """Create/reuse workbook, template, and a separate presentation copy."""
        credentials = GoogleCredentialStore(self.config.project_dir).load()
        drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
        slides = build("slides", "v1", credentials=credentials, cache_discovery=False)
        outputs = GoogleOutputManager(
            drive, self.config.project_dir, self.config.source.spreadsheet_id
        )
        verify_configured_output_ids(self.config, outputs.store.load_or_create())
        workbook_id = outputs.bootstrap_workbook()
        template_id = GoogleSlidesTemplate(slides, outputs).bootstrap(
            project_template_layout(self.config)
        )
        presentation_id = outputs.bootstrap_file(
            "presentation", "VisuaSlide survey report", copy_from=template_id
        )
        return {
            "workbook": workbook_id,
            "template": template_id,
            "presentation": presentation_id,
        }
