from copy import deepcopy
from unittest.mock import Mock

import pytest

from visuaslide import SurveyProject
from visuaslide.exceptions import PublishingError
from visuaslide.google_bootstrap import project_template_layout
from visuaslide.google_outputs import MIME_TYPES, ManagedOutputStore
from visuaslide.google_publisher import GoogleReportPublisher, managed_sheet_identity
from visuaslide.google_template import template_object_id
from visuaslide.layouts import build_default_layout
from visuaslide.reporting import build_presentation_content
from visuaslide.testing import FixtureSource
from visuaslide.update_plan import managed_object_id, plan_report_update


def _deck(content, plan):
    by_key = {entry.object_key: entry.object_id for entry in plan.mapping.entries}
    table_ids = {item.object_id: by_key[f"table:{item.publication_key}"] for item in content.tables}
    chart_ids = {item.object_id: by_key[f"chart:{item.publication_key}"] for item in content.charts}
    pages = []
    for slide in build_default_layout(content).slides:
        title_id = (
            managed_object_id("title:report")
            if slide.slide_key == "cover"
            else template_object_id(f"title:{slide.slide_key}")
        )
        elements = [{"objectId": title_id}]
        elements.extend({"objectId": by_key[f"text:{key}"]} for key in slide.text_ids)
        elements.extend({"objectId": table_ids[key]} for key in slide.table_ids)
        elements.extend({"objectId": chart_ids[key]} for key in slide.chart_ids)
        pages.append(
            {"objectId": template_object_id(f"slide:{slide.slide_key}"), "pageElements": elements}
        )
    return {"slides": pages}


@pytest.fixture
def google_case(multiselect_case):
    config, snapshot = multiselect_case
    analysis = SurveyProject(config, source=FixtureSource(snapshot)).refresh(dry_run=True).analysis
    content = build_presentation_content(analysis, config.report)
    plan = plan_report_update(content)
    store = ManagedOutputStore(config.project_dir)
    registry = store.load_or_create().model_copy(
        update={"files": {"workbook": "synthetic-workbook", "presentation": "synthetic-deck"}}
    )
    store.save(registry)
    sheets, drive, slides = Mock(), Mock(), Mock()

    def file_get(fileId, fields):
        role = next(role for role, identity in registry.files.items() if identity == fileId)
        return Mock(
            execute=lambda: {
                "id": fileId,
                "mimeType": MIME_TYPES[role],
                "appProperties": {
                    "visuaslide_project": registry.project_id,
                    "visuaslide_role": role,
                },
            }
        )

    drive.files.return_value.get.side_effect = file_get
    deck = _deck(content, plan)
    slides.presentations.return_value.get.return_value.execute.side_effect = lambda: deepcopy(deck)
    tabs = []
    for index, table in enumerate(content.tables):
        sheet_id, title = managed_sheet_identity(registry.project_id, table.publication_key)
        tabs.append(
            {
                "properties": {"sheetId": sheet_id, "title": title},
                "charts": [{"chartId": 100 + index}]
                if table.source_analysis_id != "score_summary"
                else [],
            }
        )
    sheets.spreadsheets.return_value.get.return_value.execute.return_value = {"sheets": tabs}
    publisher = GoogleReportPublisher(config, sheets, drive, slides)
    return publisher, content, plan, deck, sheets, slides


def test_bootstrap_and_actual_publication_use_identical_pages(google_case):
    publisher, content, plan, _, sheets, slides = google_case
    assert project_template_layout(publisher.config) == build_default_layout(content)
    for step in ("workbook", "charts", "slides"):
        publisher.publish_step(step, content, plan)
    batches = slides.presentations.return_value.batchUpdate.call_args_list
    created = [
        request["createTable"]
        for call in batches
        for request in call.kwargs["body"]["requests"]
        if "createTable" in request
    ]
    assert [table["rows"] for table in created[:2]] == [11, 4]
    assert publisher.store.load_or_create().mapping == plan.mapping
    updates = sheets.spreadsheets.return_value.values.return_value.update.call_args_list
    faculty_ranges = {
        managed_sheet_identity(publisher.store.load_or_create().project_id, table.publication_key)[
            1
        ]
        for table in content.tables[:2]
    }
    written = [call.kwargs for call in updates if call.kwargs["range"].endswith("!A1")]
    assert {item["range"].split("'")[1] for item in written[:2]} == faculty_ranges
    assert [len(item["body"]["values"]) for item in written[:2]] == [11, 4]


