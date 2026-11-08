"""The committed result format catalog matches the formats the converters declare."""

import csv
from pathlib import Path

from tb_internet_use.toolcall.result_format_audit import catalog_rows

CATALOG_CSV = (
    Path(__file__).parents[2]
    / "src/tb_internet_use/toolcall/catalogs/harness_result_format_catalog.csv"
)


def _without_reviewed(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [{k: v for k, v in row.items() if k != "reviewed"} for row in rows]


def test_committed_catalog_matches_the_declared_formats():
    with CATALOG_CSV.open(newline="") as f:
        committed = list(csv.DictReader(f))
    assert _without_reviewed(committed) == _without_reviewed(catalog_rows()), (
        "rebuild it with scripts/build_harness_result_format_catalog.py"
    )
