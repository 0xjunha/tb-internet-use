"""Read the picked trials with the reports of their readers, for the scripts that count or show what the readers recorded."""

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class TrialReports:
    """One picked trial with the facts of its row of `picked_trials.csv` and the reports of its readers that exist."""

    trial_id: str
    task: str
    harness: str
    model: str
    # The reward as `picked_trials.csv` writes it, e.g. `1.0`.
    reward: str
    reading_group: str
    # The reports by 0-based reader index, in that order.
    reports: tuple[tuple[int, dict[str, Any]], ...]

    @property
    def pair(self) -> str:
        """Give the harness and model as one text, e.g. `codex gpt-6-astra`."""
        return f"{self.harness} {self.model or 'no model'}"


def read_trial_reports(out_dir: Path) -> list[TrialReports]:
    """Read every picked trial of `picked_trials.csv` that has a report, in file order, with its reports from `reports/<trial_id>_<reader_index>.json`."""
    readings = json.loads((out_dir / "readings.json").read_text())
    reader_indexes: dict[str, list[int]] = {}
    for reading in readings:
        reader_indexes.setdefault(reading["trial_id"], []).append(
            reading["reader_index"]
        )
    trials: list[TrialReports] = []
    with (out_dir / "picked_trials.csv").open(newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            reports = tuple(
                (reader_index, json.loads(path.read_text()))
                for reader_index in sorted(reader_indexes.get(row["trial_id"], []))
                if (
                    path := out_dir
                    / "reports"
                    / f"{row['trial_id']}_{reader_index}.json"
                ).is_file()
            )
            if reports:
                trials.append(
                    TrialReports(
                        trial_id=row["trial_id"],
                        task=row["task"],
                        harness=row["harness"],
                        model=row["model"],
                        reward=row["reward"],
                        reading_group=row["reading_group"],
                        reports=reports,
                    )
                )
    return trials
