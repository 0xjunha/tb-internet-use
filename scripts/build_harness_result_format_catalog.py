"""Write the harness result format catalog from the formats the converters declare.

It reads no trajectory. Rows follow the order in which the formats are tried.
A hand-filled `reviewed` value is kept while its row's template and labels stay the same.
A hand-filled `note` is always kept.

Usage: uv run python -I scripts/build_harness_result_format_catalog.py [output_csv]
"""

import argparse
import csv
from pathlib import Path

from tb_internet_use.parse.toolcall.result_format_audit import (
    CATALOG_COLUMNS,
    RESULT_FORMAT_CATALOG_CSV,
    catalog_rows,
    with_kept_reviews,
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
    rows = with_kept_reviews(catalog_rows(), previous)

    with paths.output_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, CATALOG_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"catalog written: {paths.output_csv} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
