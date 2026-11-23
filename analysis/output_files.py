"""Write the CSV files of the trajectory analysis, so that every script writes them with the same line ends."""

import csv
from collections.abc import Iterable, Sequence
from pathlib import Path


def write_csv(
    path: Path, columns: Sequence[str], rows: Iterable[Sequence[object]]
) -> None:
    """Write a CSV file of a header and rows, with `\\n` line ends."""
    with path.open("w", newline="") as csv_file:
        writer = csv.writer(csv_file, lineterminator="\n")
        writer.writerow(columns)
        writer.writerows(rows)
