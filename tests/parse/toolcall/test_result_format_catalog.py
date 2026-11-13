"""The committed result format catalog matches the formats the converters declare."""

import csv

from tb_internet_use.parse.toolcall.result_format_audit import (
    RESULT_FORMAT_CATALOG_CSV,
    catalog_rows,
)


def _without_hand_filled(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {k: v for k, v in row.items() if k not in ("reviewed", "note")} for row in rows
    ]


def test_committed_catalog_matches_the_declared_formats():
    with RESULT_FORMAT_CATALOG_CSV.open(newline="") as f:
        committed = list(csv.DictReader(f))
    assert _without_hand_filled(committed) == _without_hand_filled(catalog_rows()), (
        "rebuild it with scripts/build_harness_result_format_catalog.py"
    )
