"""Write the harness result format catalog from the formats the converters declare.

It reads no trajectory. Rows follow the order in which the formats are tried.
A hand-filled `reviewed` value is kept while its row's template and labels stay the same.

Usage: uv run python -I scripts/build_harness_result_format_catalog.py [output_csv]
"""

import argparse
import csv
from pathlib import Path

from tb_internet_use.toolcall.result_format_audit import (
    CATALOG_COLUMNS,
    REVIEWED_LABELS,
    catalog_rows,
)

PACKAGE_DIR = Path(__file__).parents[1] / "src/tb_internet_use"
DEFAULT_OUTPUT_CSV = PACKAGE_DIR / "toolcall/catalogs/harness_result_format_catalog.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_csv", type=Path, nargs="?", default=DEFAULT_OUTPUT_CSV)
    paths = parser.parse_args()

    rows = catalog_rows()
    previous: dict[tuple[str, str, str], dict[str, str]] = {}
    if paths.output_csv.exists():
        with paths.output_csv.open(newline="") as f:
            previous = {
                (r["harness"], r["tool"], r["format"]): r for r in csv.DictReader(f)
            }
    for row in rows:
        old = previous.get((row["harness"], row["tool"], row["format"]))
        # A review covers the declaration it saw, so a changed declaration drops it
        if old and all(
            old.get(column, "") == row[column] for column in REVIEWED_LABELS
        ):
            row["reviewed"] = old.get("reviewed", "")

    with paths.output_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, CATALOG_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"catalog written: {paths.output_csv} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
