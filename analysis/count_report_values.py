"""Count the values that readers recorded and the labels derived from them over all reports, per reading group, task, harness and pair, into CSV files of the out dir.

A trial read twice can count for one reader and not the other, so a count of trials gives three numbers, by reader 0, by both readers and by either reader, from which a range can be reported. A trial read once gives the same number in all three. A count of items, e.g. failed requests, gives the items of reader 0 and those of all readings.

Run it after `check_reports.py` as `uv run python -I analysis/count_report_values.py <out_dir>`.
"""

import argparse
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

# `python -I` leaves the folder of this script off `sys.path`.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from output_files import write_csv
from report_files import TrialReports, read_trial_reports
from report_labels import (
    content_kinds_reaching_graded_answer_of,
    effects_on_answer_of,
    first_request_start_of,
    has_received_step,
    trial_use_summary_of,
)

COUNT_COLUMNS = (
    "measure",
    "unit",
    "breakdown",
    "breakdown_value",
    "value",
    "reader_0",
    "both_readers",
    "either_reader",
    "all_readings",
)
# The ways a count is broken down, each by the text it gives a trial.
BREAKDOWNS: dict[str, Callable[[TrialReports], str]] = {
    "all": lambda trial: "all",
    "reading_group": lambda trial: trial.reading_group,
    "task": lambda trial: trial.task,
    "harness": lambda trial: trial.harness,
    "pair": lambda trial: trial.pair,
}
TRIAL_UNIT = "trial"

# A function that gives the values a report has, or None when the report has no part they come from.
type ValuesOf = Callable[[dict[str, Any]], Iterable[str] | None]


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument(
        "out_dir",
        type=Path,
        help="the folder with picked_trials.csv, readings.json and reports/",
    )
    arguments = parser.parse_args()

    trials = read_trial_reports(arguments.out_dir)
    for file_name, rows in count_tables_of(trials).items():
        write_csv(arguments.out_dir / file_name, COUNT_COLUMNS, rows)
        print(f"== {file_name}")
        for row in rows:
            if row[2] == "all":
                print("  " + " ".join(str(cell) for cell in (row[0], row[1], *row[4:])))
    unconfirmed_rows = unconfirmed_command_entries_of(trials)
    write_csv(
        arguments.out_dir / "unconfirmed_command_entries.csv",
        UNCONFIRMED_COMMAND_ENTRY_COLUMNS,
        unconfirmed_rows,
    )
    print(f"== unconfirmed_command_entries.csv, {len(unconfirmed_rows)} entries")
    for row in unconfirmed_rows:
        print("  " + " ".join(str(cell) for cell in row))


