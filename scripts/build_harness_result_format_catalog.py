"""Write the harness result format catalog from the formats the harnesses declare in `knowledge/`.

It reads no trajectory. Rows follow the order in which the formats are tried.
A hand-filled `reviewed` value is kept while its row's template and labels stay the same.
A hand-filled `note` is always kept.

Run it as `uv run python -I scripts/build_harness_result_format_catalog.py [output_csv]`.
"""

import argparse
import csv
from pathlib import Path

from tb_internet_use.knowledge.harness_result_format_audit import (
    CATALOG_COLUMNS,
    RESULT_FORMAT_CATALOG_CSV,
    catalog_rows_from_declarations,
    rows_with_kept_reviews_from,
)

DEFAULT_OUTPUT_CSV = RESULT_FORMAT_CATALOG_CSV


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_csv", type=Path, nargs="?", default=DEFAULT_OUTPUT_CSV)
    paths = parser.parse_args()

    previous: list[dict[str, str]] = []
    if paths.output_csv.exists():
        with paths.output_csv.open(newline="") as f:
            previous = list(csv.DictReader(f))
    rows = rows_with_kept_reviews_from(catalog_rows_from_declarations(), previous)

    with paths.output_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, CATALOG_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"catalog written: {paths.output_csv} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
