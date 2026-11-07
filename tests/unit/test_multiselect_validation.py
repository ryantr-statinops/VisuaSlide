from datetime import UTC, datetime

import pytest

from visuaslide.config import SourceConfig, VariableSchema
from visuaslide.preparation import (
    parse_multiselect,
    prepare_multiselect_column,
    prepare_numeric_column,
)
from visuaslide.snapshots import SourceSnapshot


def _variable(**updates):
    return VariableSchema(
        name="choices",
        source_header="Choices",
        kind="multi_select",
        categories=("IELTS", "PET (Cambridge)", "So sánh IELTS, TOEIC và APTIS"),
        aliases={"Pet": "PET (Cambridge)", "PET Cambridge": "PET (Cambridge)"},
        trim_whitespace=True,
        **updates,
    )


def _snapshot(value):
    return SourceSnapshot.capture(
        SourceConfig(spreadsheet_id="synthetic", sheet_id=0, column_range="A:B"),
        headers=("ID", "Choices"),
        rows=(("synthetic-001", value),),
        acquired_at=datetime(2026, 11, 7, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("IELTS, IELTS, Pet, ", ("IELTS", "PET (Cambridge)")),
        ("PET Cambridge", ("PET (Cambridge)",)),
        ("So sánh IELTS, TOEIC và APTIS, IELTS", ("IELTS", "So sánh IELTS, TOEIC và APTIS")),
        ("  Pet , IELTS  ", ("IELTS", "PET (Cambridge)")),
    ],
)
def test_whole_choices_aliases_and_configured_order(text, expected):
    assert parse_multiselect(text, _variable()) == expected


@pytest.mark.parametrize(
    "text", ["IELTS-extra", "ielts", "Unknown", "IELTS, Unknown", "IELTS,,Pet", ","]
)
def test_unknown_or_partial_choices_are_safe_validation_errors(text):
    result = prepare_multiselect_column(_snapshot(text), _variable())
    assert result.values == (None,)
    assert [(issue.code, issue.source_row) for issue in result.issues] == [
        ("invalid_multiselect", 2)
    ]
    assert all(text not in issue.message for issue in result.issues)


def test_custom_separator_and_longest_complete_choice():
    variable = VariableSchema(
        name="choices",
        source_header="Choices",
        kind="multi_select",
        categories=("A", "A|B", "B"),
        separator="|",
    )
    assert parse_multiselect("A|B|A|", variable) == ("A", "A|B")


@pytest.mark.parametrize("value", [None, "", "  "])
def test_missing_answers_and_required_policy(value):
    assert prepare_multiselect_column(_snapshot(value), _variable()).values == (None,)
    required = prepare_multiselect_column(_snapshot(value), _variable(required=True))
    assert [issue.code for issue in required.issues] == ["required_value_missing"]


def test_multiselect_type_and_header_errors():
    assert (
        prepare_multiselect_column(_snapshot(12), _variable()).issues[0].code
        == "invalid_multiselect"
    )
    snapshot = _snapshot("IELTS").model_copy(update={"headers": ("ID", "Other")})
    assert (
        prepare_multiselect_column(snapshot, _variable()).issues[0].code
        == "missing_configured_header"
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"categories": ()},
        {"categories": ("",)},
        {"categories": (" A ",)},
        {"aliases": {"": "IELTS"}},
        {"aliases": {"Other": "Unconfigured"}},
        {"aliases": {"IELTS": "PET (Cambridge)"}},
        {"missing_values": ("IELTS",)},
        {"separator": ""},
        {"separator": " "},
    ],
)
def test_invalid_multiselect_configuration(updates):
    values = _variable().model_dump()
    values.update(updates)
    with pytest.raises(ValueError):
        VariableSchema.model_validate(values)


@pytest.mark.parametrize("allowed", [[], [True], [1, 1.0], [float("inf")], [float("nan")]])
def test_numeric_allowed_values_must_be_finite_unique_numbers(allowed):
    with pytest.raises(ValueError):
        VariableSchema(
            name="score", source_header="Choices", kind="numeric", allowed_values=allowed
        )


@pytest.mark.parametrize("value", [0, 6, 2.5])
def test_numeric_values_outside_declared_scale_fail(value):
    variable = VariableSchema(
        name="score", source_header="Choices", kind="numeric", allowed_values=(1, 2, 3, 4, 5)
    )
    result = prepare_numeric_column(_snapshot(value), variable)
    assert result.issues[0].code == "numeric_value_not_allowed"
    assert prepare_numeric_column(_snapshot(3), variable).values == (3,)
    unbounded = variable.model_copy(update={"allowed_values": None})
    assert prepare_numeric_column(_snapshot(value), unbounded).values == (value,)
