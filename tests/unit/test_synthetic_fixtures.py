import json
import statistics
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_synthetic_survey_fixture_matches_independently_computed_reference() -> None:
    fixture = json.loads((ROOT / "tests/fixtures/synthetic_responses.json").read_text("utf-8"))
    expected = json.loads((ROOT / "tests/fixtures/expected_summary.json").read_text("utf-8"))
    rows = fixture["rows"]

    assert len(rows) == expected["input_rows"] == 5
    assert sum(not any(value != "" for value in row) for row in rows) == expected["blank_rows"]
    assert len({row[0] for row in rows}) == 5
    assert [row[1] for row in rows].count("Year 1") == expected["study_year_counts"]["Year 1"]
    assert [row[1] for row in rows].count("Year 2") == expected["study_year_counts"]["Year 2"]
    assert [row[1] for row in rows].count("Year 3") == expected["study_year_counts"]["Year 3"]
    assert [row[1] for row in rows].count("Year 4") == expected["study_year_counts"]["Year 4"]

    scores = [float(row[3]) for row in rows if row[3] != ""]
    assert len(scores) == expected["score_count"]
    assert sum(scores) / len(scores) == expected["score_mean"]
    assert sorted(scores)[1:3] == [expected["score_median"], expected["score_median"]]
    assert min(scores) == expected["score_min"]
    assert max(scores) == expected["score_max"]
    assert statistics.stdev(scores) == expected["score_sample_standard_deviation"]

    tool_answers = [row[2] for row in rows if row[2] != ""]
    assert tool_answers.count("Yes") == expected["tool_use_counts"]["Yes"]
    assert tool_answers.count("No") == expected["tool_use_counts"]["No"]
    assert len(rows) - len(tool_answers) == expected["tool_use_missing"]
    assert (
        tool_answers.count("Yes") / len(tool_answers) == expected["tool_use_yes_non_missing_rate"]
    )
    assert tool_answers.count("No") / len(tool_answers) == expected["tool_use_no_non_missing_rate"]

    complete_pairs = [row for row in rows if row[1] != "" and row[2] != ""]
    actual_pair_counts = {
        f"{year}|{answer}": sum(row[1] == year and row[2] == answer for row in complete_pairs)
        for year in ("Year 1", "Year 2", "Year 3")
        for answer in ("Yes", "No")
    }
    assert actual_pair_counts == expected["year_by_tool_pairwise_complete_counts"]


def test_example_config_parses_and_only_names_synthetic_variables() -> None:
    with (ROOT / "examples/survey.example.toml").open("rb") as file:
        config = tomllib.load(file)

    assert config["source"]["spreadsheet_id"] == "REPLACE_WITH_YOUR_GOOGLE_SHEETS_ID"
    assert [variable["name"] for variable in config["schema"]["variables"]] == [
        "response_id",
        "study_year",
        "uses_tool",
        "score",
        "submitted_at",
        "comment",
    ]
