"""The declared output line patterns agree with their review record, one hand-filled row per pattern in the order of the tables."""

import csv
from pathlib import Path

from tb_internet_use.knowledge.declarations.network_request_result import (
    output_line_patterns,
)
from tb_internet_use.knowledge.declarations.network_request_result.output_line_patterns import (
    OUTPUT_LINE_PATTERN_TABLES,
)

_REVIEWS_CSV = (
    Path(output_line_patterns.__file__).parent / "output_line_pattern_reviews.csv"
)
_REVIEWS_COLUMNS = ["table", "pattern", "checked_against", "reviewed", "note"]


def _review_rows() -> list[dict[str, str]]:
    with _REVIEWS_CSV.open(newline="", encoding="utf-8") as reviews_file:
        reader = csv.DictReader(reviews_file)
        assert reader.fieldnames == _REVIEWS_COLUMNS
        return list(reader)


def test_review_record_has_one_row_per_declared_pattern_in_table_order():
    declared = [
        (table.name, pattern.name)
        for table in OUTPUT_LINE_PATTERN_TABLES
        for pattern in table.patterns
    ]

    assert [(row["table"], row["pattern"]) for row in _review_rows()] == declared


def test_every_review_row_says_what_it_was_checked_against_and_marks_review_by_yes():
    rows = _review_rows()

    assert [row["pattern"] for row in rows if not row["checked_against"]] == []
    assert {row["reviewed"] for row in rows} <= {"", "yes"}
