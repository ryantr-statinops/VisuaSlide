import pytest
from pydantic import ValidationError

from visuaslide.config import SurveySchema, VariableKind, VariableSchema


def test_categorical_schema_keeps_declared_order() -> None:
    schema = VariableSchema(
        name="study_year",
        source_header="Study year",
        kind=VariableKind.CATEGORICAL,
        categories=("Year 1", "Year 2"),
    )

    assert schema.categories == ("Year 1", "Year 2")
    assert schema.missing_values == ("",)


@pytest.mark.parametrize(
    "values",
    [
        {"name": "choice", "source_header": "Choice", "kind": "categorical"},
        {
            "name": "score",
            "source_header": "Score",
            "kind": "numeric",
            "categories": ("low", "high"),
        },
        {"name": "date", "source_header": "Date", "kind": "datetime"},
        {
            "name": "choice",
            "source_header": "Choice",
            "kind": "categorical",
            "categories": ("yes", "yes"),
        },
        {"name": "Invalid name", "source_header": "Choice", "kind": "text"},
    ],
)
def test_variable_schema_rejects_incomplete_or_ambiguous_definitions(
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        VariableSchema.model_validate(values)


def test_datetime_schema_requires_explicit_format_and_accepts_timezone() -> None:
    schema = VariableSchema(
        name="submitted_at",
        source_header="Submitted at",
        kind="datetime",
        datetime_format="%Y-%m-%d %H:%M",
        timezone="Asia/Ho_Chi_Minh",
    )

    assert schema.timezone == "Asia/Ho_Chi_Minh"


def test_schema_rejects_duplicate_internal_names_and_headers() -> None:
    first = VariableSchema(name="first", source_header="Shared", kind="text")
    second = VariableSchema(name="second", source_header="Shared", kind="text")

    with pytest.raises(ValidationError, match="source headers must be unique"):
        SurveySchema(variables=(first, second))
