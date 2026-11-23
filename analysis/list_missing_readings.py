"""List the readings that have no report yet, so that a stopped run of the reading workflow can be resumed with their labels.

The labels go to standard output as one JSON list, e.g. for the `labels` argument of the workflow, and the count per task and reading group goes to standard error, so that the output stays valid JSON.

Run it as `uv run python -I analysis/list_missing_readings.py <out_dir> [--task <name>]`.
"""

import argparse
import csv
import json
import sys
from collections import Counter
from collections.abc import Collection, Sequence
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument(
        "out_dir",
        type=Path,
        help="the folder with picked_trials.csv, readings.json and reports/",
    )
    parser.add_argument("--task", help="only the readings of this task")
    arguments = parser.parse_args()

    readings = json.loads((arguments.out_dir / "readings.json").read_text())
    with (arguments.out_dir / "picked_trials.csv").open(newline="") as csv_file:
        task_by_trial = {
            row["trial_id"]: row["task"] for row in csv.DictReader(csv_file)
        }
    reports_dir = arguments.out_dir / "reports"
    report_names = (
        {path.name for path in reports_dir.iterdir()} if reports_dir.is_dir() else set()
    )
    missing = missing_readings_of(
        readings, report_names, task_by_trial, task=arguments.task
    )
    print(json.dumps([reading["label"] for reading in missing], indent=1))
    counts = Counter(
        (task_by_trial[reading["trial_id"]], reading["reading_group"])
        for reading in missing
    )
    for (task, reading_group), count in sorted(counts.items()):
        print(f"{task} {reading_group} {count}", file=sys.stderr)
    task_text = f" of task {arguments.task}" if arguments.task else ""
    print(
        f"{len(missing)} readings{task_text} have no report, of {len(readings)} readings in all",
        file=sys.stderr,
    )


def missing_readings_of(
    readings: Sequence[dict[str, Any]],
    report_names: Collection[str],
    task_by_trial: dict[str, str],
    *,
    task: str | None = None,
) -> list[dict[str, Any]]:
    """Give the readings, in their order, without a report file `<trial_id>_<reader_index>.json`, only those of `task` when it is given."""
    return [
        reading
        for reading in readings
        if f"{reading['trial_id']}_{reading['reader_index']}.json" not in report_names
        and (task is None or task_by_trial[reading["trial_id"]] == task)
    ]


if __name__ == "__main__":
    main()
