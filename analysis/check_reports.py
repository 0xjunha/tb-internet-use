"""Flag what the schema of a report cannot enforce, and derive from the step ids of each request group what the trajectory and the request rows say about it.

A report is the JSON object that the reader of one reading returned, saved as `<out_dir>/reports/<trial_id>_<reader_index>.json`. The script changes no report. It writes `report_flags.csv` with one row per flag, `derived_report_facts.csv`, e.g. the first and last step of a request group and the `sender` of the request rows at its steps, and the labels that `report_labels.py` derives, in `group_labels.csv`, `step_labels.csv`, `effects.csv`, `trial_use_summaries.csv` and `other_answers.csv`, which lists every answer `other` with its explanation for a person to read.

Run it after the readings as `uv run python -I analysis/check_reports.py <raw_trials_dir> <out_dir>`.
"""

import argparse
import csv
import json
import re
import sys
from collections import Counter
from collections.abc import Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

# `python -I` leaves the folder of this script off `sys.path`.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from output_files import write_csv
from pipeline_rows import (
    RequestRow,
    host_names_of,
    is_confirmed_non_package_request,
    is_confirmed_request,
    read_trial_request_rows,
)
from reading_groups import ReadingGroup
from report_labels import (
    EFFECTS_WITH_ANSWER_PART,
    RECEIVED_RESPONSES,
    TrialUseSummary,
    cannot_tell_grade_count_of,
    content_kinds_reaching_graded_answer_of,
    first_content_groups_of,
    first_request_start_of,
    group_label_of,
    has_received_step,
    other_answers_of,
    request_step_ids_of,
    step_labels_of,
    steps_from_failed_step_of,
    trial_use_summary_of,
)
from trajectory_steps import (
    MAIN_TRAJECTORY_ID,
    TrajectoryStep,
    main_step_ids_of,
    trajectory_steps_of,
)

# The characters that a quote may add or drop, e.g. quote marks or markdown bold, left out before comparing.
_DROPPED_CHARACTERS = str.maketrans(dict.fromkeys("\"'`“”‘’*"))
# The characters that a quote may give otherwise, e.g. a dash, a slash or a full stop, compared as spaces.
_SPACED_CHARACTERS = re.compile(r"[-—–−/\\.,;:!?()\[\]{}]")
# A markdown link, whose text alone is compared.
_MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# A quote has fewer words than this.
QUOTE_WORD_LIMIT = 15
# `notes` has at most this many words.
NOTES_WORD_LIMIT = 150
FLAG_COLUMNS = ("trial_id", "reader_index", "reading_group", "flag", "where", "detail")
# The columns of `picked_trials.csv` that each row of `derived_report_facts.csv` repeats.
PICKED_TRIAL_FACT_COLUMNS = ("task", "harness", "model", "reward", "reading_group")
DERIVED_FACT_COLUMNS = (
    "trial_id",
    "reader_index",
    *PICKED_TRIAL_FACT_COLUMNS,
    "fact_kind",
    "request_group_index",
    "first_step_id",
    "last_step_id",
    "made_by_subagent",
    "request_row_senders",
    "steps_without_request_row",
    "step_id",
    "made_by",
    "category",
    "sender",
    "target",
)