def count_tables_of(trials: Sequence[TrialReports]) -> dict[str, list[tuple[Any, ...]]]:
    """Give the rows of each count file, by its file name."""
    return {
        "trial_use_summary_counts.csv": trial_counts_of(
            trials,
            "trial_use_summary",
            _groups_part(lambda groups: [trial_use_summary_of(groups)]),
        ),
        "first_request_start_counts.csv": trial_counts_of(
            trials,
            "first_request_start",
            _groups_part(lambda groups: [first_request_start_of(groups)]),
        ),
        "effect_counts.csv": trial_counts_of(
            trials,
            "effect tests_grade_part",
            _groups_part(
                lambda groups: {
                    f"{effect['effect']} {effect['tests_grade_part']}"
                    for effect in effects_on_answer_of(groups)
                }
            ),
        ),
        "failed_request_counts.csv": [
            row
            for key, value_of in FAILED_REQUEST_MEASURES.items()
            for row in [
                *item_counts_of(
                    trials,
                    key,
                    "failed request",
                    _items_of("failed_requests", value_of),
                ),
                *trial_counts_of(trials, key, _items_of("failed_requests", value_of)),
            ]
        ],
        "without_entry_counts.csv": [
            *item_counts_of(
                trials,
                "trial_without_requests.entries.content_origin",
                "host entry",
                _without_entry_values,
            ),
            *trial_counts_of(
                trials,
                "trial_without_requests.entries.content_origin",
                _without_entry_values,
            ),
            *trial_counts_of(
                trials,
                "trial_without_requests.considered_internet",
                lambda report: (
                    [report["trial_without_requests"]["considered_internet"]]
                    if "trial_without_requests" in report
                    else None
                ),
            ),
        ],
        "online_rule_counts.csv": [
            *trial_counts_of(
                trials,
                "online_rule.treatment",
                lambda report: (
                    [report["online_rule"]["treatment"]]
                    if "online_rule" in report
                    else None
                ),
            ),
            *trial_counts_of(
                trials,
                "online_rule.reason_given",
                lambda report: (
                    [
                        "given"
                        if report["online_rule"]["reason_given"].strip()
                        else "empty"
                    ]
                    if "online_rule" in report
                    else None
                ),
            ),
        ],
        "disputed_row_counts.csv": [
            *item_counts_of(
                trials,
                "request_rows_disputed.dispute",
                "disputed row",
                lambda report: [
                    row["dispute"] for row in report["request_rows_disputed"]
                ],
            ),
            *trial_counts_of(
                trials,
                "request_rows_disputed.dispute",
                lambda report: [
                    row["dispute"] for row in report["request_rows_disputed"]
                ],
            ),
            *disputed_row_agreement_counts_of(trials),
        ],
        "content_kind_counts.csv": [
            *trial_counts_of(
                trials,
                "content_kinds of groups with a received step",
                _groups_part(
                    lambda groups: {
                        kind
                        for group in groups
                        if has_received_step(group)
                        for kind in group["content_kinds"]
                    }
                ),
            ),
            *trial_counts_of(
                trials,
                "content_kinds_reaching_graded_answer",
                _groups_part(
                    lambda groups: content_kinds_reaching_graded_answer_of(
                        groups
                    ).split()
                ),
            ),
        ],
    }


# The keys of a failed request that are counted, each by the value it gives an entry.
FAILED_REQUEST_MEASURES: dict[str, Callable[[dict[str, Any]], str]] = {
    "failure_shown": lambda entry: entry["failure_shown"],
    "next_action": lambda entry: entry["next_action"],
    "content_obtained_later": lambda entry: entry["content_obtained_later"],
    "next_action content_obtained_later": lambda entry: (
        f"{entry['next_action']} {entry['content_obtained_later']}"
    ),
}
UNCONFIRMED_COMMAND_ENTRY_COLUMNS = (
    "task",
    "trial_id",
    "harness",
    "model",
    "reader_index",
    "command",
    "download_evidence",
    "image_fetches_dependencies",
    "first_run_step_id",
    "what_was_downloaded",
)


def trial_counts_of(
    trials: Sequence[TrialReports], measure: str, values_of: ValuesOf
) -> list[tuple[Any, ...]]:
    """Count per breakdown the trials whose report has each value, by reader 0, by both readers and by either reader, over the trials whose reports have the part the values come from."""
    rows: list[tuple[Any, ...]] = []
    for breakdown, breakdown_value_of in BREAKDOWNS.items():
        counts: dict[tuple[str, str], list[int]] = {}
        for trial in trials:
            value_sets = [values_of(report) for _, report in trial.reports]
            if any(values is None for values in value_sets):
                continue
            sets = [set(values or ()) for values in value_sets]
            for value in set().union(*sets):
                count = counts.setdefault((breakdown_value_of(trial), value), [0, 0, 0])
                count[0] += value in sets[0]
                count[1] += all(value in values for values in sets)
                count[2] += 1
        rows += [
            (measure, TRIAL_UNIT, breakdown, breakdown_value, value, *count, "")
            for (breakdown_value, value), count in sorted(counts.items())
        ]
    return rows


