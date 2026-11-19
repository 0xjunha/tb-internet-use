"""Run the steps up to `decide_network_request_results` on raw trials, count the results per harness and check the equations that the results must meet.

An equation sets a count of the results beside a count that this script takes another way, e.g. from the expanded calls, from the requests or from the output lines that its own door reads, so that a result that the step dropped, made twice or gave without its evidence shows as a difference.
An equation whose right side is 0 counts results that break a rule that holds whatever the data, e.g. a confirmed received result without a download line or a use of the saved file of its own.
Each equation of `EQUATIONS` has its definition above its name.

It writes `trial_outcomes.csv`, `trials_not_decided.csv`, `counts_by_harness.csv`, `equations.csv`, `equation_examples.csv`, `results_by_level.csv`, `evidence_by_kind.csv`, `output_lines_by_kind.csv`, `requests_with_shown_output_and_no_trace.csv`, `unowned_output_lines.csv`, `unowned_output_lines_by_task.csv`, `judgment_rule_uses.csv`, `exit_code_rule_uses.csv`, `file_use_rule_conditions.csv`, `requests_by_evidence_pair.csv`, `judgment_rule_lower_bound_changes.csv`, `received_trials.csv`, `knowledge_row_uses.csv`, `unknown_inputs.csv` and `output_line_meanings.csv` under the output folder, `out/network_request_result/` unless `--out-dir` names another, which `.gitignore` keeps out of the repo.
They hold counts, harness names, task names, trial ids, call keys, exception type names, program, subcommand, option, web tool, output line kind and pattern names, exit codes and status codes, and in `output_line_meanings.csv` the host names and package names that output lines write, never other text from a trajectory.
The rows of each file are described above the call that writes it in `write_audit_files`, or above its entry of `_LISTS`.

The script ends with exit code 1 when a trial raised an exception or an equation differs.
Run it as `nice -n 10 uv run python -I scripts/audit_network_request_results.py <raw_trials_dir> [--limit N | --trial-ids FILE] [--out-dir DIR]`.
"""

import argparse
import functools
import sys
from collections import Counter
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from tb_internet_use.expanded_tool_call.model import (
    CallCommandText,
    ExpandedToolCall,
    FileUse,
    FileUseKind,
    OutputVisibility,
    ProgramInvocation,
    RanCommand,
    RanShellText,
    UnknownProgramInvocation,
)
from tb_internet_use.knowledge.catalog import KnowledgeUses, KnowledgeUsesTotal
from tb_internet_use.knowledge.network_request_result_knowledge import (
    NetworkRequestResultKnowledge,
)
from tb_internet_use.network_request import extract_network_requests
from tb_internet_use.network_request.model import (
    ContentSaved,
    FromCode,
    FromCommand,
    FromWebTool,
    NetworkRequest,
    NetworkRequestCertainty,
    NoContentRequested,
)
from tb_internet_use.network_request_result import (
    decide_network_request_results,
    judgment_rules,
)
from tb_internet_use.network_request_result.model import (
    ExecutionStatusEvidence,
    ExitCodeEvidence,
    FileUseEvidence,
    HttpStatusEvidence,
    NetworkRequestResult,
    NetworkRequestResultCertainty,
    NetworkRequestResultEvidence,
    NetworkRequestResultLevel,
    NetworkRequestResultStopReason,
    OutputLineEvidence,
    OutputLineKind,
    OutputLineMeaning,
    ProgramExitCodeMeaning,
    SharedOutputLineAssumptionReason,
    ShownContentEvidence,
    UnreadablePackageNamesText,
    UnusedOutputLineReason,
)
from tb_internet_use.network_request_result.parse_package_names_text import (
    parse_package_names_text,
)
from tb_internet_use.network_request_result.parse_tool_output_text import (
    parse_tool_output_text,
)
from tb_internet_use.pipeline import (
    KnowledgeDoors,
    read_trajectory,
    read_trial_file_texts,
    run_steps_to_expanded_tool_calls,
)
from tb_internet_use.tool_call.model import (
    ExecutionStatus,
    ToolCall,
    ToolCallKey,
    WebFetchAction,
    WebFindAction,
    WebSearchAction,
    indexed_action_steps_of,
    may_have_run,
)
from tb_internet_use.trial import collect_trials
from tb_internet_use.trial.model import UnreadableTrajectory

# `python -I` leaves the folder of this script off `sys.path`, so the script puts it there to import the module beside it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from trial_folders_and_csv_files import (
    PROCESS_COUNT,
    add_trial_choice_arguments,
    chosen_trial_dirs_from,
    write_csv,
)

OUT_DIR = Path(__file__).resolve().parents[1] / "out" / "network_request_result"
# Every equation in the order of the output.
# The comment above each name gives its left side beside its right side.
EQUATIONS = (
    # `NetworkRequestResult`s beside `NetworkRequest`s.
    "results_equal_requests",
    # Requests whose call key and index in the call one result has and no other beside requests.
    "each_request_has_one_result_with_its_key",
    # Lines of every call's result that this script's own door matches, the parts of a line asked from the last one and the result of web tool actions alone, also as the steps of a tool script, read as page text, beside distinct lines that an `OutputLineEvidence` of a result names, plus the lines that `decide_network_request_results` counted as unused.
    "matched_lines_equal_evidence_lines_and_unused_lines",
    # Requests from a command of the call's own text without `structure_may_be_wrong`, that exits 0 when its text does, whose text ended `FINISHED` with exit code 0 and whose outer programs all end with the exit code of the next one, beside results with an `ExitCodeEvidence` of exit code 0.
    "exit_zero_requests_equal_results_with_exit_zero_evidence",
    # Requests of calls whose result is `NOT_RUN` beside results with an `ExecutionStatusEvidence` of `NOT_RUN` that are `ATTEMPTED` and `FAILED`.
    "not_run_requests_equal_not_run_failed_results",
    # Results whose level and stop reason are none of the eight rows of the result table, with `REACHED` without a stop reason in place of `RECEIVED` without one for a request that asks for no content, beside 0.
    "results_outside_the_result_table",
    # Confirmed `RECEIVED` results without a `DOWNLOADED` line of their own and without an `USES_CONTENT` file use that fits one written file beside 0.
    "confirmed_received_results_without_own_download_or_content_use",
    # Confirmed `REACHED` results without a stop reason whose request asks for content, or that have neither a status line 100 to 399 of their own nor the status of a web fetch with one request, beside 0.
    "confirmed_reached_successes_without_own_status",
    # Results whose request certainty rose from `UNCERTAIN` to `CONFIRMED` without an output line of their own beside 0.
    "lifted_requests_without_own_line",
    # `ASSUMED` results beside results with at least one assumption reason.
    "assumed_results_equal_results_with_assumption_reasons",
    # Shared output line reasons of a result whose line no other result of the trial holds as a shared `OutputLineEvidence` beside 0.
    "shared_output_line_reasons_without_another_result_of_the_line",
    # Names counted in the counter of `decide_network_request_results` beside those of `network_request_result/judgment_rules.py`.
    "judgment_rule_names_are_of_this_step",
)
# The two sides of an equation, as `equations.csv` names them.
_SIDES = ("left", "right")
# The trial outcome of a trial that ran through the steps.
DECIDED = "decided"
# The trial outcome of an id that names no folder under the raw trials folder.
NOT_FOUND = "not found"
# The examples kept per equation and per trial outcome, so that the CSVs stay short.
_EXAMPLE_LIMIT = 20
# The rule names that the counter of `decide_network_request_results` may hold.
JUDGMENT_RULE_NAMES = frozenset(
    name
    for name in dir(judgment_rules)
    if name.startswith("treat_") and callable(getattr(judgment_rules, name))
)
_ATTEMPTED = NetworkRequestResultLevel.ATTEMPTED
_EXECUTED = NetworkRequestResultLevel.EXECUTED
_REACHED = NetworkRequestResultLevel.REACHED
_RECEIVED = NetworkRequestResultLevel.RECEIVED
_FAILED = NetworkRequestResultStopReason.FAILED
_NOT_VISIBLE = NetworkRequestResultStopReason.NOT_VISIBLE
_NOT_NEEDED = NetworkRequestResultStopReason.NOT_NEEDED
_CONFIRMED = NetworkRequestResultCertainty.CONFIRMED
# The eight rows of the result table of the criteria, as level and stop reason.
_RESULT_TABLE_ROWS = frozenset(
    {
        (_RECEIVED, None),
        (_REACHED, _FAILED),
        (_EXECUTED, _FAILED),
        (_ATTEMPTED, _FAILED),
        (_REACHED, _NOT_VISIBLE),
        (_EXECUTED, _NOT_VISIBLE),
        (_ATTEMPTED, _NOT_VISIBLE),
        (_EXECUTED, _NOT_NEEDED),
    }
)
# The view of the report for each stop reason, which the criteria give beside the result table.
_REPORT_VIEW_BY_STOP_REASON = {
    None: "received",
    _FAILED: "not received",
    _NOT_VISIBLE: "unknown",
    _NOT_NEEDED: "not needed",
}
# The levels from the lowest, to rank the evidence of a result in `_strongest_evidence_of`.
_LEVELS_IN_ORDER = (_ATTEMPTED, _EXECUTED, _REACHED, _RECEIVED)
# The level and stop reason that a line of each kind shows, with the provisional choice of each judgment rule, read again here since a result keeps no level of its evidence. Lines of status codes and of content received are read in `_level_and_stop_reason_of_evidence`.
_LEVEL_AND_STOP_REASON_BY_OUTPUT_LINE_KIND = {
    OutputLineKind.PROGRAM_MISSING: (_ATTEMPTED, _FAILED),
    OutputLineKind.NAME_NOT_RESOLVED: (_EXECUTED, _FAILED),
    OutputLineKind.CONNECTION_FAILED: (_EXECUTED, _FAILED),
    OutputLineKind.REFUSED_LOCALLY: (_EXECUTED, _FAILED),
    OutputLineKind.TLS_FAILED: (_EXECUTED, _FAILED),
    OutputLineKind.PROXY_REFUSED: (_EXECUTED, _FAILED),
    OutputLineKind.NOT_FOUND: (_EXECUTED, _FAILED),
    OutputLineKind.CONNECTION_LOST: (_REACHED, _FAILED),
    OutputLineKind.ALREADY_PRESENT: (_EXECUTED, _NOT_NEEDED),
    OutputLineKind.CONNECTED: (_REACHED, _NOT_VISIBLE),
    OutputLineKind.SERVER_ANSWERED: (_REACHED, _NOT_VISIBLE),
    OutputLineKind.DOWNLOAD_STARTED: (_REACHED, _NOT_VISIBLE),
    OutputLineKind.INSTALLED: (_EXECUTED, _NOT_VISIBLE),
    OutputLineKind.VERSION_NOTICE: (_EXECUTED, _NOT_VISIBLE),
}
# The row of `judgment_rule_lower_bound_changes.csv` for an assumed success that no one rule keeps out of the lower bound, e.g. shown content beside a failure.
_NO_SINGLE_RULE = "no single rule"
# The rules that can leave a line of one request alone uncertain, which a result does not tell apart.
_RULES_OF_AN_OWN_LINE_IN_AN_ASSUMED_RESULT = f"{judgment_rules.treat_line_beside_shown_file_or_page_text_as_not_a_trace.__name__} or {judgment_rules.treat_line_that_unknown_printer_may_have_printed_as_shared.__name__}"
_WEB_TOOL_ACTIONS = (WebFetchAction, WebSearchAction, WebFindAction)
# The place of a line in the results of one trial, i.e. the call key, the line index and the index in the JSON string.
type _LinePlace = tuple[ToolCallKey, int, int | None]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    add_trial_choice_arguments(parser)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    arguments = parser.parse_args()

    trial_dirs = list(dict.fromkeys(chosen_trial_dirs_from(arguments)))
    total = TrialAuditTotal()
    with ProcessPoolExecutor(PROCESS_COUNT) as pool:
        for trial_audit in pool.map(audit_trial, trial_dirs, chunksize=5):
            total.add_trial(trial_audit)
    write_audit_files(total, arguments.out_dir)
    print(f"trials: {dict(sorted(total.outcome_counts.items()))}")
    for equation, left, right in total.equation_rows():
        print(f"{equation}: {left} = {right} {'holds' if left == right else 'differs'}")
    print(f"written under {arguments.out_dir}")
    if total.has_exception_or_differing_equation():
        sys.exit(1)