class ReportFlagKind(StrEnum):
    """Kind of problem in a report that its schema cannot catch, for a person to look at."""

    UNKNOWN_STEP_ID = "unknown_step_id"
    EMPTY_REQUEST_STEPS = "empty_request_steps"
    EMPTY_CONTENT_KINDS = "empty_content_kinds"
    EMPTY_EFFECTS = "empty_effects"
    # `none_shown` beside another effect of its group, which it may not share.
    NONE_SHOWN_BESIDE_OTHER_EFFECT = "none_shown_beside_other_effect"
    # A value `other` whose sentence of explanation is empty.
    OTHER_WITHOUT_EXPLANATION = "other_without_explanation"
    FAILED_STEP_WITHOUT_CITED_STEP = "failed_step_without_cited_step"
    # An effect on the answer in a group none of whose steps got content back.
    ANSWER_EFFECT_WITHOUT_RECEIVED_CONTENT = "answer_effect_without_received_content"
    ANSWER_PART_FOR_NONE_SHOWN = "answer_part_for_none_shown"
    # An effect on the answer without the part of the answer it bears on.
    NO_ANSWER_PART_FOR_ANSWER_EFFECT = "no_answer_part_for_answer_effect"
    QUOTE_TOO_LONG = "quote_too_long"
    NOTES_TOO_LONG = "notes_too_long"
    COMMAND_WITHOUT_ENTRY = "command_without_entry"
    # A trial of `SOLVED_WITHOUT` whose reader found a request group, which a person reads.
    REQUEST_GROUP_IN_SOLVED_WITHOUT = "request_group_in_solved_without"
    # An item of `hosts` with a space or a slash, i.e. no host name.
    HOST_THAT_IS_NO_HOST_NAME = "host_that_is_no_host_name"
    # The steps of an entry of `unconfirmed_commands` differ from those that the prompt gave for its command.
    COMMAND_STEPS_DIFFER = "command_steps_differ"
    # A quote whose text no step from its first cited step through its last, or for a group's reason through the group's first request step, holds.
    QUOTE_NOT_IN_CITED_STEPS = "quote_not_in_cited_steps"
    # The reason of a group quoted from a step after the group's first request.
    QUOTE_ONLY_AFTER_REQUEST = "quote_only_after_request"
    # A confirmed request row whose result view is `not_received`, at a step that no failed request and no disputed row names.
    NOT_RECEIVED_ROW_WITHOUT_FAILED_REQUEST = "not_received_row_without_failed_request"
    # A `graded_answer_reach` of `all` or `some` without an effect that made or changed a graded part, or `none` with one.
    GRADED_ANSWER_REACH_AGAINST_EFFECTS = "graded_answer_reach_against_effects"
    # A request that a `never_sent` dispute names and that a request group or a failed request holds too, by its step and a host of its row.
    NEVER_SENT_STEP_IN_GROUP_OR_FAILURE = "never_sent_step_in_group_or_failure"
    # A dispute whose step id and target match no request row.
    DISPUTE_OF_NO_ROW = "dispute_of_no_row"
    # A confirmed non-package request row at a step that no request group names, which the reader does not dispute.
    CONFIRMED_ROW_IN_NO_GROUP = "confirmed_row_in_no_group"
    # A failed request none of whose hosts the request rows at its steps name, while those rows name hosts.
    FAILED_HOSTS_NOT_AT_STEPS = "failed_hosts_not_at_steps"
    # An entry of `trial_without_requests` whose host the prompt did not list.
    WITHOUT_ENTRY_OF_UNLISTED_HOST = "without_entry_of_unlisted_host"
    LISTED_HOST_WITHOUT_ENTRY = "listed_host_without_entry"


class DerivedFactKind(StrEnum):
    """Kind of row of `derived_report_facts.csv`."""

    REQUEST_GROUP = "request_group"
    # A request row of a category other than `package` that may be internet use, at a step that no request group names.
    REQUEST_ROW_IN_NO_GROUP = "request_row_in_no_group"


@dataclass(frozen=True, slots=True)
class ReportFlag:
    """One problem that `flags_of_report` found in a report."""

    flag: ReportFlagKind
    # The key of the report, e.g. `request_groups[1].use_step_ids`.
    where: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Quote:
    """One quote of a report with the steps that must hold it, listed by `quotes_of`."""

    # The key of the report, e.g. `online_rule.reason_given`.
    where: str
    text: str
    # The first and last step id of the steps that must hold it, None when it cites none.
    step_span: tuple[int, int] | None
    # The first request step of the group whose reason it is, None for a quote of no group.
    first_request_step_id: int | None = None


