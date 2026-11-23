"""Count how often the two readers of a trial agree, request step by request step, and on their failed requests matched by the steps they share.

Trials of `requested_and_solved` are read twice by readers that do not see each other, so where they disagree a person reads the trial beside the raw trajectory. Two readers can form groups differently from the same facts, so the facts of a group are compared on each of its request steps, e.g. the `prior_candidate` of a group of steps 4 and 5 is compared at step 4 and at step 5. A `cannot_tell` counts as a value of its own, so two readers agree on it only when both give it.

Run it after `check_reports.py` as `uv run python -I analysis/reader_agreement.py <out_dir>`.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# `python -I` leaves the folder of this script off `sys.path`.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from output_files import write_csv
from report_labels import (
    content_kinds_reaching_graded_answer_of,
    first_request_start_of,
    merged_step_label_sets_of,
    step_label_sets_of,
    trial_use_summary_of,
)

CANNOT_TELL = "cannot_tell"
AGREEMENT_COLUMNS = (
    "key",
    "counted_over",
    "agree",
    "disagree",
    "agree_on_cannot_tell",
    "disagree_with_one_cannot_tell",
    "listed_by_one_reader_only",
)
ONLINE_RULE_KEY = "online_rule.treatment"
TRIAL_USE_SUMMARY_KEY = "trial_use_summary"
FIRST_REQUEST_START_KEY = "first_request_start"
CONTENT_KINDS_KEY = "content_kinds_reaching_graded_answer"
GRADED_ANSWER_REACH_KEY = "graded_answer_reach"
# The set of effects, each with whether the tests grade its part, and the set of disputed rows of a trial.
EFFECTS_KEY = "effects"
DISPUTED_ROWS_KEY = "request_rows_disputed"
# The keys of a trial that two readers are compared on, in the order of `trial_comparisons.csv`.
TRIAL_KEYS = (
    TRIAL_USE_SUMMARY_KEY,
    FIRST_REQUEST_START_KEY,
    CONTENT_KINDS_KEY,
    GRADED_ANSWER_REACH_KEY,
    EFFECTS_KEY,
    DISPUTED_ROWS_KEY,
)
# The facts of a request step that two readers are compared on, the last two projected from its group.
STEP_KEYS = (
    "response",
    "step_label",
    "merged_step_label",
    "prior_candidate",
    "shown_before_request",
)
# The step label of a step that only the other reader lists, in the confusion table.
NOT_LISTED = "not_listed"


@dataclass(frozen=True, slots=True)
class ComparedReportPart:
    """List of a report whose entries two readers are matched and compared on, e.g. `request_groups`."""

    # The key of the list in the report.
    name: str
    # The key of the step ids by which entries are matched.
    step_ids_key: str
    # The keys whose values two readers are compared on.
    compared_keys: tuple[str, ...]
    # The key that names an entry in the list of unmatched entries.
    description_key: str


COMPARED_REPORT_PARTS = (
    ComparedReportPart(
        "failed_requests",
        "step_ids",
        ("failure_shown", "next_action", "content_obtained_later"),
        "hosts",
    ),
)


@dataclass(frozen=True, slots=True)
class EntryMatch:
    """Pair of entries of one list of the two readers of a trial that share the most steps, by their 0-based index in each report."""

    first_entry_index: int
    second_entry_index: int
    shared_step_count: int


@dataclass(slots=True)
class KeyAgreement:
    """Counts of one key over the matched entries or the trials, written as one row of `reader_agreement.csv`."""

    agree: int = 0
    disagree: int = 0
    agree_on_cannot_tell: int = 0
    disagree_with_one_cannot_tell: int = 0
    listed_by_one_reader_only: int = 0

    def add(self, first_value: object, second_value: object) -> None:
        """Count one comparison of the values of the two readers."""
        if first_value == second_value:
            self.agree += 1
            self.agree_on_cannot_tell += first_value == CANNOT_TELL
        else:
            self.disagree += 1
            self.disagree_with_one_cannot_tell += CANNOT_TELL in (
                first_value,
                second_value,
            )


@dataclass(slots=True)
class _AgreementRows:
    """Counts and rows that `main` gathers over the trials read twice."""

    agreements: dict[str, KeyAgreement] = field(
        default_factory=lambda: defaultdict(KeyAgreement)
    )
    match_rows: list[tuple[Any, ...]] = field(default_factory=list)
    unmatched_rows: list[tuple[Any, ...]] = field(default_factory=list)
    step_rows: list[tuple[Any, ...]] = field(default_factory=list)
    trial_rows: list[tuple[Any, ...]] = field(default_factory=list)
    step_label_pairs: Counter[tuple[str, str]] = field(default_factory=Counter)


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument(
        "out_dir", type=Path, help="the folder with readings.json and reports/"
    )
    arguments = parser.parse_args()

    readings = json.loads((arguments.out_dir / "readings.json").read_text())
    reader_indexes_by_trial: dict[str, list[int]] = defaultdict(list)
    for reading in readings:
        reader_indexes_by_trial[reading["trial_id"]].append(reading["reader_index"])
    rows = _AgreementRows()
    compared_trials = 0
    for trial_id, reader_indexes in reader_indexes_by_trial.items():
        report_paths = [
            arguments.out_dir / "reports" / f"{trial_id}_{reader_index}.json"
            for reader_index in sorted(reader_indexes)
        ]
        if len(report_paths) != 2 or not all(path.is_file() for path in report_paths):
            continue
        compared_trials += 1
        first_report, second_report = (
            json.loads(path.read_text()) for path in report_paths
        )
        for part in COMPARED_REPORT_PARTS:
            _compare_part(trial_id, part, first_report, second_report, rows)
        if "online_rule" in first_report and "online_rule" in second_report:
            rows.agreements[ONLINE_RULE_KEY].add(
                first_report["online_rule"]["treatment"],
                second_report["online_rule"]["treatment"],
            )
        if "request_groups" in first_report and "request_groups" in second_report:
            _compare_steps(trial_id, first_report, second_report, rows)
            _compare_trial(trial_id, first_report, second_report, rows)
    write_csv(
        arguments.out_dir / "reader_agreement.csv",
        AGREEMENT_COLUMNS,
        [
            (
                key,
                _counted_over_of(key),
                agreement.agree,
                agreement.disagree,
                agreement.agree_on_cannot_tell,
                agreement.disagree_with_one_cannot_tell,
                agreement.listed_by_one_reader_only,
            )
            for key, agreement in rows.agreements.items()
        ],
    )
    write_csv(
        arguments.out_dir / "entry_matches.csv",
        (
            "trial_id",
            "part",
            "first_entry_index",
            "second_entry_index",
            "shared_step_count",
            "disagreeing_keys",
        ),
        rows.match_rows,
    )
    write_csv(
        arguments.out_dir / "unmatched_entries.csv",
        ("trial_id", "part", "reader_index", "entry_index", "step_ids", "description"),
        rows.unmatched_rows,
    )
    write_csv(
        arguments.out_dir / "step_comparisons.csv",
        (
            "trial_id",
            "step_id",
            *(f"{key}_{reader}" for key in STEP_KEYS for reader in ("0", "1")),
        ),
        rows.step_rows,
    )
    write_csv(
        arguments.out_dir / "step_label_confusion.csv",
        ("reader_0_step_label", "reader_1_step_label", "steps"),
        [(*pair, count) for pair, count in sorted(rows.step_label_pairs.items())],
    )
    write_csv(
        arguments.out_dir / "trial_comparisons.csv",
        (
            "trial_id",
            *(f"{key}_{reader}" for key in TRIAL_KEYS for reader in ("0", "1")),
            "group_count_0",
            "group_count_1",
        ),
        rows.trial_rows,
    )
    print(
        f"{compared_trials} trials with two reports, {len(rows.step_rows)} request steps compared, {len(rows.match_rows)} matched failed requests, {len(rows.unmatched_rows)} unmatched"
    )


def match_entries_by_steps(
    first_entries: Sequence[dict[str, Any]],
    second_entries: Sequence[dict[str, Any]],
    step_ids_key: str,
) -> list[EntryMatch]:
    """Match the entries of two readers one to one by the step ids under `step_ids_key`, most shared steps first, and among equals the pair whose steps overlap most in share, leaving an entry that shares no step unmatched."""
    candidates = []
    for first_index, first_entry in enumerate(first_entries):
        for second_index, second_entry in enumerate(second_entries):
            first_steps = set(first_entry[step_ids_key])
            second_steps = set(second_entry[step_ids_key])
            shared = len(first_steps & second_steps)
            if shared:
                overlap_share = shared / len(first_steps | second_steps)
                candidates.append((-shared, -overlap_share, first_index, second_index))
    matches: list[EntryMatch] = []
    used_first, used_second = set(), set()
    for negative_shared, _, first_index, second_index in sorted(candidates):
        if first_index in used_first or second_index in used_second:
            continue
        used_first.add(first_index)
        used_second.add(second_index)
        matches.append(EntryMatch(first_index, second_index, -negative_shared))
    return sorted(matches, key=lambda match: match.first_entry_index)


def _compare_part(
    trial_id: str,
    part: ComparedReportPart,
    first_report: dict[str, Any],
    second_report: dict[str, Any],
    rows: _AgreementRows,
) -> None:
    """Match the entries of one list of two reports, count the agreement of each compared key and add the rows of matched and unmatched entries."""
    first_entries = first_report.get(part.name, [])
    second_entries = second_report.get(part.name, [])
    matches = match_entries_by_steps(first_entries, second_entries, part.step_ids_key)
    for match in matches:
        first_entry = first_entries[match.first_entry_index]
        second_entry = second_entries[match.second_entry_index]
        disagreeing_keys = []
        for key in part.compared_keys:
            first_value, second_value = (
                _compared_value_of(entry[key]) for entry in (first_entry, second_entry)
            )
            rows.agreements[f"{part.name}.{key}"].add(first_value, second_value)
            if first_value != second_value:
                disagreeing_keys.append(key)
        rows.match_rows.append(
            (
                trial_id,
                part.name,
                match.first_entry_index,
                match.second_entry_index,
                match.shared_step_count,
                " ".join(disagreeing_keys),
            )
        )
    for reader_index, entries, matched_indexes in (
        (0, first_entries, {m.first_entry_index for m in matches}),
        (1, second_entries, {m.second_entry_index for m in matches}),
    ):
        rows.unmatched_rows += [
            (
                trial_id,
                part.name,
                reader_index,
                entry_index,
                " ".join(map(str, entry[part.step_ids_key])),
                _description_of(entry[part.description_key]),
            )
            for entry_index, entry in enumerate(entries)
            if entry_index not in matched_indexes
        ]


def step_facts_of(report: dict[str, Any]) -> dict[int, dict[str, frozenset[str]]]:
    """Give each request step of a report the set of each of its facts, i.e. its responses, its derived step labels full and merged and the prior candidates and reasons of its groups.

    One step can hold several calls whose requests belong to different groups, so a fact is the set of the values of every group of the step, and two readers agree on it when their sets are equal.
    """
    label_sets = step_label_sets_of(report["request_groups"])
    merged_label_sets = merged_step_label_sets_of(report["request_groups"])
    facts: dict[int, dict[str, set[str]]] = {}
    for group in report["request_groups"]:
        for step in group["request_steps"]:
            step_facts = facts.setdefault(
                step["step_id"], {key: set() for key in STEP_KEYS}
            )
            step_facts["response"].add(step["response"])
            step_facts["prior_candidate"].add(group["prior_candidate"])
            step_facts["shown_before_request"].add(group["shown_before_request"])
    return {
        step_id: {
            **{key: frozenset(values) for key, values in step_facts.items()},
            "step_label": frozenset(label_sets[step_id]),
            "merged_step_label": frozenset(merged_label_sets[step_id]),
        }
        for step_id, step_facts in facts.items()
    }


def _compare_steps(
    trial_id: str,
    first_report: dict[str, Any],
    second_report: dict[str, Any],
    rows: _AgreementRows,
) -> None:
    """Compare the facts of every request step that either reader lists, counting a step that one reader alone lists as such."""
    first_facts, second_facts = (
        step_facts_of(first_report),
        step_facts_of(second_report),
    )
    for step_id in sorted(first_facts.keys() | second_facts.keys()):
        first, second = first_facts.get(step_id), second_facts.get(step_id)
        for key in STEP_KEYS:
            if first is None or second is None:
                rows.agreements[key].listed_by_one_reader_only += 1
            else:
                rows.agreements[key].add(first[key], second[key])
        rows.step_rows.append(
            (
                trial_id,
                step_id,
                *(
                    "" if facts is None else _set_text_of(facts[key])
                    for key in STEP_KEYS
                    for facts in (first, second)
                ),
            )
        )
        rows.step_label_pairs[
            (
                NOT_LISTED if first is None else _set_text_of(first["step_label"]),
                NOT_LISTED if second is None else _set_text_of(second["step_label"]),
            )
        ] += 1


def _compare_trial(
    trial_id: str,
    first_report: dict[str, Any],
    second_report: dict[str, Any],
    rows: _AgreementRows,
) -> None:
    """Compare what the two readers say of the whole trial, e.g. its summary, its effects, the start of its first request and its disputed rows, and add one row of `trial_comparisons.csv`."""
    reports = (first_report, second_report)
    values_by_key = {
        TRIAL_USE_SUMMARY_KEY: [
            trial_use_summary_of(report["request_groups"]) for report in reports
        ],
        FIRST_REQUEST_START_KEY: [
            first_request_start_of(report["request_groups"]) for report in reports
        ],
        CONTENT_KINDS_KEY: [
            content_kinds_reaching_graded_answer_of(report["request_groups"])
            for report in reports
        ],
        GRADED_ANSWER_REACH_KEY: [
            report.get("graded_answer_reach", "") for report in reports
        ],
        EFFECTS_KEY: [_effects_text_of(report) for report in reports],
        DISPUTED_ROWS_KEY: [_disputed_rows_text_of(report) for report in reports],
    }
    for key, (first_value, second_value) in values_by_key.items():
        rows.agreements[key].add(first_value, second_value)
    rows.trial_rows.append(
        (
            trial_id,
            *(value for values in values_by_key.values() for value in values),
            *(len(report["request_groups"]) for report in reports),
        )
    )


def _set_text_of(values: frozenset[str]) -> str:
    """Write a set of values sorted and separated by spaces, e.g. the labels of a step in two groups."""
    return " ".join(sorted(values))


def _effects_text_of(report: dict[str, Any]) -> str:
    """Write the set of effects of a report, each with whether the tests grade its part, e.g. `entered_answer:yes`."""
    return " ".join(
        sorted(
            {
                f"{effect['effect']}:{effect['tests_grade_part']}"
                for group in report["request_groups"]
                for effect in group["effects"]
            }
        )
    )


def _disputed_rows_text_of(report: dict[str, Any]) -> str:
    """Write the set of disputed rows of a report, each as its step id, target and dispute."""
    return "; ".join(
        sorted(
            {
                f"{disputed['step_id']} {disputed['target']} {disputed['dispute']}"
                for disputed in report.get("request_rows_disputed", [])
            }
        )
    )


def _counted_over_of(key: str) -> str:
    if key == ONLINE_RULE_KEY or key in TRIAL_KEYS:
        return "trials"
    if key in STEP_KEYS:
        return "request steps"
    return f"matched {key.split('.')[0]}"


def _description_of(value: object) -> str:
    """Write the value that names an entry, a list such as `hosts` with its items separated by spaces."""
    if isinstance(value, list):
        return " ".join(map(str, value))
    return str(value)


def _compared_value_of(value: object) -> object:
    """Give a value as it is compared, a list of `content_kinds` as the set of its items so that order does not count."""
    if isinstance(value, list):
        return tuple(sorted(set(value)))
    return value


if __name__ == "__main__":
    main()
