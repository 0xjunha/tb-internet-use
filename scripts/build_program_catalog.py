"""Count how often each program catalog row matches the commands of raw trials, and list the programs without a row.

It rewrites only the count columns of the committed catalog and never the hand-filled ones.
Every program and subcommand goes to `out/program_catalog_candidates.csv`, which `.gitignore` keeps out of the repo, since raw program names can hold hidden task content.

Usage: nice -n 10 uv run python -I scripts/build_program_catalog.py <raw_trials_dir> [candidates_csv]
"""

import argparse
import csv
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from tb_internet_use.callrun import expand_calls
from tb_internet_use.program.arguments import parse_arguments
from tb_internet_use.program.catalog_loader import PROGRAM_CATALOG_CSV
from tb_internet_use.program.catalog_rows import matched_catalog_rows
from tb_internet_use.shell.programs import program_words
from tb_internet_use.toolcall import convert_trial

DEFAULT_CANDIDATES_CSV = (
    Path(__file__).resolve().parents[1] / "out" / "program_catalog_candidates.csv"
)
CANDIDATE_COLUMNS = [
    "program",
    "subcommand",
    "command_count",
    "trial_count",
    "has_catalog_row",
]
# Data runs use at most 4 processes, to leave the machine usable.
_PROCESS_COUNT = 4

# (program, subcommand words joined by spaces)
type CatalogKey = tuple[str, str]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_trials_dir", type=Path)
    parser.add_argument(
        "candidates_csv", type=Path, nargs="?", default=DEFAULT_CANDIDATES_CSV
    )
    arguments = parser.parse_args()

    trial_dirs = sorted(p for p in arguments.raw_trials_dir.iterdir() if p.is_dir())
    command_count_of_row: Counter[CatalogKey] = Counter()
    trial_count_of_row: Counter[CatalogKey] = Counter()
    candidate_commands: Counter[tuple[CatalogKey, bool]] = Counter()
    candidate_trials: Counter[tuple[CatalogKey, bool]] = Counter()
    with ProcessPoolExecutor(_PROCESS_COUNT) as pool:
        for row_counts, candidates in pool.map(count_trial, trial_dirs, chunksize=20):
            command_count_of_row.update(row_counts)
            trial_count_of_row.update(row_counts.keys())
            candidate_commands.update(candidates)
            candidate_trials.update(candidates.keys())

    _rewrite_catalog_counts(command_count_of_row, trial_count_of_row)
    arguments.candidates_csv.parent.mkdir(parents=True, exist_ok=True)
    with arguments.candidates_csv.open("w", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(CANDIDATE_COLUMNS)
        for (key, has_row), count in candidate_commands.most_common():
            writer.writerow(
                [
                    *key,
                    count,
                    candidate_trials[key, has_row],
                    "yes" if has_row else "no",
                ]
            )


def count_trial(
    trial_dir: Path,
) -> tuple[Counter[CatalogKey], Counter[tuple[CatalogKey, bool]]]:
    """Count the commands of one trial per matching catalog row, and per program and first plain argument."""
    row_counts: Counter[CatalogKey] = Counter()
    candidates: Counter[tuple[CatalogKey, bool]] = Counter()
    for call_run in expand_calls(convert_trial(trial_dir)):
        for text in call_run.shell_texts:
            for ran_command in text.commands or ():
                words = program_words(ran_command.command)
                if not words:
                    continue
                matched_rows = matched_catalog_rows(words)
                for matched in matched_rows:
                    key = (matched.program_name, " ".join(matched.row.subcommand_words))
                    row_counts[key] += 1
                plain = parse_arguments(words[0], words[1:]).plain_arguments
                candidates[(words[0], ""), bool(matched_rows)] += 1
                if plain:
                    candidates[(words[0], plain[0]), bool(matched_rows)] += 1
    return row_counts, candidates


def _rewrite_catalog_counts(
    command_count_of_row: Counter[CatalogKey], trial_count_of_row: Counter[CatalogKey]
) -> None:
    """Write the new counts into the committed catalog, keeping every other column, and print the rows that match nothing."""
    with PROGRAM_CATALOG_CSV.open(newline="") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames
        csv_rows = list(reader)
    assert columns is not None
    for row in csv_rows:
        key = (row["program"], row["subcommand"])
        row["command_count"] = str(command_count_of_row[key])
        row["trial_count"] = str(trial_count_of_row[key])
        if not command_count_of_row[key]:
            print(f"no command matches row {key}")
    with PROGRAM_CATALOG_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(f, columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(csv_rows)


if __name__ == "__main__":
    main()