def test_uncertain_page_creation_is_reconciled_before_retry(google_case):
    publisher, content, plan, deck, _, slides = google_case
    continuation_id = template_object_id("slide:analysis_faculty_counts/page/2")
    deck["slides"] = [page for page in deck["slides"] if page["objectId"] != continuation_id]
    attempted = []

    def create_then_fail(**kwargs):
        requests = kwargs["body"]["requests"]
        for request in requests:
            if "createSlide" in request:
                identity = request["createSlide"]["objectId"]
                attempted.append(identity)
                deck["slides"].append({"objectId": identity, "pageElements": []})
            if "createShape" in request:
                shape = request["createShape"]
                page_id = shape["elementProperties"]["pageObjectId"]
                next(page for page in deck["slides"] if page["objectId"] == page_id)[
                    "pageElements"
                ].append({"objectId": shape["objectId"]})
        raise TimeoutError("synthetic uncertain response")

    slides.presentations.return_value.batchUpdate.side_effect = create_then_fail
    with pytest.raises(PublishingError, match="resume"):
        publisher._ensure_slide_pages(content, plan)
    assert publisher.store.load_or_create().pending_pages
    slides.presentations.return_value.batchUpdate.side_effect = None
    publisher._ensure_slide_pages(content, plan)
    assert attempted == [continuation_id]
    assert publisher.store.load_or_create().pending_pages == ()
    last_requests = slides.presentations.return_value.batchUpdate.call_args.kwargs["body"][
        "requests"
    ]
    assert not any(
        "createSlide" in request or "createShape" in request for request in last_requests
    )


def test_missing_registered_page_fails_before_any_creation(google_case):
    publisher, content, plan, deck, _, slides = google_case
    publisher.store.save(
        publisher.store.load_or_create().model_copy(
            update={
                "pages": {
                    slide.slide_key: template_object_id(f"slide:{slide.slide_key}")
                    for slide in build_default_layout(content).slides
                }
            }
        )
    )
    deck["slides"].pop(2)
    with pytest.raises(PublishingError, match="previously managed report page"):
        publisher._ensure_slide_pages(content, plan)
    slides.presentations.return_value.batchUpdate.assert_not_called()


def test_page_cleanup_preserves_unregistered_user_slides(google_case):
    publisher, content, plan, deck, _, slides = google_case
    publisher.store.save(
        publisher.store.load_or_create().model_copy(update={"mapping": plan.mapping})
    )
    deck["slides"].append({"objectId": "user-slide", "pageElements": [{"objectId": "user-shape"}]})
    retained_tables = (content.tables[0], *content.tables[2:])
    retained_charts = (content.charts[0], *content.charts[2:])
    removed_caption = next(text.object_id for text in content.text_blocks if text.page_key)
    smaller = content.model_copy(
        update={
            "tables": retained_tables,
            "charts": retained_charts,
            "text_blocks": tuple(
                text for text in content.text_blocks if text.object_id != removed_caption
            ),
        }
    )
    next_plan = plan_report_update(smaller, plan.mapping)
    publisher._ensure_slide_pages(smaller, next_plan)
    requests = slides.presentations.return_value.batchUpdate.call_args.kwargs["body"]["requests"]
    deleted = {
        request["deleteObject"]["objectId"] for request in requests if "deleteObject" in request
    }
    assert deleted == {template_object_id("slide:analysis_faculty_counts/page/2")}
