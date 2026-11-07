from visuaslide import SurveyProject
from visuaslide.models import RunStatus
from visuaslide.publisher import FakeReportPublisher
from visuaslide.testing import FixtureSource


def test_source_edits_and_deletions_keep_page_ids_and_update_all_outputs(multiselect_case):
    config, original = multiselect_case
    publisher = FakeReportPublisher()
    snapshots = [
        original,
        original.model_copy(
            update={"rows": (*original.rows, ("synthetic-004", "Khoa Luật", "TOEIC", "", 4))}
        ),
        original.model_copy(
            update={
                "rows": (original.rows[0], (*original.rows[1][:2], "TOEIC", *original.rows[1][3:]))
            }
        ),
    ]
    identities = None
    for snapshot in snapshots:
        result = SurveyProject(
            config, source=FixtureSource(snapshot), publisher=publisher
        ).refresh()
        assert result.status == RunStatus.COMPLETED
        current_ids = set(publisher.objects)
        assert identities is None or current_ids == identities
        identities = current_ids
        assert (
            len(
                next(
                    table
                    for table in result.analysis.tables
                    if table.analysis_id == "faculty_counts"
                ).rows
            )
            == 13
        )
    certificate_table = next(
        table for table in result.analysis.tables if table.analysis_id == "certificate_counts"
    )
    assert certificate_table.rows[0][1] == 1
    assert certificate_table.rows[1][1] == 1
