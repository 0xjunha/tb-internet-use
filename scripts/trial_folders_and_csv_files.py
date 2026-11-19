"""Choose the trial folders that an audit script reads, bound the processes that read them and write the CSV files of its results.

`run_pipeline.py` and the audit scripts that read raw trial folders in worker processes share the choice of folders, e.g. `--limit 100` or `--trial-ids sample-trials.txt`, and write CSVs under `out/`. `audit_results.py` is the exception, with its own `--limit` and no `--trial-ids`. `audit_export_knowledge.py` reads the saved results of a run and takes only `PROCESS_COUNT` and `write_csv` from here.
A script imports this module after it puts its own folder on `sys.path`, since `python -I` leaves that folder off.
"""

import argparse
import csv
from collections.abc import Iterable, Sequence
from pathlib import Path

# Data runs use at most 4 processes, to leave the machine usable.
PROCESS_COUNT = 4


def add_trial_choice_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the argument `raw_trials_dir` and the exclusive options `--limit` and `--trial-ids` that `chosen_trial_dirs_from` reads."""
    parser.add_argument("raw_trials_dir", type=Path)
    trial_choice = parser.add_mutually_exclusive_group()
    trial_choice.add_argument(
        "--limit", type=int, help="only the first N trial folders by name"
    )
    trial_choice.add_argument(
        "--trial-ids",
        type=Path,
        help="only the trials a file lists, one id per line in its first tab-separated column, skipping lines that start with #",
    )


def chosen_trial_dirs_from(arguments: argparse.Namespace) -> list[Path]:
    """Give the trial folders that the arguments of `add_trial_choice_arguments` choose, i.e. all by name, the first `--limit` by name or those that `--trial-ids` lists in its order."""
    if arguments.trial_ids is not None:
        return [
            arguments.raw_trials_dir / trial_id
            for trial_id in trial_ids_from_file_text(arguments.trial_ids.read_text())
        ]
    trial_dirs = trial_dirs_of(arguments.raw_trials_dir)
    if arguments.limit is not None:
        return trial_dirs[: arguments.limit]
    return trial_dirs


def trial_dirs_of(raw_trials_dir: Path) -> list[Path]:
    """Give every folder directly under the raw trials folder, sorted by name."""
    return sorted(path for path in raw_trials_dir.iterdir() if path.is_dir())


def trial_ids_from_file_text(file_text: str) -> list[str]:
    """List the trial ids of a file, i.e. the first tab-separated column of each line that is neither empty nor starts with `#`."""
    return [
        line.split("\t")[0]
        for line in file_text.splitlines()
        if line.strip() and not line.startswith("#")
    ]


def write_csv(path: Path, columns: Sequence[str], rows: Iterable[Sequence]) -> None:
    """Write a CSV file of a header and rows, with `\\n` line ends."""
    with path.open("w", newline="") as csv_file:
        writer = csv.writer(csv_file, lineterminator="\n")
        writer.writerow(columns)
        writer.writerows(rows)