def item_counts_of(
    trials: Sequence[TrialReports],
    measure: str,
    unit: str,
    values_of: ValuesOf,
) -> list[tuple[Any, ...]]:
    """Count per breakdown the items of each value, e.g. failed requests, in the reports of reader 0 and in all readings."""
    rows: list[tuple[Any, ...]] = []
    for breakdown, breakdown_value_of in BREAKDOWNS.items():
        reader_0_counts: Counter[tuple[str, str]] = Counter()
        all_counts: Counter[tuple[str, str]] = Counter()
        for trial in trials:
            for position, (_, report) in enumerate(trial.reports):
                for value in values_of(report) or ():
                    key = (breakdown_value_of(trial), value)
                    all_counts[key] += 1
                    reader_0_counts[key] += position == 0
        rows += [
            (
                measure,
                unit,
                breakdown,
                breakdown_value,
                value,
                reader_0_counts[key],
                "",
                "",
                count,
            )
            for key, count in sorted(all_counts.items())
            for breakdown_value, value in [key]
        ]
    return rows


def disputed_row_agreement_counts_of(
    trials: Sequence[TrialReports],
) -> list[tuple[Any, ...]]:
    """Count per breakdown the disputed rows of trials read twice, as their step id, target and dispute, by whether both readers or only one disputed them."""

    def value_of(trial: TrialReports, disputed: tuple[Any, ...]) -> str:
        holders = [disputed in _disputed_rows_of(report) for _, report in trial.reports]
        if all(holders):
            return "both_readers"
        return f"reader_{holders.index(True)}_only"

    rows: list[tuple[Any, ...]] = []
    for breakdown, breakdown_value_of in BREAKDOWNS.items():
        counts: Counter[tuple[str, str]] = Counter()
        for trial in trials:
            if len(trial.reports) != 2:
                continue
            disputed_rows = set().union(
                *(_disputed_rows_of(report) for _, report in trial.reports)
            )
            for disputed in disputed_rows:
                counts[(breakdown_value_of(trial), value_of(trial, disputed))] += 1
        rows += [
            (
                "request_rows_disputed in trials read twice",
                "disputed row",
                breakdown,
                breakdown_value,
                value,
                "",
                "",
                "",
                count,
            )
            for (breakdown_value, value), count in sorted(counts.items())
        ]
    return rows


def unconfirmed_command_entries_of(
    trials: Sequence[TrialReports],
) -> list[tuple[Any, ...]]:
    """Give one row per entry of `unconfirmed_commands`, by task and trial."""
    return [
        (
            trial.task,
            trial.trial_id,
            trial.harness,
            trial.model,
            reader_index,
            entry["command"],
            entry["download_evidence"],
            entry["image_fetches_dependencies"],
            entry["first_run_step_id"],
            entry["what_was_downloaded"],
        )
        for trial in sorted(trials, key=lambda trial: trial.task)
        for reader_index, report in trial.reports
        for entry in report.get("unconfirmed_commands", [])
    ]


def _groups_part(
    values_of_groups: Callable[[list[dict[str, Any]]], Iterable[str]],
) -> ValuesOf:
    """Give a function that applies `values_of_groups` to the request groups of a report that has the part, and gives None for one without."""

    def values_of(report: dict[str, Any]) -> Iterable[str] | None:
        if "request_groups" not in report:
            return None
        return values_of_groups(report["request_groups"])

    return values_of


def _items_of(part: str, value_of: Callable[[dict[str, Any]], str]) -> ValuesOf:
    """Give a function that lists the value of each entry of one list of a report, None for a report without the list."""

    def values_of(report: dict[str, Any]) -> list[str] | None:
        if part not in report:
            return None
        return [value_of(entry) for entry in report[part]]

    return values_of


def _without_entry_values(report: dict[str, Any]) -> list[str] | None:
    if "trial_without_requests" not in report:
        return None
    return [
        entry["content_origin"] for entry in report["trial_without_requests"]["entries"]
    ]


def _disputed_rows_of(report: dict[str, Any]) -> set[tuple[Any, ...]]:
    return {
        (row["step_id"], row["target"], row["dispute"])
        for row in report.get("request_rows_disputed", [])
    }


if __name__ == "__main__":
    main()
