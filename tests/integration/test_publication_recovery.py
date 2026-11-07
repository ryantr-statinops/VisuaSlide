import json
from pathlib import Path
from unittest.mock import patch

import pytest

from visuaslide import SurveyProject
from visuaslide.config import load_config
from visuaslide.exceptions import ConfigurationError, PublishingError, StorageError
from visuaslide.models import RunStatus
from visuaslide.publications import PublicationStore
from visuaslide.publisher import FakeReportPublisher
from visuaslide.runs import RunStore, _sha256, effective_config_hash
from visuaslide.snapshots import SourceSnapshot, utc_now
from visuaslide.testing import FixtureSource


class MustNotRead:
    def read(self, source):
        raise AssertionError("resume must not reacquire the source")


@pytest.mark.parametrize("failed_step", ["workbook", "charts", "slides"])
def test_resume_uses_saved_plan_after_each_uncertain_side_effect(multiselect_case, failed_step):
    config, snapshot = multiselect_case

    class FailAfterStep(FakeReportPublisher):
        failed = False

        def publish_step(self, step, content, plan):
            super().publish_step(step, content, plan)
            if step == failed_step and not self.failed:
                self.failed = True
                raise PublishingError("synthetic checkpoint fault")

    publisher = FailAfterStep()
    project = SurveyProject(config, source=FixtureSource(snapshot), publisher=publisher)
    with pytest.raises(PublishingError, match="synthetic checkpoint fault"):
        project.refresh()
    (manifest_path,) = (config.project_dir / "runs").glob("*.json")
    run_id = manifest_path.stem
    failed = project.inspect_run(run_id)
    assert failed.status == RunStatus.FAILED
    saved = PublicationStore(config.project_dir).load(run_id)
    assert saved.content.layout_version == "2"
    assert [len(table.rows) for table in saved.content.tables[:2]] == [10, 3]
    artifact = (config.project_dir / "publications" / f"{run_id}.json").read_bytes()
    with patch(
        "visuaslide.reporting.build_presentation_content", side_effect=AssertionError("rebuilt")
    ):
        recovered = SurveyProject(config, source=MustNotRead(), publisher=publisher).resume(run_id)
    assert recovered.status == RunStatus.COMPLETED
    assert recovered.analysis == failed.analysis
    assert recovered.snapshot_id == failed.snapshot_id
    assert (config.project_dir / "publications" / f"{run_id}.json").read_bytes() == artifact
    assert publisher.mapping == saved.plan.mapping
    assert len(publisher.objects) == len(saved.plan.mapping.entries)


def _legacy_project(tmp_path, *, thirteen=False):
    root = Path(__file__).parents[2]
    config = load_config(root / "examples/survey.example.toml").model_copy(
        update={"project_dir": tmp_path}
    )
    if thirteen:
        variables = tuple(
            variable.model_copy(
                update={"categories": (*variable.categories, *(f"Year {n}" for n in range(5, 14)))}
            )
            if variable.name == "study_year"
            else variable
            for variable in config.survey_schema.variables
        )
        config = config.model_copy(
            update={
                "survey_schema": config.survey_schema.model_copy(update={"variables": variables}),
                "analysis": config.analysis.model_copy(
                    update={
                        "specifications": tuple(
                            spec
                            for spec in config.analysis.specifications
                            if spec.kind != "crosstab"
                        )
                    }
                ),
            }
        )
    fixture = json.loads((root / "tests/fixtures/synthetic_responses.json").read_bytes())
    snapshot = SourceSnapshot.capture(
        config.source,
        headers=tuple(fixture["headers"]),
        rows=tuple(tuple(row) for row in fixture["rows"]),
        acquired_at=utc_now(),
    )
    publisher = FakeReportPublisher()
    project = SurveyProject(config, source=FixtureSource(snapshot), publisher=publisher)
    ready = project.refresh(dry_run=True)
    store = RunStore(tmp_path)
    manifest = store.load(ready.run_id)
    payload = config.model_dump(mode="json", by_alias=True)
    for variable in payload["schema"]["variables"]:
        for name in ("aliases", "separator", "allowed_values"):
            variable.pop(name)
    legacy_hash = _sha256(payload)
    assert legacy_hash == effective_config_hash(config)
    store.save(
        manifest.model_copy(
            update={"template_version": None, "sdk_version": "0.1.0", "config_hash": legacy_hash}
        )
    )
    return project, ready, publisher


def test_legacy_manifest_hash_and_one_page_resume_are_supported(tmp_path):
    project, ready, publisher = _legacy_project(tmp_path)
    project.source = MustNotRead()
    result = project.resume(ready.run_id)
    assert result.status == RunStatus.COMPLETED
    saved = PublicationStore(tmp_path).load(ready.run_id)
    assert saved.content.layout_version == "1"
    assert all(table.page_key is None for table in saved.content.tables)
    assert publisher.mapping == saved.plan.mapping
    assert project.analyze(ready.snapshot_id).tables == ready.analysis.tables


def test_legacy_layout_overflow_requires_a_new_refresh(tmp_path):
    project, ready, publisher = _legacy_project(tmp_path, thirteen=True)
    with pytest.raises(PublishingError, match="start a new refresh"):
        project.resume(ready.run_id)
    assert publisher.objects == {}
    fresh = project.refresh()
    assert fresh.status == RunStatus.COMPLETED
    assert PublicationStore(tmp_path).load(fresh.run_id).content.layout_version == "2"


def test_ready_v2_run_can_publish_without_reacquisition(multiselect_case):
    config, snapshot = multiselect_case
    ready = SurveyProject(config, source=FixtureSource(snapshot)).refresh(dry_run=True)
    result = SurveyProject(config, source=MustNotRead(), publisher=FakeReportPublisher()).resume(
        ready.run_id
    )
    assert result.status == RunStatus.COMPLETED
    assert PublicationStore(config.project_dir).load(ready.run_id).content.layout_version == "2"


def test_publication_integrity_and_provenance(multiselect_case):
    config, snapshot = multiselect_case
    result = SurveyProject(
        config, source=FixtureSource(snapshot), publisher=FakeReportPublisher()
    ).refresh()
    store = PublicationStore(config.project_dir)
    saved = store.load(result.run_id)
    with pytest.raises(StorageError, match="does not match"):
        saved.verify_analysis(result.analysis.model_copy(update={"accepted_rows": 0}))
    with pytest.raises(StorageError):
        store.save(saved)
    path = config.project_dir / "publications" / f"{result.run_id}.json"
    envelope = json.loads(path.read_bytes())
    envelope["publication"]["content"]["title"] = "Tampered"
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(StorageError, match="integrity"):
        store.load(result.run_id)


def test_changed_configuration_is_rejected_on_resume(multiselect_case):
    config, snapshot = multiselect_case
    ready = SurveyProject(config, source=FixtureSource(snapshot)).refresh(dry_run=True)
    changed = config.model_copy(
        update={"report": config.report.model_copy(update={"title": "Changed"})}
    )
    with pytest.raises(ConfigurationError, match="effective configuration"):
        SurveyProject(changed, source=MustNotRead(), publisher=FakeReportPublisher()).resume(
            ready.run_id
        )