@dataclass(frozen=True, slots=True)
class ReadingContext:
    """What a report is checked against besides itself, i.e. the trajectory of its trial and what its prompt gave the reader."""

    reading_group: ReadingGroup
    trajectory_steps: Sequence[TrajectoryStep]
    # The rows of the trial's `requests.csv`.
    request_rows: Sequence[RequestRow] = ()
    # The hosts that the WITHOUT part lists.
    listed_hosts: Sequence[str] = ()
    # The steps that the COMMANDS part gives for each command.
    command_step_ids: Mapping[str, Sequence[int]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DerivedFact:
    """Row of `derived_report_facts.csv` without the trial and reader, with empty cells for what its kind does not give."""

    fact_kind: DerivedFactKind
    request_group_index: int | None = None
    first_step_id: int | None = None
    last_step_id: int | None = None
    # `yes`, `no` or `partly` by the `is_sidechain` flags of the steps, `not_recorded` when no step has one.
    made_by_subagent: str = ""
    # The distinct `sender` of the request rows at the steps of the group, separated by spaces.
    request_row_senders: str = ""
    # The steps of the group without a request row, i.e. requests that the reader added, separated by spaces.
    steps_without_request_row: str = ""
    request_row: RequestRow | None = None


@dataclass(slots=True)
class LabelRows:
    """Rows of the CSV files of derived labels that `main` gathers over the reports, one file per kind of row."""

    group_rows: list[tuple[Any, ...]] = field(default_factory=list)
    step_rows: list[tuple[Any, ...]] = field(default_factory=list)
    effect_rows: list[tuple[Any, ...]] = field(default_factory=list)
    trial_rows: list[tuple[Any, ...]] = field(default_factory=list)
    other_rows: list[tuple[Any, ...]] = field(default_factory=list)

    def add(
        self,
        trial_id: str,
        reader_index: int,
        reading_group: ReadingGroup,
        report: dict[str, Any],
    ) -> None:
        """Add the labels of the groups, steps, effects and trial of one report."""
        reading = (trial_id, reader_index, reading_group)
        request_groups = report["request_groups"]
        for group_index, group in enumerate(request_groups):
            step_ids = request_step_ids_of(group)
            steps_from_failed_step = steps_from_failed_step_of(group)
            self.group_rows.append(
                (
                    *reading,
                    group_index,
                    group_label_of(group),
                    min(step_ids) if step_ids else "",
                    "" if steps_from_failed_step is None else steps_from_failed_step,
                    group["prior_candidate"],
                    group["shown_before_request"],
                )
            )
            responses = {
                step["step_id"]: step["response"] for step in group["request_steps"]
            }
            self.step_rows += [
                (*reading, group_index, step_id, responses[step_id], label)
                for step_id, label in step_labels_of(group)
            ]
            self.effect_rows += [
                (
                    *reading,
                    group_index,
                    effect["effect"],
                    effect["answer_part"],
                    effect["tests_grade_part"],
                    group["prior_candidate"],
                    group["shown_before_request"],
                    has_received_step(group),
                )
                for effect in group["effects"]
            ]
        first_groups = first_content_groups_of(request_groups)
        self.trial_rows.append(
            (
                *reading,
                trial_use_summary_of(request_groups),
                cannot_tell_grade_count_of(request_groups),
                first_request_start_of(request_groups),
                # The values of every group tied at the earliest first request step.
                " ".join(sorted({g["shown_before_request"] for g in first_groups})),
                " ".join(sorted({g["prior_candidate"] for g in first_groups})),
                content_kinds_reaching_graded_answer_of(request_groups),
                report.get("graded_answer_reach", ""),
            )
        )
        self.other_rows += [
            (*reading, group_index, key, text)
            for group_index, key, text in other_answers_of(request_groups)
        ]

    def write(self, out_dir: Path) -> None:
        reading_columns = ("trial_id", "reader_index", "reading_group")
        write_csv(
            out_dir / "group_labels.csv",
            (
                *reading_columns,
                "group_index",
                "group_label",
                "first_request_step_id",
                "steps_from_failed_step",
                "prior_candidate",
                "shown_before_request",
            ),
            self.group_rows,
        )
        write_csv(
            out_dir / "step_labels.csv",
            (*reading_columns, "group_index", "step_id", "response", "step_label"),
            self.step_rows,
        )
        write_csv(
            out_dir / "effects.csv",
            (
                *reading_columns,
                "group_index",
                "effect",
                "answer_part",
                "tests_grade_part",
                "prior_candidate",
                "shown_before_request",
                # Effects of a group without it count in no trial value.
                "group_has_received_step",
            ),
            self.effect_rows,
        )
        write_csv(
            out_dir / "trial_use_summaries.csv",
            (
                *reading_columns,
                "trial_use_summary",
                "effects_with_tests_grade_part_cannot_tell",
                "first_request_start",
                "first_groups_shown_before_request",
                "first_groups_prior_candidate",
                "content_kinds_reaching_graded_answer",
                "graded_answer_reach",
            ),
            self.trial_rows,
        )
        write_csv(
            out_dir / "other_answers.csv",
            (*reading_columns, "group_index", "key", "text"),
            self.other_rows,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("raw_trials_dir", type=Path)
    parser.add_argument(
        "out_dir",
        type=Path,
        help="the folder with picked_trials.csv, readings.json, the trials/ of write_reading_materials.py and reports/",
    )
    arguments = parser.parse_args()

    readings = json.loads((arguments.out_dir / "readings.json").read_text())
    with (arguments.out_dir / "picked_trials.csv").open(newline="") as csv_file:
        picked_trial_cells = {
            row["trial_id"]: [row[column] for column in PICKED_TRIAL_FACT_COLUMNS]
            for row in csv.DictReader(csv_file)
            if row["trial_id"]
        }
    flag_rows: list[tuple[Any, ...]] = []
    fact_rows: list[tuple[Any, ...]] = []
    label_rows = LabelRows()
    missing_reports: list[str] = []
    for reading in readings:
        trial_id, reader_index = reading["trial_id"], reading["reader_index"]
        report_path = arguments.out_dir / "reports" / f"{trial_id}_{reader_index}.json"
        if not report_path.is_file():
            missing_reports.append(report_path.name)
            continue
        report = json.loads(report_path.read_text())
        trajectory_steps = trajectory_steps_of(
            json.loads(
                (arguments.raw_trials_dir / trial_id / "trajectory.json").read_text()
            )
        )
        reading_group = ReadingGroup(reading["reading_group"])
        request_rows = read_trial_request_rows(
            arguments.out_dir / "trials" / trial_id / "requests.csv", trial_id
        )
        context = ReadingContext(
            reading_group,
            trajectory_steps,
            request_rows,
            reading.get("listed_hosts", []),
            reading.get("command_step_ids", {}),
        )
        flag_rows += [
            (trial_id, reader_index, reading_group, f.flag, f.where, f.detail)
            for f in flags_of_report(report, context)
        ]
        fact_rows += [
            (trial_id, reader_index, *picked_trial_cells[trial_id], *_cells_of(fact))
            for fact in derived_facts_of_report(report, request_rows, trajectory_steps)
        ]
        if "request_groups" in report:
            label_rows.add(trial_id, reader_index, reading_group, report)
    write_csv(arguments.out_dir / "report_flags.csv", FLAG_COLUMNS, flag_rows)
    label_rows.write(arguments.out_dir)
    write_csv(
        arguments.out_dir / "derived_report_facts.csv", DERIVED_FACT_COLUMNS, fact_rows
    )
    print(
        f"{len(readings) - len(missing_reports)} reports checked, {len(missing_reports)} missing"
    )
    for flag, count in sorted(Counter(row[3] for row in flag_rows).items()):
        print(f"  {flag} {count}")


def flags_of_report(
    report: dict[str, Any], context: ReadingContext
) -> list[ReportFlag]:
    """List every flag of a report, by the rules that its schema cannot hold."""
    reading_group = context.reading_group
    step_ids = main_step_ids_of(list(context.trajectory_steps))
    flags = [
        ReportFlag(ReportFlagKind.UNKNOWN_STEP_ID, where, str(step_id))
        for where, step_id in _step_ids_in(report)
        if step_id not in step_ids
    ]
    for index, request_group in enumerate(report.get("request_groups", [])):
        flags += _flags_of_request_group(request_group, f"request_groups[{index}]")
    flags += [
        ReportFlag(
            ReportFlagKind.OTHER_WITHOUT_EXPLANATION,
            f"request_groups[{group_index}].{key}",
        )
        for group_index, key, text in other_answers_of(report.get("request_groups", []))
        if not text.strip()
    ]
    if "graded_answer_reach" in report:
        flags += _flags_of_graded_answer_reach(report)
    if reading_group == ReadingGroup.SOLVED_WITHOUT and report.get("request_groups"):
        flags.append(
            ReportFlag(
                ReportFlagKind.REQUEST_GROUP_IN_SOLVED_WITHOUT,
                "request_groups",
                str(len(report["request_groups"])),
            )
        )
    quotes = quotes_of(report)
    flags += [
        ReportFlag(
            ReportFlagKind.QUOTE_TOO_LONG,
            quote.where,
            f"{_word_count(quote.text)} words",
        )
        for quote in quotes
        if _word_count(quote.text) >= QUOTE_WORD_LIMIT
    ]
    flags += [
        flag
        for quote in quotes
        if quote.text.strip()
        for flag in _flags_of_quote_place(quote, context.trajectory_steps)
    ]
    if _word_count(report.get("notes", "")) > NOTES_WORD_LIMIT:
        flags.append(
            ReportFlag(
                ReportFlagKind.NOTES_TOO_LONG,
                "notes",
                f"{_word_count(report['notes'])} words",
            )
        )
    if "unconfirmed_commands" in report:
        flags += _flags_of_command_steps(
            report["unconfirmed_commands"], context.command_step_ids
        )
        entered = {entry["command"] for entry in report["unconfirmed_commands"]}
        flags += [
            ReportFlag(
                ReportFlagKind.COMMAND_WITHOUT_ENTRY, "unconfirmed_commands", command
            )
            for command in context.command_step_ids
            if command not in entered
        ]
    main_request_rows = [
        row for row in context.request_rows if row.trajectory_id == MAIN_TRAJECTORY_ID
    ]
    flags += _flags_of_disputes(report, main_request_rows)
    if "request_groups" in report:
        flags += _flags_of_confirmed_rows_in_no_group(report, main_request_rows)
    if "failed_requests" in report:
        flags += _flags_of_not_received_rows(report, context.request_rows)
        flags += _flags_of_failed_hosts(report["failed_requests"], main_request_rows)
    if "trial_without_requests" in report:
        flags += _flags_of_without_entries(
            report["trial_without_requests"]["entries"], context.listed_hosts
        )
    return flags


def derived_facts_of_report(
    report: dict[str, Any],
    request_rows: Sequence[RequestRow],
    trajectory_steps: Sequence[TrajectoryStep],
) -> list[DerivedFact]:
    """Derive the facts of each request group from its step ids, then list the request rows of a category other than `package` that may be internet use and that no group names and the reader does not dispute.

    Step ids of a report are those of the agent's own trajectory, so rows of a subagent trajectory never match one.
    """
    main_request_rows = [
        row for row in request_rows if row.trajectory_id == MAIN_TRAJECTORY_ID
    ]
    sidechain_flags = {
        step.step["step_id"]: step.is_sidechain
        for step in trajectory_steps
        if step.trajectory_id == MAIN_TRAJECTORY_ID
    }
    request_groups = report.get("request_groups", [])
    facts: list[DerivedFact] = []
    for index, request_group in enumerate(request_groups):
        group_step_ids = sorted(set(request_step_ids_of(request_group)))
        rows_at_steps = [
            row for row in main_request_rows if row.step_id in group_step_ids
        ]
        facts.append(
            DerivedFact(
                DerivedFactKind.REQUEST_GROUP,
                request_group_index=index,
                first_step_id=group_step_ids[0] if group_step_ids else None,
                last_step_id=group_step_ids[-1] if group_step_ids else None,
                made_by_subagent=_made_by_subagent_of(
                    [sidechain_flags.get(step_id) for step_id in group_step_ids]
                ),
                request_row_senders=" ".join(
                    sorted({row.sender for row in rows_at_steps})
                ),
                steps_without_request_row=" ".join(
                    str(step_id)
                    for step_id in group_step_ids
                    if not any(row.step_id == step_id for row in rows_at_steps)
                ),
            )
        )
    if "request_groups" in report:
        named_step_ids = {
            step_id
            for request_group in request_groups
            for step_id in request_step_ids_of(request_group)
        }
        disputed_rows = disputed_rows_of(report)
        facts += [
            DerivedFact(DerivedFactKind.REQUEST_ROW_IN_NO_GROUP, request_row=row)
            for row in main_request_rows
            if row.category != "package"
            and row.is_internet_use != "false"
            and row.step_id not in named_step_ids
            and (row.step_id, row.target) not in disputed_rows
        ]
    return facts


def disputed_rows_of(report: dict[str, Any]) -> set[tuple[int, str]]:
    """Give the step id and target of each request row that the reader disputes."""
    return {
        (disputed["step_id"], disputed["target"])
        for disputed in report.get("request_rows_disputed", [])
    }


def _flags_of_graded_answer_reach(report: dict[str, Any]) -> list[ReportFlag]:
    """Flag a `graded_answer_reach` that the effects do not bear out, i.e. `all` or `some` with no effect that made or changed a graded part, or `none` with one, unless the trial's content is `content_not_recorded`."""
    reach = report["graded_answer_reach"]
    trial_use_summary = trial_use_summary_of(report["request_groups"])
    # Content that the trajectory does not show may have reached the answer, so no reach contradicts it.
    if trial_use_summary == TrialUseSummary.CONTENT_NOT_RECORDED:
        return []
    made_or_changed = trial_use_summary == TrialUseSummary.GRADED_ANSWER_MADE_OR_CHANGED
    if (reach in ("all", "some") and not made_or_changed) or (
        reach == "none" and made_or_changed
    ):
        return [
            ReportFlag(
                ReportFlagKind.GRADED_ANSWER_REACH_AGAINST_EFFECTS,
                "graded_answer_reach",
                reach,
            )
        ]
    return []


def _flags_of_disputes(
    report: dict[str, Any], main_request_rows: Sequence[RequestRow]
) -> list[ReportFlag]:
    """Flag a dispute that matches no request row, and a `never_sent` dispute whose request a request group or a failed request holds, since a request that never left belongs in neither.

    A step can hold a request that never left beside one that was sent, e.g. a fallback curl after `||`, so a group or failed request holds the disputed request only when it names its step and one of the hosts of its row.
    """
    hosts_by_row = {
        (row.step_id, row.target): set(row.host_names.split())
        for row in main_request_rows
    }
    holders = [
        (set(request_step_ids_of(group)), set(group["hosts"]))
        for group in report.get("request_groups", [])
    ] + [
        (set(entry["step_ids"]), set(entry["hosts"]))
        for entry in report.get("failed_requests", [])
    ]
    flags: list[ReportFlag] = []
    for index, disputed in enumerate(report.get("request_rows_disputed", [])):
        where = f"request_rows_disputed[{index}]"
        row_key = (disputed["step_id"], disputed["target"])
        if row_key not in hosts_by_row:
            flags.append(
                ReportFlag(
                    ReportFlagKind.DISPUTE_OF_NO_ROW,
                    where,
                    f"step {disputed['step_id']} {disputed['target']}",
                )
            )
        row_hosts = hosts_by_row.get(row_key, set())
        if disputed["dispute"] == "never_sent" and any(
            disputed["step_id"] in step_ids and row_hosts & hosts
            for step_ids, hosts in holders
        ):
            flags.append(
                ReportFlag(
                    ReportFlagKind.NEVER_SENT_STEP_IN_GROUP_OR_FAILURE,
                    where,
                    f"step {disputed['step_id']} {' '.join(sorted(row_hosts))}",
                )
            )
    return flags


def _flags_of_confirmed_rows_in_no_group(
    report: dict[str, Any], main_request_rows: Sequence[RequestRow]
) -> list[ReportFlag]:
    """Flag each confirmed non-package request row whose step no request group names and whose row the reader does not dispute."""
    named_step_ids = {
        step_id
        for request_group in report["request_groups"]
        for step_id in request_step_ids_of(request_group)
    }
    disputed_rows = disputed_rows_of(report)
    return [
        ReportFlag(
            ReportFlagKind.CONFIRMED_ROW_IN_NO_GROUP,
            "request_groups",
            f"step {row.step_id} {row.target}",
        )
        for row in main_request_rows
        if is_confirmed_non_package_request(row)
        and row.step_id not in named_step_ids
        and (row.step_id, row.target) not in disputed_rows
    ]


def _flags_of_failed_hosts(
    entries: Sequence[dict[str, Any]], main_request_rows: Sequence[RequestRow]
) -> list[ReportFlag]:
    """Flag a failed request whose hosts include none that the request rows at its steps name, when those rows name any and the entry names any, since a search tool's entry names none."""
    flags: list[ReportFlag] = []
    for index, entry in enumerate(entries):
        if not entry["hosts"]:
            continue
        row_hosts = host_names_of(
            row for row in main_request_rows if row.step_id in entry["step_ids"]
        )
        if row_hosts and not row_hosts & set(entry["hosts"]):
            flags.append(
                ReportFlag(
                    ReportFlagKind.FAILED_HOSTS_NOT_AT_STEPS,
                    f"failed_requests[{index}].hosts",
                    " ".join(sorted(row_hosts)),
                )
            )
    return flags


def _flags_of_command_steps(
    entries: Sequence[dict[str, Any]], command_step_ids: Mapping[str, Sequence[int]]
) -> list[ReportFlag]:
    """Flag an entry of a command whose steps differ from those the prompt gave, naming the steps missing from the entry and those it adds."""
    flags: list[ReportFlag] = []
    for index, entry in enumerate(entries):
        listed = set(command_step_ids.get(entry["command"], []))
        given = set(entry["step_ids"])
        if listed == given:
            continue
        missing = " ".join(map(str, sorted(listed - given)))
        extra = " ".join(map(str, sorted(given - listed)))
        flags.append(
            ReportFlag(
                ReportFlagKind.COMMAND_STEPS_DIFFER,
                f"unconfirmed_commands[{index}].step_ids",
                f"missing {missing or 'none'}, extra {extra or 'none'}",
            )
        )
    return flags


def _flags_of_not_received_rows(
    report: dict[str, Any], request_rows: Sequence[RequestRow]
) -> list[ReportFlag]:
    """Flag each confirmed request row of the agent's trajectory whose result view is `not_received` and whose step no failed request names, unless the reader disputes the row."""
    named_step_ids = {
        step_id
        for entry in report["failed_requests"]
        for step_id in (*entry["step_ids"], *entry.get("failure_output_step_ids", []))
    }
    disputed_rows = disputed_rows_of(report)
    return [
        ReportFlag(
            ReportFlagKind.NOT_RECEIVED_ROW_WITHOUT_FAILED_REQUEST,
            "failed_requests",
            f"step {row.step_id} {row.target}",
        )
        for row in request_rows
        if row.trajectory_id == MAIN_TRAJECTORY_ID
        and is_confirmed_request(row)
        and row.result_view == "not_received"
        and row.step_id not in named_step_ids
        and (row.step_id, row.target) not in disputed_rows
    ]


def quotes_of(report: dict[str, Any]) -> list[Quote]:
    """List the quotes of a report with the steps where each must be found, i.e. from its earliest cited step through its latest, and for the reason of a group through the group's first request step."""
    quotes = [
        Quote(
            f"unconfirmed_commands[{index}].evidence_quote",
            entry["evidence_quote"],
            _step_span_of([*entry["step_ids"], *entry.get("evidence_step_ids", [])]),
        )
        for index, entry in enumerate(report.get("unconfirmed_commands", []))
    ]
    for index, group in enumerate(report.get("request_groups", [])):
        step_ids = request_step_ids_of(group)
        if (
            group["shown_before_request"] in ("other", "no_reason_shown")
            or not step_ids
        ):
            continue
        first_request_step_id = min(step_ids)
        quotes.append(
            Quote(
                f"request_groups[{index}].shown_before_request_detail",
                group["shown_before_request_detail"],
                _step_span_of(
                    [*group["shown_before_request_step_ids"], first_request_step_id],
                    last_step_id=first_request_step_id,
                ),
                first_request_step_id=first_request_step_id,
            )
        )
    if "online_rule" in report:
        online_rule = report["online_rule"]
        quotes.append(
            Quote(
                "online_rule.reason_given",
                online_rule["reason_given"],
                _step_span_of(online_rule["step_ids"]),
            )
        )
    return quotes


def _step_span_of(
    step_ids: Sequence[int], *, last_step_id: int | None = None
) -> tuple[int, int] | None:
    """Give the first and last step of a span that covers the cited steps, ending at `last_step_id` when it is given, None when nothing is cited."""
    if not step_ids:
        return None
    return (min(step_ids), max(step_ids) if last_step_id is None else last_step_id)


def _flags_of_quote_place(
    quote: Quote, trajectory_steps: Sequence[TrajectoryStep]
) -> list[ReportFlag]:
    """Flag a quote that no step of its span holds, as found only after the request when a later step holds the reason of a group."""
    span = quote.step_span
    if span is not None and _is_quote_in_steps(
        quote.text, range(span[0], span[1] + 1), trajectory_steps
    ):
        return []
    detail = "" if span is None else f"{span[0]} to {span[1]}"
    if quote.first_request_step_id is not None and _is_quote_in_steps(
        quote.text,
        _later_step_ids_of(quote.first_request_step_id, trajectory_steps),
        trajectory_steps,
    ):
        return [
            ReportFlag(ReportFlagKind.QUOTE_ONLY_AFTER_REQUEST, quote.where, detail)
        ]
    return [ReportFlag(ReportFlagKind.QUOTE_NOT_IN_CITED_STEPS, quote.where, detail)]


def _later_step_ids_of(
    step_id: int, trajectory_steps: Sequence[TrajectoryStep]
) -> set[int]:
    return {
        step.step["step_id"]
        for step in trajectory_steps
        if isinstance(step.step.get("step_id"), int) and step.step["step_id"] > step_id
    }


def _is_quote_in_steps(
    quote: str,
    step_ids: Collection[int],
    trajectory_steps: Sequence[TrajectoryStep],
) -> bool:
    """Tell whether one of the given steps of the agent holds the quote, both made comparable by `_comparable_text_of` and each part around an ellipsis looked for on its own."""
    step_texts = [
        _comparable_text_of(" ".join(_strings_in(step.step)))
        for step in trajectory_steps
        if step.trajectory_id == MAIN_TRAJECTORY_ID
        and step.step.get("step_id") in step_ids
    ]
    parts = [_comparable_text_of(part) for part in re.split(r"\.\.\.|…", quote)]
    return any(
        all(part in step_text for part in parts if part) for step_text in step_texts
    )


def _strings_in(value: object) -> Iterator[str]:
    """Yield every string in a step of a trajectory file, e.g. its message, the arguments of its calls and the text of its results."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings_in(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings_in(item)


def _comparable_text_of(text: str) -> str:
    """Give a text in the form in which a quote is compared with a step, i.e. without what a reader may change without changing its words.

    JSON escapes are decoded, markdown links keep their text, letter case, quote marks, `*` and backticks go, and dashes, slashes, newlines and punctuation become spaces, e.g. `**Note:** it's "TLS 1.3" — done.` and `note its tls 1 3 done` compare equal.
    """
    text = text.replace('\\"', '"').replace("\\'", "'").replace("\\n", " ")
    text = _MARKDOWN_LINK.sub(r"\1", text).lower()
    text = text.translate(_DROPPED_CHARACTERS)
    return " ".join(_SPACED_CHARACTERS.sub(" ", text).split())


def _flags_of_without_entries(
    entries: Sequence[dict[str, Any]], listed_hosts: Sequence[str]
) -> list[ReportFlag]:
    """Flag an entry of a host that the prompt did not list and a listed host without an entry."""
    entered_hosts = {entry["host"] for entry in entries}
    return [
        ReportFlag(
            ReportFlagKind.WITHOUT_ENTRY_OF_UNLISTED_HOST,
            f"trial_without_requests.entries[{index}].host",
            entry["host"],
        )
        for index, entry in enumerate(entries)
        if entry["host"] not in listed_hosts
    ] + [
        ReportFlag(
            ReportFlagKind.LISTED_HOST_WITHOUT_ENTRY,
            "trial_without_requests.entries",
            host,
        )
        for host in listed_hosts
        if host not in entered_hosts
    ]


def _flags_of_request_group(
    request_group: dict[str, Any], where: str
) -> list[ReportFlag]:
    """Flag what a request group says of its steps, hosts, reason, prior candidate and effects that its facts do not allow together."""
    flags: list[ReportFlag] = []
    for key, flag in (
        ("request_steps", ReportFlagKind.EMPTY_REQUEST_STEPS),
        ("content_kinds", ReportFlagKind.EMPTY_CONTENT_KINDS),
        ("effects", ReportFlagKind.EMPTY_EFFECTS),
    ):
        if not request_group[key]:
            flags.append(ReportFlag(flag, f"{where}.{key}"))
    flags += [
        ReportFlag(
            ReportFlagKind.HOST_THAT_IS_NO_HOST_NAME, f"{where}.hosts[{index}]", host
        )
        for index, host in enumerate(request_group["hosts"])
        if " " in host or "/" in host
    ]
    if (
        request_group["shown_before_request"] == "failed_step"
        and not request_group["shown_before_request_step_ids"]
    ):
        flags.append(
            ReportFlag(
                ReportFlagKind.FAILED_STEP_WITHOUT_CITED_STEP,
                f"{where}.shown_before_request_step_ids",
            )
        )
    effects = [effect["effect"] for effect in request_group["effects"]]
    if "none_shown" in effects and len(effects) > 1:
        flags.append(
            ReportFlag(
                ReportFlagKind.NONE_SHOWN_BESIDE_OTHER_EFFECT, f"{where}.effects"
            )
        )
    has_received_content = any(
        step["response"] in RECEIVED_RESPONSES
        for step in request_group["request_steps"]
    )
    # A group whose steps are all `not_recorded`, e.g. a provider search, may have received what the trajectory does not show, unlike a real contradiction.
    is_all_not_recorded = bool(request_group["request_steps"]) and all(
        step["response"] == "not_recorded" for step in request_group["request_steps"]
    )
    for index, effect in enumerate(request_group["effects"]):
        effect_where = f"{where}.effects[{index}]"
        name = effect["effect"]
        has_answer_part = bool(effect["answer_part"].strip())
        if name in EFFECTS_WITH_ANSWER_PART and not has_received_content:
            flags.append(
                ReportFlag(
                    ReportFlagKind.ANSWER_EFFECT_WITHOUT_RECEIVED_CONTENT,
                    effect_where,
                    f"{name}, every step not_recorded" if is_all_not_recorded else name,
                )
            )
        if name == "none_shown" and has_answer_part:
            flags.append(
                ReportFlag(
                    ReportFlagKind.ANSWER_PART_FOR_NONE_SHOWN,
                    f"{effect_where}.answer_part",
                )
            )
        if name in EFFECTS_WITH_ANSWER_PART and not has_answer_part:
            flags.append(
                ReportFlag(
                    ReportFlagKind.NO_ANSWER_PART_FOR_ANSWER_EFFECT,
                    f"{effect_where}.answer_part",
                    name,
                )
            )
    return flags


def _step_ids_in(value: object, where: str = "") -> Iterator[tuple[str, object]]:
    """Yield every step id of a report with the key that holds it, i.e. the value of a key that ends with `step_id` and each item of a list under a key that ends with `step_ids`."""
    if isinstance(value, dict):
        for key, item in value.items():
            key_where = f"{where}.{key}" if where else key
            if key.endswith("step_ids") and isinstance(item, list):
                yield from ((key_where, step_id) for step_id in item)
            elif key.endswith("step_id"):
                yield (key_where, item)
            else:
                yield from _step_ids_in(item, key_where)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _step_ids_in(item, f"{where}[{index}]")


def _made_by_subagent_of(sidechain_flags: Sequence[bool | None]) -> str:
    recorded = [flag for flag in sidechain_flags if flag is not None]
    if not recorded:
        return "not_recorded"
    if all(recorded):
        return "yes"
    return "partly" if any(recorded) else "no"


def _word_count(text: str) -> int:
    return len(text.split())


def _cells_of(fact: DerivedFact) -> tuple[Any, ...]:
    row = fact.request_row
    return (
        fact.fact_kind,
        "" if fact.request_group_index is None else fact.request_group_index,
        "" if fact.first_step_id is None else fact.first_step_id,
        "" if fact.last_step_id is None else fact.last_step_id,
        fact.made_by_subagent,
        fact.request_row_senders,
        fact.steps_without_request_row,
        "" if row is None else row.step_id,
        "" if row is None else row.made_by,
        "" if row is None else row.category,
        "" if row is None else row.sender,
        "" if row is None else row.target,
    )


if __name__ == "__main__":
    main()
