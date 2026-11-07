"""Create the three application-managed Google reporting files."""

from __future__ import annotations

from googleapiclient.discovery import build

from visuaslide.config import FrequencyAnalysis, MultiFrequencyAnalysis, ProjectConfig
from visuaslide.google_auth import GoogleCredentialStore
from visuaslide.google_outputs import GoogleOutputManager, verify_configured_output_ids
from visuaslide.google_template import GoogleSlidesTemplate
from visuaslide.layouts import PresentationLayout, SlideLayout
from visuaslide.reporting import projection_object_id, report_page_keys


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
    variables = {variable.name: variable for variable in config.survey_schema.variables}
    for specification in config.analysis.specifications:
        keys = (specification.id,)
        if isinstance(specification, (FrequencyAnalysis, MultiFrequencyAnalysis)):
            keys = report_page_keys(
                specification.id, len(variables[specification.variable].categories)
            )
        for index, key in enumerate(keys):
            page_key = key if index else None
            title = specification.id.replace("_", " ").capitalize()
            if len(keys) > 1:
                title += f" ({index + 1}/{len(keys)})"
            slides.append(
                SlideLayout(
                    slide_key=f"analysis_{key}",
                    role="analysis",
                    title=title,
                    text_ids=(projection_object_id("caption", specification.id, page_key),),
                    table_ids=(projection_object_id("table", specification.id, page_key),),
                    chart_ids=(projection_object_id("chart", specification.id, page_key),)
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