def write_audit_files(total: TrialAuditTotal, out_dir: Path) -> None:
    """Write the CSVs from the sum of the trials, with the rows of each described above the call that writes it."""
    out_dir.mkdir(parents=True, exist_ok=True)
    # `trial_outcomes.csv` has one row for each outcome of a trial, e.g. `decided`, `not found` or `exception` with its type name, with its trials and the first 20 trial ids.
    write_csv(
        out_dir / "trial_outcomes.csv",
        ("outcome", "trial_count", "first_trial_ids"),
        (
            (outcome, count, " ".join(total.trial_id_examples_by_outcome[outcome]))
            for outcome, count in sorted(total.outcome_counts.items())
        ),
    )
    # `trials_not_decided.csv` has one row for each trial that was not decided, with its outcome.
    write_csv(
        out_dir / "trials_not_decided.csv",
        ("trial_id", "outcome"),
        total.trials_not_decided,
    )
    # `counts_by_harness.csv` has one row for each harness, or `all`, with a count, e.g. results by level, stop reason and certainty, assumed results by assumption reason, requests by the view of the report (received, not received, unknown, not needed), and matched output lines by kind.
    write_csv(
        out_dir / "counts_by_harness.csv",
        ("harness", "count_name", "count"),
        (
            (harness, count_name, count)
            for (harness, count_name), count in sorted(total.counts.items())
        ),
    )
    # `equations.csv` has one row for each equation of `EQUATIONS`, with its two sides and whether they are equal.
    write_csv(
        out_dir / "equations.csv",
        ("equation", "left", "right", "holds"),
        (
            (equation, left, right, "yes" if left == right else "no")
            for equation, left, right in total.equation_rows()
        ),
    )
    # `equation_examples.csv` has one row for each call where an equation differs, or a trial with a blank call key for an equation counted per trial, the first 20 per equation.
    write_csv(
        out_dir / "equation_examples.csv",
        ("equation", "trial_id", "tool_call_key"),
        total.equation_examples,
    )
    for list_name, file_name, key_columns in _LISTS:
        write_csv(
            out_dir / file_name,
            (*key_columns, "count", "trial_count", "task_count"),
            (
                (
                    *row_key,
                    count,
                    len(total.list_trials[list_name, row_key]),
                    len(total.list_tasks[list_name, row_key]),
                )
                for row_key, count in total.list_rows_of(list_name)
            ),
        )
    # `evidence_by_kind.csv` has one row for each kind of evidence, with the requests that have it, their trials and tasks, of those requests the confirmed received, the assumed received and the lower ones, and the requests whose strongest evidence it is, i.e. evidence that shows the level of the result, one that no other request shares first.
    write_csv(
        out_dir / "evidence_by_kind.csv",
        (
            "evidence_kind",
            "request_count",
            "trial_count",
            "task_count",
            "received_confirmed_count",
            "received_assumed_count",
            "lower_count",
            "strongest_count",
        ),
        (
            (
                row_key[0],
                count,
                len(total.list_trials[_EVIDENCE_KINDS, row_key]),
                len(total.list_tasks[_EVIDENCE_KINDS, row_key]),
                total.evidence_kind_outcome_counts[row_key[0], "received confirmed"],
                total.evidence_kind_outcome_counts[row_key[0], "received assumed"],
                total.evidence_kind_outcome_counts[row_key[0], "lower"],
                total.evidence_kind_outcome_counts[row_key[0], "strongest"],
            )
            for row_key, count in total.list_rows_of(_EVIDENCE_KINDS)
        ),
    )
    # `unowned_output_lines_by_task.csv` has one row for each task, with its trials that show an unowned line in the output of a run whose content or program is unknown and those of them without any request, most of the latter first.
    write_csv(
        out_dir / "unowned_output_lines_by_task.csv",
        ("task", "trial_count", "trial_count_without_request"),
        sorted(
            (
                (task, len(trial_ids), len(total.trials_without_request & trial_ids))
                for task, trial_ids in total.unowned_line_in_unknown_run_trials_by_task.items()
            ),
            key=lambda row: (-row[2], -row[1], row[0]),
        ),
    )
    # `judgment_rule_uses.csv` has one row for each judgment rule, with its uses, trials and tasks.
    write_csv(
        out_dir / "judgment_rule_uses.csv",
        ("judgment_rule", "use_count", "trial_count", "task_count"),
        (
            (
                name,
                count,
                total.judgment_rule_trial_counts[name],
                len(total.judgment_rule_tasks[name]),
            )
            for name, count in total.judgment_rule_use_counts.most_common()
        ),
    )
    # `received_trials.csv` has one row for all decided trials and one for each harness and each task, with its decided trials, those with a request, with a confirmed received result, with one whose request is also confirmed, with an assumed received result and with any received result.
    write_csv(
        out_dir / "received_trials.csv",
        (
            "scope",
            "trial_count",
            "trial_count_with_request",
            "trial_count_with_confirmed_received",
            "trial_count_with_confirmed_received_of_confirmed_request",
            "trial_count_with_assumed_received",
            "trial_count_with_received",
        ),
        (
            (
                scope,
                *(
                    len(total.received_trials[scope, column])
                    for column in _RECEIVED_TRIAL_COLUMNS
                ),
            )
            for scope in sorted({scope for scope, _ in total.received_trials})
        ),
    )
    uses_total = total.knowledge_uses_total
    # `knowledge_row_uses.csv` has one row for each row of a catalog or an output line pattern of `NetworkRequestResultKnowledge`, with its uses and trials.
    write_csv(
        out_dir / "knowledge_row_uses.csv",
        ("catalog", "row_key", "use_count", "trial_count"),
        (
            (
                catalog,
                " ".join(row_key),
                count,
                uses_total.row_trial_counts[catalog, row_key],
            )
            for (catalog, row_key), count in uses_total.row_use_counts.most_common()
        ),
    )
    # `unknown_inputs.csv` has one row for each program run, option or exit code without a row, with its lookups, its trials and its tasks, most lookups first.
    write_csv(
        out_dir / "unknown_inputs.csv",
        ("catalog", "row_key", "lookup_count", "trial_count", "task_count"),
        (
            (
                catalog,
                " | ".join(row_key),
                count,
                uses_total.unknown_input_trial_counts[catalog, row_key],
                len(total.unknown_input_tasks[catalog, row_key]),
            )
            for (catalog, row_key), count in sorted(
                uses_total.unknown_input_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
    )
    # `output_line_meanings.csv` has one row for each matched output line by trial, call key, line index and index in the JSON string, with its kind, host name, package names and status code, to compare with an earlier reading of the same lines.
    write_csv(
        out_dir / "output_line_meanings.csv",
        (
            "trial_id",
            "tool_call_key",
            "line_index",
            "line_index_in_json_string",
            "kind",
            "host_name",
            "package_names",
            "status_code",
        ),
        total.output_line_meaning_rows,
    )


# The names of the lists that a trial counts by a row key, with their file and key columns.
_RESULTS_BY_LEVEL = "results by level"
_EVIDENCE_KINDS = "evidence kinds"
_OUTPUT_LINES_BY_KIND = "output lines by kind"
_NO_TRACE_REQUESTS = "requests with shown output and no trace"
_UNOWNED_OUTPUT_LINES = "unowned output lines"
_EXIT_CODE_RULE_USES = "exit code rule uses"
_FILE_USE_RULE_CONDITIONS = "file use rule conditions"
_EVIDENCE_PAIRS = "evidence pairs"
_RULES_KEEPING_OUT_OF_LOWER_BOUND = "rules keeping out of the lower bound"
_LISTS = (
    # `results_by_level.csv` has one row for each harness, or `all`, a level, a stop reason and a level certainty, with its results, trials and tasks.
    (
        _RESULTS_BY_LEVEL,
        "results_by_level.csv",
        ("harness", "level", "stop_reason", "level_certainty"),
    ),
    # `output_lines_by_kind.csv` has one row for each output line kind and a use, i.e. matched, evidence of one request, evidence shared by several or unused with its reason, with its lines, trials and tasks.
    (_OUTPUT_LINES_BY_KIND, "output_lines_by_kind.csv", ("kind", "use")),
    # `requests_with_shown_output_and_no_trace.csv` has one row for each program with its subcommand and options, a code language or a web tool, with its requests whose output reached a result but which have no output line evidence, their trials and tasks, most first.
    (
        _NO_TRACE_REQUESTS,
        "requests_with_shown_output_and_no_trace.csv",
        ("program_or_means", "subcommand", "options"),
    ),
    # `unowned_output_lines.csv` has one row for each reason, an output line kind and a program name that reaches the place of the line, `(no command)` when none does, blank for the lines themselves, with the lines, trials and tasks.
    (
        _UNOWNED_OUTPUT_LINES,
        "unowned_output_lines.csv",
        ("reason", "kind", "program_name"),
    ),
    # `exit_code_rule_uses.csv` has one row for each answer of the door that makes exit code 0 give a level, a program and a subcommand, with its requests, trials and tasks.
    (
        _EXIT_CODE_RULE_USES,
        "exit_code_rule_uses.csv",
        ("door_answer", "program_name", "subcommand"),
    ),
    # `file_use_rule_conditions.csv` has one row for each condition that makes a use of a saved file uncertain, or none, with its requests, trials and tasks.
    (_FILE_USE_RULE_CONDITIONS, "file_use_rule_conditions.csv", ("condition",)),
    # `requests_by_evidence_pair.csv` has one row for each pair of evidence that the report lists apart, with its requests, trials and tasks.
    (_EVIDENCE_PAIRS, "requests_by_evidence_pair.csv", ("evidence_pair",)),
    # `judgment_rule_lower_bound_changes.csv` has one row for each judgment rule, or `no single rule` for an assumed success that no one rule keeps out of the lower bound, and whether another result of the trial is in the lower bound, with the assumed successes of confirmed requests that would be in the lower bound if the evidence of that rule alone were a fact, their trials and tasks.
    # The trials of `no` would newly be in it.
    # The rule is read from the kind of the evidence, since a result keeps no rule, so a line of one request alone names two rules.
    (
        _RULES_KEEPING_OUT_OF_LOWER_BOUND,
        "judgment_rule_lower_bound_changes.csv",
        ("judgment_rule", "trial_has_another_result_in_lower_bound"),
    ),
)
# The columns of `received_trials.csv` after the scope.
_RECEIVED_TRIAL_COLUMNS = (
    "trials",
    "with request",
    "with confirmed received",
    "with confirmed received of confirmed request",
    "with assumed received",
    "with received",
)


def audit_trial(trial_dir: Path) -> TrialAudit:
    """Run the steps up to `decide_network_request_results` on one trial, then count and check its results, with an exception named instead of raised."""
    if not trial_dir.is_dir():
        return TrialAudit(trial_dir.name, NOT_FOUND)
    try:
        harness_tool_calls = read_trajectory(trial_dir)
        if isinstance(harness_tool_calls, UnreadableTrajectory):
            return TrialAudit(trial_dir.name, f"unreadable {harness_tool_calls.reason}")
        (trial,) = collect_trials([read_trial_file_texts(trial_dir)], {})
        process_doors = process_doors_of_worker()
        knowledge_doors = process_doors.knowledge_doors
        # The doors serve every trial of the worker process, so their uses start empty for each trial.
        knowledge_doors.tool_call_knowledge.uses = KnowledgeUses()
        knowledge_doors.expanded_tool_call_knowledge.uses = KnowledgeUses()
        knowledge_doors.network_request_knowledge.uses = KnowledgeUses()
        knowledge_doors.network_request_result_knowledge.uses = KnowledgeUses()
        # The steps run as `run_steps_to_network_request_results` runs them, keeping the expanded calls and the requests that the recounts read.
        expanded_tool_calls = run_steps_to_expanded_tool_calls(
            harness_tool_calls,
            knowledge_doors=knowledge_doors,
            tool_call_judgment_rule_use_counts=Counter(),
            expanded_tool_call_judgment_rule_use_counts=Counter(),
        )
        network_requests = extract_network_requests(
            expanded_tool_calls,
            knowledge=knowledge_doors.network_request_knowledge,
            judgment_rule_use_counts=Counter(),
            no_network_request_counts=Counter(),
        )
        trial_audit = TrialAudit(
            trial_dir.name,
            DECIDED,
            harness=trial.harness,
            task=f"{trial.benchmark_version} {trial.task_name}",
        )
        network_request_results = decide_network_request_results(
            expanded_tool_calls,
            network_requests,
            knowledge=knowledge_doors.network_request_result_knowledge,
            judgment_rule_use_counts=trial_audit.judgment_rule_use_counts,
            unused_output_line_counts=trial_audit.unused_output_line_counts,
            program_counts_of_unowned_output_lines=trial_audit.program_counts_of_unowned_output_lines,
        )
        trial_audit.knowledge_uses = (
            knowledge_doors.network_request_result_knowledge.uses
        )
        # The door of this script starts empty too, and its lookups never join those of the step.
        process_doors.own_network_request_result_knowledge.uses = KnowledgeUses()
        TrialChecker(
            trial_audit,
            expanded_tool_calls,
            network_requests,
            network_request_results,
            process_doors.own_network_request_result_knowledge,
        ).check()
    except Exception as error:  # noqa: BLE001, one trial must not stop the run
        return TrialAudit(trial_dir.name, f"exception {type(error).__name__}")
    return trial_audit


@dataclass(frozen=True, slots=True)
class ProcessDoors:
    """Doors of outside knowledge made once in each worker process and used for each of its trials.

    `audit_trial` empties the `uses` of each door that a trial asks before the trial asks it, so that they count the lookups of that trial alone.
    """

    # The doors that the steps ask.
    knowledge_doors: KnowledgeDoors = field(default_factory=KnowledgeDoors)
    # The door that `TrialChecker` asks what a line means and what an exit code says, so that its lookups do not count as lookups of the step.
    own_network_request_result_knowledge: NetworkRequestResultKnowledge = field(
        default_factory=NetworkRequestResultKnowledge
    )


@functools.cache
def process_doors_of_worker() -> ProcessDoors:
    """Give the doors of this worker process, made at its first trial."""
    return ProcessDoors()


@dataclass(slots=True)
class TrialAudit:
    """Result of auditing one trial, sent from a worker process to the main process that sums the trials."""

    trial_id: str
    # `decided`, `not found`, `unreadable` with the reason, or `exception` with the type name.
    outcome: str
    harness: str = ""
    # The benchmark version and the task name, which together name a task.
    task: str = ""
    # By (harness or `all`, count name).
    counts: Counter[tuple[str, str]] = field(default_factory=Counter)
    # By (equation, `left` or `right`), every side at 0 before the trial adds to it, so that an equation the trials never reach still shows.
    equation_sides: Counter[tuple[str, str]] = field(
        default_factory=lambda: Counter(
            dict.fromkeys(
                ((equation, side) for equation in EQUATIONS for side in _SIDES), 0
            )
        )
    )
    # (equation, tool call key) of each difference of an equation, the key empty for an equation counted per trial.
    equation_examples: list[tuple[str, str]] = field(default_factory=list)
    judgment_rule_use_counts: Counter[str] = field(default_factory=Counter)
    unused_output_line_counts: Counter[
        tuple[UnusedOutputLineReason, OutputLineKind]
    ] = field(default_factory=Counter)
    program_counts_of_unowned_output_lines: Counter[
        tuple[UnusedOutputLineReason, OutputLineKind, str]
    ] = field(default_factory=Counter)
    knowledge_uses: KnowledgeUses = field(default_factory=KnowledgeUses)
    # By (list name, row key), the rows of the lists of `_LISTS` and of `evidence_by_kind.csv`.
    list_counts: Counter[tuple[str, tuple[str, ...]]] = field(default_factory=Counter)
    # By (evidence kind, `received confirmed`, `received assumed`, `lower` or `strongest`), the requests.
    evidence_kind_outcome_counts: Counter[tuple[str, str]] = field(
        default_factory=Counter
    )
    # The columns of `_RECEIVED_TRIAL_COLUMNS` that the trial fills.
    received_trial_columns: set[str] = field(default_factory=set)
    # The names that `_rules_keeping_out_of_lower_bound_of` gives for each result, once per name and result.
    rules_keeping_out_of_lower_bound: list[str] = field(default_factory=list)
    has_unowned_line_in_unknown_run: bool = False
    # The rows of `output_line_meanings.csv` without the trial id.
    output_line_meaning_rows: list[tuple[str, int, str, str, str, str, str]] = field(
        default_factory=list
    )

    def count(self, count_name: str, amount: int = 1) -> None:
        """Add to a count of the trial's harness and of all harnesses."""
        self.counts[self.harness, count_name] += amount
        self.counts["all", count_name] += amount

    def add_sides(
        self, equation: str, left: int, right: int, tool_call_key: ToolCallKey | None
    ) -> None:
        """Add the two sides of an equation for one call or one trial, keeping the call as an example when they differ."""
        if equation not in EQUATIONS:
            raise ValueError(f"no equation {equation}")
        self.equation_sides[equation, "left"] += left
        self.equation_sides[equation, "right"] += right
        if left != right:
            self.equation_examples.append(
                (
                    equation,
                    ""
                    if tool_call_key is None
                    else _text_of_tool_call_key(tool_call_key),
                )
            )


@dataclass(slots=True)
class TrialAuditTotal:
    """Sum of the `TrialAudit` of many trials, built by `main` to write the CSVs."""

    outcome_counts: Counter[str] = field(default_factory=Counter)
    trial_id_examples_by_outcome: dict[str, list[str]] = field(default_factory=dict)
    # (trial id, outcome) of each trial whose outcome is not `decided`.
    trials_not_decided: list[tuple[str, str]] = field(default_factory=list)
    counts: Counter[tuple[str, str]] = field(default_factory=Counter)
    equation_sides: Counter[tuple[str, str]] = field(default_factory=Counter)
    equation_examples: list[tuple[str, str, str]] = field(default_factory=list)
    judgment_rule_use_counts: Counter[str] = field(default_factory=Counter)
    judgment_rule_trial_counts: Counter[str] = field(default_factory=Counter)
    judgment_rule_tasks: dict[str, set[str]] = field(default_factory=dict)
    knowledge_uses_total: KnowledgeUsesTotal = field(default_factory=KnowledgeUsesTotal)
    unknown_input_tasks: dict[tuple[str, tuple[str, ...]], set[str]] = field(
        default_factory=dict
    )
    list_counts: Counter[tuple[str, tuple[str, ...]]] = field(default_factory=Counter)
    list_trials: dict[tuple[str, tuple[str, ...]], set[str]] = field(
        default_factory=lambda: _DefaultSets()
    )
    list_tasks: dict[tuple[str, tuple[str, ...]], set[str]] = field(
        default_factory=lambda: _DefaultSets()
    )
    evidence_kind_outcome_counts: Counter[tuple[str, str]] = field(
        default_factory=Counter
    )
    # By (scope, column of `_RECEIVED_TRIAL_COLUMNS`), the trial ids.
    received_trials: dict[tuple[str, str], set[str]] = field(
        default_factory=lambda: _DefaultSets()
    )
    unowned_line_in_unknown_run_trials_by_task: dict[str, set[str]] = field(
        default_factory=dict
    )
    trials_without_request: set[str] = field(default_factory=set)
    output_line_meaning_rows: list[tuple[str, str, int, str, str, str, str, str]] = (
        field(default_factory=list)
    )

    def add_trial(self, trial_audit: TrialAudit) -> None:
        """Add what one trial counted, keeping the first examples of each outcome and equation."""
        trial_id = trial_audit.trial_id
        task = trial_audit.task
        self.outcome_counts[trial_audit.outcome] += 1
        trial_ids = self.trial_id_examples_by_outcome.setdefault(
            trial_audit.outcome, []
        )
        if len(trial_ids) < _EXAMPLE_LIMIT:
            trial_ids.append(trial_id)
        if trial_audit.outcome != DECIDED:
            self.trials_not_decided.append((trial_id, trial_audit.outcome))
        self.counts.update(trial_audit.counts)
        self.equation_sides.update(trial_audit.equation_sides)
        for equation, tool_call_key in trial_audit.equation_examples:
            kept = sum(
                1 for example in self.equation_examples if example[0] == equation
            )
            if kept < _EXAMPLE_LIMIT:
                self.equation_examples.append((equation, trial_id, tool_call_key))
        self.judgment_rule_use_counts.update(trial_audit.judgment_rule_use_counts)
        self.judgment_rule_trial_counts.update(
            trial_audit.judgment_rule_use_counts.keys()
        )
        for name in trial_audit.judgment_rule_use_counts:
            self.judgment_rule_tasks.setdefault(name, set()).add(task)
        self.knowledge_uses_total.add_trial(trial_audit.knowledge_uses)
        for lookup_key in trial_audit.knowledge_uses.unknown_input_counts:
            self.unknown_input_tasks.setdefault(lookup_key, set()).add(task)
        self.list_counts.update(trial_audit.list_counts)
        for list_key in trial_audit.list_counts:
            self.list_trials[list_key].add(trial_id)
            self.list_tasks[list_key].add(task)
        self.evidence_kind_outcome_counts.update(
            trial_audit.evidence_kind_outcome_counts
        )
        if trial_audit.outcome == DECIDED:
            for scope in ("all", f"harness {trial_audit.harness}", f"task {task}"):
                self.received_trials[scope, "trials"].add(trial_id)
                for column in trial_audit.received_trial_columns:
                    self.received_trials[scope, column].add(trial_id)
            if "with request" not in trial_audit.received_trial_columns:
                self.trials_without_request.add(trial_id)
        if trial_audit.has_unowned_line_in_unknown_run:
            self.unowned_line_in_unknown_run_trials_by_task.setdefault(task, set()).add(
                trial_id
            )
        self.output_line_meaning_rows += [
            (trial_id, *row) for row in trial_audit.output_line_meaning_rows
        ]

    def list_rows_of(self, list_name: str) -> list[tuple[tuple[str, ...], int]]:
        """List the rows of one list with their counts, most first and then by key."""
        return sorted(
            (
                (row_key, count)
                for (name, row_key), count in self.list_counts.items()
                if name == list_name
            ),
            key=lambda item: (-item[1], item[0]),
        )

    def equation_rows(self) -> list[tuple[str, int, int]]:
        """List each equation with its two sides, in the order of `EQUATIONS`."""
        return [
            (
                equation,
                self.equation_sides[equation, "left"],
                self.equation_sides[equation, "right"],
            )
            for equation in EQUATIONS
        ]

    def has_exception_or_differing_equation(self) -> bool:
        """Tell whether a trial raised an exception or the two sides of an equation differ, which makes `main` end with exit code 1."""
        return any(
            outcome.startswith("exception") for outcome in self.outcome_counts
        ) or any(left != right for _, left, right in self.equation_rows())


class _DefaultSets[Key](dict[Key, set[str]]):
    """Dictionary of sets that makes an empty set for a missing key, used by the total to gather trial ids and tasks."""

    def __missing__(self, key: Key) -> set[str]:
        value: set[str] = set()
        self[key] = value
        return value


class TrialChecker:
    """Checker of the results of one trial, which adds its counts, lists and the sides of each equation to a `TrialAudit`.

    It reads the expanded calls, the requests and the results, and asks its own door what each output line means, so its recounts do not go through the pieces of the step they check.
    """

    def __init__(
        self,
        trial_audit: TrialAudit,
        expanded_tool_calls: Sequence[ExpandedToolCall],
        network_requests: Sequence[NetworkRequest],
        network_request_results: Sequence[NetworkRequestResult],
        own_knowledge: NetworkRequestResultKnowledge,
    ) -> None:
        self.trial_audit = trial_audit
        self.expanded_tool_calls = expanded_tool_calls
        self.network_requests = network_requests
        self.network_request_results = network_request_results
        self.own_knowledge = own_knowledge
        self.expanded_tool_call_by_key = {
            expanded_tool_call.tool_call.harness_tool_call.key: expanded_tool_call
            for expanded_tool_call in expanded_tool_calls
        }
        self.request_counts_by_key = Counter(
            network_request.tool_call_key for network_request in network_requests
        )
        self.output_line_meaning_by_place = self._output_line_meanings_by_place()

    def check(self) -> None:
        """Count the trial and check every equation of `EQUATIONS`."""
        self.check_results_against_requests()
        self.check_output_lines()
        self.check_exit_zero_evidence()
        self.check_not_run_requests()
        for network_request_result in self.network_request_results:
            self.check_result(network_request_result)
            self.count_result(network_request_result)
        self.check_shared_output_line_reasons()
        self.count_unowned_output_lines()
        self.count_trial()
        self.trial_audit.add_sides(
            "judgment_rule_names_are_of_this_step",
            len(self.trial_audit.judgment_rule_use_counts),
            len(self.trial_audit.judgment_rule_use_counts.keys() & JUDGMENT_RULE_NAMES),
            None,
        )

    def _output_line_meanings_by_place(self) -> dict[_LinePlace, OutputLineMeaning]:
        """Read the result of every call with this script's own door, the parts of a line from the last one, page text for a call of web tool actions alone."""
        output_line_meaning_by_place: dict[_LinePlace, OutputLineMeaning] = {}
        for expanded_tool_call in self.expanded_tool_calls:
            tool_call = expanded_tool_call.tool_call
            if tool_call.result is None or tool_call.result.tool_output_text is None:
                continue
            is_web_tool_result = _has_only_web_tool_actions(tool_call)
            for tool_output_line in parse_tool_output_text(
                tool_call.result.tool_output_text
            ):
                for part in tool_output_line.parts:
                    output_line_meaning = self.own_knowledge.output_line_meaning(
                        part, is_web_tool_result=is_web_tool_result
                    )
                    if isinstance(output_line_meaning, OutputLineMeaning):
                        output_line_meaning_by_place[
                            tool_call.harness_tool_call.key,
                            tool_output_line.line_index,
                            tool_output_line.line_index_in_json_string,
                        ] = output_line_meaning
                        break
        return output_line_meaning_by_place

    def check_results_against_requests(self) -> None:
        """Check that each request has one result with its key and that there are no others."""
        result_counts = Counter(
            _request_key_of(result.network_request)
            for result in self.network_request_results
        )
        self.trial_audit.add_sides(
            "results_equal_requests",
            len(self.network_request_results),
            len(self.network_requests),
            None,
        )
        for network_request in self.network_requests:
            self.trial_audit.add_sides(
                "each_request_has_one_result_with_its_key",
                1 if result_counts[_request_key_of(network_request)] == 1 else 0,
                1,
                network_request.tool_call_key,
            )

    def check_output_lines(self) -> None:
        """Check that the lines that the own door matches are as many as the distinct lines named as evidence and the lines counted as unused, and count the lines by kind and use."""
        trial_audit = self.trial_audit
        shared_by_place: dict[_LinePlace, bool] = {}
        for result in self.network_request_results:
            for evidence in result.evidence:
                if isinstance(evidence, OutputLineEvidence):
                    place = (
                        evidence.showing_tool_call_key,
                        evidence.line_index,
                        evidence.line_index_in_json_string,
                    )
                    # A line is evidence of one request when any result has it without sharing.
                    shared_by_place[place] = shared_by_place.get(place, True) and (
                        evidence.is_shared_with_other_requests
                    )
        trial_audit.add_sides(
            "matched_lines_equal_evidence_lines_and_unused_lines",
            len(self.output_line_meaning_by_place),
            len(shared_by_place) + sum(trial_audit.unused_output_line_counts.values()),
            None,
        )
        for place, output_line_meaning in self.output_line_meaning_by_place.items():
            kind = output_line_meaning.kind.value
            trial_audit.count(f"matched output lines {kind}")
            trial_audit.list_counts[_OUTPUT_LINES_BY_KIND, (kind, "matched")] += 1
            if place in shared_by_place:
                use = (
                    "evidence shared by several requests"
                    if shared_by_place[place]
                    else "evidence of one request"
                )
                trial_audit.list_counts[_OUTPUT_LINES_BY_KIND, (kind, use)] += 1
            trial_audit.output_line_meaning_rows.append(
                _output_line_meaning_row_of(place, output_line_meaning)
            )
        for (reason, kind), count in trial_audit.unused_output_line_counts.items():
            trial_audit.list_counts[
                _OUTPUT_LINES_BY_KIND, (kind.value, f"unused {reason.value}")
            ] += count

    def check_exit_zero_evidence(self) -> None:
        """Check that as many results have exit code 0 as evidence as there are requests whose command's run the exit code 0 of its call's text shows."""
        results_with_exit_zero = sum(
            1
            for result in self.network_request_results
            if any(
                isinstance(evidence, ExitCodeEvidence) and evidence.exit_code == 0
                for evidence in result.evidence
            )
        )
        self.trial_audit.add_sides(
            "exit_zero_requests_equal_results_with_exit_zero_evidence",
            sum(
                1
                for network_request in self.network_requests
                if self._is_run_shown_by_exit_zero(network_request)
            ),
            results_with_exit_zero,
            None,
        )

    def _is_run_shown_by_exit_zero(self, network_request: NetworkRequest) -> bool:
        source = network_request.source
        if not isinstance(source, FromCommand) or not isinstance(
            source.ran_text_source, CallCommandText
        ):
            return False
        expanded_tool_call = self.expanded_tool_call_by_key[
            network_request.tool_call_key
        ]
        command_text_status = expanded_tool_call.command_text_status
        if (
            not may_have_run(expanded_tool_call.tool_call)
            or command_text_status is None
            or command_text_status.execution_status != ExecutionStatus.FINISHED
            or command_text_status.exit_code != 0
        ):
            return False
        ran_command = _call_text_ran_command_of(expanded_tool_call, source.command_id)
        if ran_command is None:
            return False
        shell_command = ran_command.shell_command
        if (
            shell_command.structure_may_be_wrong
            or not shell_command.succeeded_if_text_exits_zero
        ):
            return False
        return _do_outer_programs_end_with_exit_code_of_next(
            ran_command, source.program_invocation
        )

    def check_not_run_requests(self) -> None:
        """Check that as many results fail at `ATTEMPTED` on the status `NOT_RUN` as there are requests of calls that did not run."""
        self.trial_audit.add_sides(
            "not_run_requests_equal_not_run_failed_results",
            sum(
                1
                for network_request in self.network_requests
                if not may_have_run(
                    self.expanded_tool_call_by_key[
                        network_request.tool_call_key
                    ].tool_call
                )
            ),
            sum(
                1
                for result in self.network_request_results
                if (result.level, result.stop_reason) == (_ATTEMPTED, _FAILED)
                and any(
                    isinstance(evidence, ExecutionStatusEvidence)
                    and evidence.execution_status == ExecutionStatus.NOT_RUN
                    for evidence in result.evidence
                )
            ),
            None,
        )

    def check_result(self, result: NetworkRequestResult) -> None:
        """Check the combination of level and stop reason, the evidence that a confirmed received or reached result and a lifted request need, and that an assumed result has assumption reasons."""
        network_request = result.network_request
        asks_for_no_content = isinstance(
            network_request.received_content_destination, NoContentRequested
        )
        level_and_stop_reason = (result.level, result.stop_reason)
        # A request that asks for no content succeeds at `REACHED`, so that row stands in for the row of content received.
        result_table_rows = (
            _RESULT_TABLE_ROWS - {(_RECEIVED, None)} | {(_REACHED, None)}
            if asks_for_no_content
            else _RESULT_TABLE_ROWS
        )
        tool_call_key = network_request.tool_call_key
        self.trial_audit.add_sides(
            "results_outside_the_result_table",
            0 if level_and_stop_reason in result_table_rows else 1,
            0,
            tool_call_key,
        )
        is_confirmed = result.level_certainty == _CONFIRMED
        if level_and_stop_reason == (_RECEIVED, None) and is_confirmed:
            self.trial_audit.add_sides(
                "confirmed_received_results_without_own_download_or_content_use",
                0 if self._has_own_download_or_content_use(result) else 1,
                0,
                tool_call_key,
            )
        if level_and_stop_reason == (_REACHED, None) and is_confirmed:
            self.trial_audit.add_sides(
                "confirmed_reached_successes_without_own_status",
                0
                if asks_for_no_content and self._has_own_success_status(result)
                else 1,
                0,
                tool_call_key,
            )
        self.trial_audit.add_sides(
            "assumed_results_equal_results_with_assumption_reasons",
            1 if result.level_certainty == NetworkRequestResultCertainty.ASSUMED else 0,
            1 if result.assumption_reasons else 0,
            tool_call_key,
        )
        if (
            network_request.certainty == NetworkRequestCertainty.UNCERTAIN
            and result.request_certainty_after_evidence
            == NetworkRequestCertainty.CONFIRMED
        ):
            self.trial_audit.add_sides(
                "lifted_requests_without_own_line",
                0
                if any(
                    isinstance(evidence, OutputLineEvidence)
                    and not evidence.is_shared_with_other_requests
                    for evidence in result.evidence
                )
                else 1,
                0,
                tool_call_key,
            )

    def check_shared_output_line_reasons(self) -> None:
        """Check that the line of each shared output line reason is a shared line of another result too, so that the results that share it can be found together."""
        result_indexes_by_shared_line: dict[_LinePlace, set[int]] = {}
        for result_index, result in enumerate(self.network_request_results):
            for evidence in result.evidence:
                if (
                    isinstance(evidence, OutputLineEvidence)
                    and evidence.is_shared_with_other_requests
                ):
                    result_indexes_by_shared_line.setdefault(
                        (
                            evidence.showing_tool_call_key,
                            evidence.line_index,
                            evidence.line_index_in_json_string,
                        ),
                        set(),
                    ).add(result_index)
        for result_index, result in enumerate(self.network_request_results):
            for assumption_reason in result.assumption_reasons:
                if not isinstance(assumption_reason, SharedOutputLineAssumptionReason):
                    continue
                result_indexes = result_indexes_by_shared_line.get(
                    (
                        assumption_reason.showing_tool_call_key,
                        assumption_reason.line_index,
                        assumption_reason.line_index_in_json_string,
                    ),
                    set(),
                )
                self.trial_audit.add_sides(
                    "shared_output_line_reasons_without_another_result_of_the_line",
                    0 if result_indexes - {result_index} else 1,
                    0,
                    result.network_request.tool_call_key,
                )

    def _has_own_download_or_content_use(self, result: NetworkRequestResult) -> bool:
        return any(
            isinstance(evidence, OutputLineEvidence)
            and evidence.kind == OutputLineKind.DOWNLOADED
            and not evidence.is_shared_with_other_requests
            or isinstance(evidence, FileUseEvidence)
            and evidence.file_use.kind == FileUseKind.USES_CONTENT
            and not evidence.file_use.fits_several_written_files
            for evidence in result.evidence
        )

    def _has_own_success_status(self, result: NetworkRequestResult) -> bool:
        for evidence in result.evidence:
            if isinstance(evidence, OutputLineEvidence):
                status_code = self._status_code_of_line(evidence)
                if (
                    not evidence.is_shared_with_other_requests
                    and status_code is not None
                    and 100 <= status_code <= 399
                ):
                    return True
            if (
                isinstance(evidence, HttpStatusEvidence)
                and 100 <= evidence.http_status <= 399
                and self.request_counts_by_key[evidence.showing_tool_call_key] == 1
            ):
                return True
        return False

    def _status_code_of_line(self, evidence: OutputLineEvidence) -> int | None:
        output_line_meaning = self.output_line_meaning_by_place.get(
            (
                evidence.showing_tool_call_key,
                evidence.line_index,
                evidence.line_index_in_json_string,
            )
        )
        if output_line_meaning is None or output_line_meaning.kind not in (
            OutputLineKind.HTTP_STATUS,
            OutputLineKind.BARE_STATUS_CODE,
        ):
            return None
        return output_line_meaning.status_code

    def count_result(self, result: NetworkRequestResult) -> None:
        """Count one result by level, view, evidence, and the lists of requests that the report reads."""
        trial_audit = self.trial_audit
        level = result.level.value
        stop_reason = "none" if result.stop_reason is None else result.stop_reason.value
        level_certainty = result.level_certainty.value
        trial_audit.count("results")
        trial_audit.count(f"results {level} {stop_reason} {level_certainty}")
        trial_audit.count(
            f"requests in the view {_REPORT_VIEW_BY_STOP_REASON[result.stop_reason]} {level_certainty}"
        )
        if result.request_certainty_after_evidence != result.network_request.certainty:
            trial_audit.count("requests lifted to confirmed by the evidence")
        for assumption_reason_name in dict.fromkeys(
            type(assumption_reason).__name__
            for assumption_reason in result.assumption_reasons
        ):
            trial_audit.count(
                f"assumed results with the reason {assumption_reason_name}"
            )
        for harness in (trial_audit.harness, "all"):
            trial_audit.list_counts[
                _RESULTS_BY_LEVEL, (harness, level, stop_reason, level_certainty)
            ] += 1
        outcome = self._outcome_of(result)
        for evidence_kind in self._evidence_kinds_of(result):
            trial_audit.list_counts[_EVIDENCE_KINDS, (evidence_kind,)] += 1
            trial_audit.evidence_kind_outcome_counts[evidence_kind, outcome] += 1
        strongest_evidence = self._strongest_evidence_of(result)
        if strongest_evidence is not None:
            trial_audit.evidence_kind_outcome_counts[
                self._evidence_kind_of(result, strongest_evidence), "strongest"
            ] += 1
        if not any(
            isinstance(evidence, OutputLineEvidence) for evidence in result.evidence
        ) and self._has_shown_output(result.network_request):
            trial_audit.list_counts[
                _NO_TRACE_REQUESTS, _means_of(result.network_request)
            ] += 1
        for exit_code_rule_use in self._exit_code_rule_uses_of(result):
            trial_audit.list_counts[_EXIT_CODE_RULE_USES, exit_code_rule_use] += 1
        for condition in self._file_use_rule_conditions_of(result.network_request):
            trial_audit.list_counts[_FILE_USE_RULE_CONDITIONS, (condition,)] += 1
        for evidence_pair in self._evidence_pairs_of(result):
            trial_audit.list_counts[_EVIDENCE_PAIRS, (evidence_pair,)] += 1
        trial_audit.rules_keeping_out_of_lower_bound += (
            self._rules_keeping_out_of_lower_bound_of(result)
        )
        trial_audit.received_trial_columns.add("with request")
        if result.level == _RECEIVED:
            trial_audit.received_trial_columns.add("with received")
            if result.level_certainty == _CONFIRMED:
                trial_audit.received_trial_columns.add("with confirmed received")
                if (
                    result.request_certainty_after_evidence
                    == NetworkRequestCertainty.CONFIRMED
                ):
                    trial_audit.received_trial_columns.add(
                        "with confirmed received of confirmed request"
                    )
            else:
                trial_audit.received_trial_columns.add("with assumed received")

    def _outcome_of(self, result: NetworkRequestResult) -> str:
        if result.level == _RECEIVED:
            return (
                "received confirmed"
                if result.level_certainty == _CONFIRMED
                else "received assumed"
            )
        return "lower"

    def _evidence_kinds_of(self, result: NetworkRequestResult) -> set[str]:
        """Name the kinds of evidence of a result as `_evidence_kind_of` names each, and a use of the saved file that shows only its size or type, which gives no evidence."""
        evidence_kinds = {
            self._evidence_kind_of(result, evidence) for evidence in result.evidence
        }
        if any(
            file_use.kind == FileUseKind.SHOWS_SIZE_OR_TYPE
            for file_use in self._saved_file_uses_of(result.network_request)
        ):
            evidence_kinds.add("file use shows_size_or_type, which gives no evidence")
        return evidence_kinds

    def _evidence_kind_of(
        self, result: NetworkRequestResult, evidence: NetworkRequestResultEvidence
    ) -> str:
        """Name the kind of one piece of evidence of a result, splitting status codes at 400, shown content by tool, file uses by kind and exit code 0 by the door's answer."""
        if isinstance(evidence, OutputLineEvidence):
            status_code = self._status_code_of_line(evidence)
            status_range = (
                ""
                if status_code is None
                else " 100-399"
                if 100 <= status_code <= 399
                else " 400-599"
                if 400 <= status_code <= 599
                else f" {status_code}"
            )
            return f"output line {evidence.kind.value}{status_range}"
        if isinstance(evidence, HttpStatusEvidence):
            return (
                "http status 100-399"
                if evidence.http_status < 400
                else "http status 400-599"
            )
        if isinstance(evidence, ShownContentEvidence):
            action = self.expanded_tool_call_by_key[
                evidence.showing_tool_call_key
            ].tool_call.action
            return (
                "shown content of web search"
                if isinstance(action, WebSearchAction)
                else "shown content of web fetch"
                if isinstance(action, WebFetchAction)
                else "shown content of a command result"
            )
        if isinstance(evidence, FileUseEvidence):
            return f"file use {evidence.file_use.kind.value}"
        if isinstance(evidence, ExitCodeEvidence):
            return f"exit code {evidence.exit_code}, door answer {self._exit_code_answer_of(result.network_request, evidence.exit_code)}"
        return f"execution status {evidence.execution_status.value}"

    def _strongest_evidence_of(
        self, result: NetworkRequestResult
    ) -> NetworkRequestResultEvidence | None:
        """Find the strongest evidence of a result, i.e. one that shows its level as `_level_and_stop_reason_of_evidence` reads it, or the highest below it, evidence that no other request shares first and then the first in order.

        A result keeps no level of each piece of evidence, so this script reads the level again from the kind of the evidence with the provisional choice of each judgment rule. A line that names another target is read by its kind, so its level is capped at the result's, e.g. `Downloading B-1.0.whl` under `pip install A` does not outrank exit code 0.
        """
        level_index = _LEVELS_IN_ORDER.index(result.level)
        evidence_with_level_index = [
            (
                min(
                    _LEVELS_IN_ORDER.index(
                        self._level_and_stop_reason_of_evidence(result, evidence)[0]
                    ),
                    level_index,
                ),
                not _is_evidence_shared(evidence),
                -evidence_index,
                evidence,
            )
            for evidence_index, evidence in enumerate(result.evidence)
        ]
        if not evidence_with_level_index:
            return None
        return max(evidence_with_level_index, key=lambda item: item[:3])[3]

    def _level_and_stop_reason_of_evidence(
        self, result: NetworkRequestResult, evidence: NetworkRequestResultEvidence
    ) -> tuple[NetworkRequestResultLevel, NetworkRequestResultStopReason | None]:
        """Read the level and stop reason that one piece of evidence shows, from its kind, the status code of its line and the door's answer for exit code 0, with the provisional choice of each judgment rule.

        Content received or a status below 400 is a success at `REACHED` for a request that asks for no content, e.g. `curl -I u`.
        """
        success_level = (
            _REACHED
            if isinstance(
                result.network_request.received_content_destination,
                NoContentRequested,
            )
            else _RECEIVED
        )
        if isinstance(evidence, ExecutionStatusEvidence):
            return (
                (_ATTEMPTED, _FAILED)
                if evidence.execution_status == ExecutionStatus.NOT_RUN
                else (_EXECUTED, _NOT_VISIBLE)
            )
        if isinstance(evidence, ShownContentEvidence | FileUseEvidence):
            return success_level, None
        if isinstance(evidence, ExitCodeEvidence):
            answer = self._exit_code_answer_of(
                result.network_request, evidence.exit_code
            )
            if answer == ProgramExitCodeMeaning.REQUEST_SUCCEEDED.value:
                return success_level, None
            if answer == ProgramExitCodeMeaning.SERVER_ANSWERED.value:
                return _REACHED, _NOT_VISIBLE
            return _EXECUTED, _NOT_VISIBLE
        status_code = (
            evidence.http_status
            if isinstance(evidence, HttpStatusEvidence)
            else self._status_code_of_line(evidence)
        )
        if status_code is not None:
            if status_code == 0:
                return _EXECUTED, _FAILED
            if status_code >= 400:
                return _REACHED, _FAILED
            return (
                (_REACHED, None)
                if success_level == _REACHED
                else (_REACHED, _NOT_VISIBLE)
            )
        assert isinstance(evidence, OutputLineEvidence)
        if evidence.kind == OutputLineKind.DOWNLOADED:
            return success_level, None
        return _LEVEL_AND_STOP_REASON_BY_OUTPUT_LINE_KIND[evidence.kind]

    def _rules_keeping_out_of_lower_bound_of(
        self, result: NetworkRequestResult
    ) -> list[str]:
        """Name each judgment rule whose evidence alone, if it were a fact, would put an assumed success of a confirmed request into the lower bound, or `no single rule`.

        The success evidence of each rule is read from its kind, e.g. shown content for `treat_shown_result_text_as_assumed_content`. A line of this request alone in an assumed result rests on a rule that the result does not name, so it is listed under the two rules that make such a line uncertain.
        Failure evidence beside the success makes the result rest on the rule that picks between them, which then is the only rule that could change it, and only when a line of this request alone shows the success.
        """
        success_level = (
            _REACHED
            if isinstance(
                result.network_request.received_content_destination,
                NoContentRequested,
            )
            else _RECEIVED
        )
        if (
            (result.level, result.stop_reason) != (success_level, None)
            or result.level_certainty == _CONFIRMED
            or result.request_certainty_after_evidence
            != NetworkRequestCertainty.CONFIRMED
        ):
            return []
        levels_and_stop_reasons = [
            (evidence, self._level_and_stop_reason_of_evidence(result, evidence))
            for evidence in result.evidence
        ]
        failure_levels = [
            level
            for _, (level, stop_reason) in levels_and_stop_reasons
            if stop_reason == _FAILED
        ]
        success_evidence = [
            evidence
            for evidence, level_and_stop_reason in levels_and_stop_reasons
            if level_and_stop_reason == (success_level, None)
        ]
        if failure_levels:
            if not any(
                isinstance(evidence, OutputLineEvidence)
                and not evidence.is_shared_with_other_requests
                for evidence in success_evidence
            ):
                return [_NO_SINGLE_RULE]
            return [
                judgment_rules.treat_stop_reasons_of_one_level_as_first_in_fixed_order.__name__
                if success_level in failure_levels
                else judgment_rules.treat_higher_evidence_beside_failure_as_assumed_level.__name__
            ]
        rule_names = sorted(
            {
                rule_name
                for evidence in success_evidence
                if (rule_name := self._rule_of_success_evidence(evidence)) is not None
            }
        )
        return rule_names or [_NO_SINGLE_RULE]

    def _rule_of_success_evidence(
        self, evidence: NetworkRequestResultEvidence
    ) -> str | None:
        """Name the judgment rule that leaves one piece of success evidence assumed, or None for evidence that another request shares, which no rule leaves so."""
        if isinstance(evidence, ShownContentEvidence):
            return judgment_rules.treat_shown_result_text_as_assumed_content.__name__
        if isinstance(evidence, FileUseEvidence):
            return (
                judgment_rules.treat_shown_content_of_saved_file_as_assumed_content.__name__
                if evidence.file_use.kind == FileUseKind.SHOWS_CONTENT
                else judgment_rules.treat_file_use_that_may_not_have_happened_as_assumed_evidence.__name__
            )
        if isinstance(evidence, ExitCodeEvidence):
            return judgment_rules.treat_exit_code_meaning_as_assumed_level.__name__
        if _is_evidence_shared(evidence):
            return None
        return _RULES_OF_AN_OWN_LINE_IN_AN_ASSUMED_RESULT

    def _exit_code_answer_of(
        self, network_request: NetworkRequest, exit_code: int
    ) -> str:
        """Ask the own door what an exit code says of the program of a command request, `nothing or unknown` for no level."""
        source = network_request.source
        if not isinstance(source, FromCommand) or not isinstance(
            source.program_invocation, ProgramInvocation
        ):
            return "nothing or unknown"
        exit_code_meaning = self.own_knowledge.program_exit_code_meaning(
            source.program_invocation, exit_code
        )
        if isinstance(exit_code_meaning, ProgramExitCodeMeaning) and (
            exit_code_meaning != ProgramExitCodeMeaning.NOTHING
        ):
            return exit_code_meaning.value
        return "nothing or unknown"

    def _exit_code_rule_uses_of(
        self, result: NetworkRequestResult
    ) -> list[tuple[str, str, str]]:
        """List the exit code 0 evidence of a result whose door answer gives a level by `treat_exit_code_meaning_as_assumed_level`, by answer, program and subcommand."""
        source = result.network_request.source
        if not isinstance(source, FromCommand) or not isinstance(
            source.program_invocation, ProgramInvocation
        ):
            return []
        return [
            (
                answer,
                source.program_invocation.program_name,
                " ".join(source.program_invocation.subcommand_words),
            )
            for evidence in result.evidence
            if isinstance(evidence, ExitCodeEvidence)
            and evidence.exit_code == 0
            and (answer := self._exit_code_answer_of(result.network_request, 0))
            != "nothing or unknown"
        ]

    def _saved_file_uses_of(self, network_request: NetworkRequest) -> list[FileUse]:
        """List the uses of the file that a request saved what it received in, i.e. the written file of its call at the saved path that its command writes."""
        destination = network_request.received_content_destination
        source = network_request.source
        if (
            not isinstance(destination, ContentSaved)
            or not isinstance(source, FromCommand)
            or destination.path is None
        ):
            return []
        expanded_tool_call = self.expanded_tool_call_by_key[
            network_request.tool_call_key
        ]
        return [
            file_use
            for written_file in expanded_tool_call.written_files
            if written_file.path == destination.path
            and any(
                writer.command_id == source.command_id
                for writer in written_file.writers
            )
            for file_use in written_file.file_uses
        ]

    def _file_use_rule_conditions_of(self, network_request: NetworkRequest) -> set[str]:
        """Name each condition that makes a use of the saved file's content uncertain, as the uses of `treat_file_use_that_may_not_have_happened_as_assumed_evidence` are split, or `sure to have happened` for a use with none."""
        conditions: set[str] = set()
        for file_use in self._saved_file_uses_of(network_request):
            if file_use.kind != FileUseKind.USES_CONTENT:
                continue
            conditions_of_use = self._conditions_of_file_use(file_use)
            conditions |= conditions_of_use or {"sure to have happened"}
        return conditions

    def _conditions_of_file_use(self, file_use: FileUse) -> set[str]:
        """Name the conditions of `_file_use_rule_conditions_of` that hold for one use."""
        conditions: set[str] = set()
        if file_use.fits_several_written_files:
            conditions.add("fits several written files")
        using_expanded_tool_call = self.expanded_tool_call_by_key[
            file_use.using_tool_call_key
        ]
        ran_command = (
            None
            if file_use.command_id is None
            else _call_text_ran_command_of(
                using_expanded_tool_call, file_use.command_id
            )
        )
        if ran_command is None:
            conditions.add("using command not in the call's own text")
            return conditions
        shell_command = ran_command.shell_command
        if shell_command.in_function_body or shell_command.in_case_branch:
            conditions.add("in a function or case branch")
        if shell_command.structure_may_be_wrong:
            conditions.add("structure may be wrong")
        command_text_status = using_expanded_tool_call.command_text_status
        if (
            command_text_status is None
            or command_text_status.execution_status != ExecutionStatus.FINISHED
            or command_text_status.exit_code != 0
        ):
            conditions.add("text not finished with exit code 0")
        if not shell_command.succeeded_if_text_exits_zero:
            conditions.add(
                "does not exit 0 when its text does, with a run condition"
                if shell_command.runs_if
                else "does not exit 0 when its text does"
            )
        last_program_invocation = (
            ran_command.program_invocations[-1]
            if ran_command.program_invocations
            else None
        )
        if last_program_invocation is None:
            conditions.add("no program")
        elif not _do_outer_programs_end_with_exit_code_of_next(
            ran_command, last_program_invocation
        ):
            conditions.add("outer program")
        return conditions

    def _evidence_pairs_of(self, result: NetworkRequestResult) -> list[str]:
        """Name the pairs of evidence of a result that the report lists apart, i.e. an install line and a download start line of the same package without a download line, and a status 200 to 299 beside shown content."""
        evidence_pairs: list[str] = []
        own_lines = [
            evidence
            for evidence in result.evidence
            if isinstance(evidence, OutputLineEvidence)
            and not evidence.is_shared_with_other_requests
        ]
        package_names_by_kind: dict[OutputLineKind, set[str]] = {}
        for evidence in own_lines:
            output_line_meaning = self.output_line_meaning_by_place.get(
                (
                    evidence.showing_tool_call_key,
                    evidence.line_index,
                    evidence.line_index_in_json_string,
                )
            )
            package_names = (
                None
                if output_line_meaning is None
                or output_line_meaning.package_names_text is None
                else parse_package_names_text(output_line_meaning.package_names_text)
            )
            if isinstance(package_names, frozenset):
                package_names_by_kind.setdefault(evidence.kind, set()).update(
                    package_names
                )
        if package_names_by_kind.get(
            OutputLineKind.INSTALLED, set()
        ) & package_names_by_kind.get(
            OutputLineKind.DOWNLOAD_STARTED, set()
        ) and OutputLineKind.DOWNLOADED not in {
            evidence.kind
            for evidence in result.evidence
            if isinstance(evidence, OutputLineEvidence)
        }:
            evidence_pairs.append(
                "install line and download start line of one package without a download line"
            )
        has_success_status = any(
            (status_code := self._status_code_of_line(evidence)) is not None
            and 200 <= status_code <= 299
            for evidence in own_lines
        ) or any(
            isinstance(evidence, HttpStatusEvidence)
            and 200 <= evidence.http_status <= 299
            for evidence in result.evidence
        )
        if has_success_status and any(
            isinstance(evidence, ShownContentEvidence) for evidence in result.evidence
        ):
            evidence_pairs.append("status 200 to 299 beside shown content")
        return evidence_pairs

    def _has_shown_output(self, network_request: NetworkRequest) -> bool:
        """Tell whether the output of a request's run reaches a result, i.e. its command or the runner of its code has an output place and a route whose output is wholly or partly there at its end, or its web tool action is the action of its call, not a step of a tool script, and the call has a result text."""
        expanded_tool_call = self.expanded_tool_call_by_key[
            network_request.tool_call_key
        ]
        source = network_request.source
        if isinstance(source, FromWebTool):
            result = expanded_tool_call.tool_call.result
            return (
                source.step_index is None
                and result is not None
                and bool(result.tool_output_text)
            )
        command_id = (
            source.command_id
            if isinstance(source, FromCommand)
            else source.runner_command_id
        )
        if command_id is None or not any(
            command_id in output_place.command_ids
            for output_place in expanded_tool_call.output_places
        ):
            return False
        ran_command = _ran_command_by_id_of(expanded_tool_call, command_id)
        return ran_command is not None and any(
            route.visibility_at_end
            in (OutputVisibility.WHOLE, OutputVisibility.PARTIAL)
            for route in (*ran_command.stdout_routes, *ran_command.stderr_routes)
        )

    def count_unowned_output_lines(self) -> None:
        """List the unused lines by reason and kind, and the unowned ones also by the programs that reach their place."""
        trial_audit = self.trial_audit
        for (reason, kind), count in trial_audit.unused_output_line_counts.items():
            trial_audit.list_counts[
                _UNOWNED_OUTPUT_LINES, (reason.value, kind.value, "")
            ] += count
            if reason == UnusedOutputLineReason.UNOWNED_LINE_IN_UNKNOWN_RUN:
                trial_audit.has_unowned_line_in_unknown_run = True
        for (
            reason,
            kind,
            program_name,
        ), count in trial_audit.program_counts_of_unowned_output_lines.items():
            trial_audit.list_counts[
                _UNOWNED_OUTPUT_LINES,
                (reason.value, kind.value, program_name or "(no command)"),
            ] += count

    def count_trial(self) -> None:
        """Count the trial, whether it has a request and a received result, and each rule that keeps a result of it out of the lower bound, by whether another result of the trial is in it."""
        trial_audit = self.trial_audit
        trial_audit.count("trials")
        for column in sorted(trial_audit.received_trial_columns):
            trial_audit.count(f"trials {column}")
        has_result_in_lower_bound = any(
            _is_in_lower_bound(result) for result in self.network_request_results
        )
        for rule_name in trial_audit.rules_keeping_out_of_lower_bound:
            trial_audit.list_counts[
                _RULES_KEEPING_OUT_OF_LOWER_BOUND,
                (rule_name, "yes" if has_result_in_lower_bound else "no"),
            ] += 1


def _is_in_lower_bound(result: NetworkRequestResult) -> bool:
    """Tell whether a result is in the lower bound of what was received, i.e. a confirmed success of a request that is confirmed after the evidence."""
    success_level = (
        _REACHED
        if isinstance(
            result.network_request.received_content_destination, NoContentRequested
        )
        else _RECEIVED
    )
    return (
        (result.level, result.stop_reason) == (success_level, None)
        and result.level_certainty == _CONFIRMED
        and result.request_certainty_after_evidence == NetworkRequestCertainty.CONFIRMED
    )


def _is_evidence_shared(evidence: NetworkRequestResultEvidence) -> bool:
    """Tell whether a piece of evidence says that other requests share it, which shown content, an HTTP status and a file use never say."""
    return getattr(evidence, "is_shared_with_other_requests", False)


def _request_key_of(network_request: NetworkRequest) -> tuple[ToolCallKey, int]:
    return (network_request.tool_call_key, network_request.index_in_tool_call)


def _has_only_web_tool_actions(tool_call: ToolCall) -> bool:
    """Tell whether a call is made of web tool actions alone, also as the steps of a tool script, whose result the step reads as page text."""
    steps = [step for _, step in indexed_action_steps_of(tool_call.action)]
    return bool(steps) and all(isinstance(step, _WEB_TOOL_ACTIONS) for step in steps)


def _call_text_ran_command_of(
    expanded_tool_call: ExpandedToolCall, command_id: int
) -> RanCommand | None:
    """Find the command of a call's own text with an id, None when the id is of a command in a file, an argument or no shell text."""
    for ran_text in expanded_tool_call.ran_texts:
        if isinstance(ran_text, RanShellText) and isinstance(
            ran_text.source, CallCommandText
        ):
            for ran_command in ran_text.ran_commands:
                if ran_command.shell_command.id == command_id:
                    return ran_command
    return None


def _ran_command_by_id_of(
    expanded_tool_call: ExpandedToolCall, command_id: int
) -> RanCommand | None:
    for ran_text in expanded_tool_call.ran_texts:
        if isinstance(ran_text, RanShellText):
            for ran_command in ran_text.ran_commands:
                if ran_command.shell_command.id == command_id:
                    return ran_command
    return None


def _do_outer_programs_end_with_exit_code_of_next(
    ran_command: RanCommand,
    program_invocation: ProgramInvocation | UnknownProgramInvocation,
) -> bool:
    """Tell whether every program that runs before the given one in a command ends with the exit code of the next, e.g. sudo, and is no unknown program."""
    program_invocations = ran_command.program_invocations
    if program_invocation not in program_invocations:
        return False
    outer_program_invocations = program_invocations[
        : program_invocations.index(program_invocation)
    ]
    return all(
        isinstance(outer, ProgramInvocation)
        and outer.exits_with_exit_code_of_next_program is True
        for outer in outer_program_invocations
    )


def _means_of(network_request: NetworkRequest) -> tuple[str, str, str]:
    """Name what made a request, i.e. its program with subcommand and option names, the language of its code, or its web tool."""
    source = network_request.source
    if isinstance(source, FromWebTool):
        return (f"web tool {source.harness_tool.name}", "", "")
    if isinstance(source, FromCode):
        return (f"code {source.code_language.value}", "", "")
    program_invocation = source.program_invocation
    if isinstance(program_invocation, UnknownProgramInvocation):
        return (program_invocation.program_name, "", "(unknown program)")
    return (
        program_invocation.program_name,
        " ".join(program_invocation.subcommand_words),
        " ".join(sorted({option.name for option in program_invocation.options})),
    )


def _output_line_meaning_row_of(
    place: _LinePlace, output_line_meaning: OutputLineMeaning
) -> tuple[str, int, str, str, str, str, str]:
    """Give a row of `output_line_meanings.csv` without the trial id, with the host in lower case and the package names read by `parse_package_names_text`, sorted."""
    tool_call_key, line_index, line_index_in_json_string = place
    package_names_text = output_line_meaning.package_names_text
    package_names = (
        None
        if package_names_text is None
        else parse_package_names_text(package_names_text)
    )
    return (
        _text_of_tool_call_key(tool_call_key),
        line_index,
        "" if line_index_in_json_string is None else str(line_index_in_json_string),
        output_line_meaning.kind.value,
        (output_line_meaning.host_name_text or "").lower(),
        "unreadable"
        if isinstance(package_names, UnreadablePackageNamesText)
        else " ".join(sorted(package_names or ())),
        ""
        if output_line_meaning.status_code is None
        else str(output_line_meaning.status_code),
    )


def _text_of_tool_call_key(tool_call_key: ToolCallKey) -> str:
    return f"{tool_call_key.trajectory_id}:{tool_call_key.step_id}:{tool_call_key.call_index}"


if __name__ == "__main__":
    main()
