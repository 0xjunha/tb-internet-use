"""Write the table of the result formats that the harnesses declare in `knowledge/`, one row per format, for a person to read.

It reads no trajectory. Within one format list the rows follow the order in which the formats are tried, and per harness the lists for results marked as errors come first, then the text lists, then the JSON lists.
The table goes to `out/tool_call_knowledge/` by default, which `.gitignore` keeps out of the repo, since the Python declarations are the source and the table only shows them.

Run it as `uv run python -I scripts/build_harness_result_format_table.py [output_csv]`.
"""

import argparse
import csv
from pathlib import Path

from tb_internet_use.knowledge.harness_result_format_audit import (
    DECLARED_RESULT_FORMAT_TABLE_COLUMNS,
    table_rows_from_declarations,
)

DEFAULT_OUTPUT_CSV = (
    Path(__file__).resolve().parents[1]
    / "out"
    / "tool_call_knowledge"
    / "harness_result_formats.csv"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_csv", type=Path, nargs="?", default=DEFAULT_OUTPUT_CSV)
    paths = parser.parse_args()

    rows = table_rows_from_declarations()
    paths.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with paths.output_csv.open("w", newline="") as f:
        writer = csv.DictWriter(
            f, DECLARED_RESULT_FORMAT_TABLE_COLUMNS, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"table written: {paths.output_csv} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
