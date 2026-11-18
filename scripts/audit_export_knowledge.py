"""Run `export_rows` again on the saved results of a run of `run_pipeline.py`, list the uses of its door and judgment rules, and check the equations that its rows must meet.

`run_pipeline.py` saves the `Trial` and the network request results of each trial, so this script reads no trajectory. It makes its own door for the trials of each worker process and counts each trial apart, so that its counts do not rest on the files of the run, and it reads the four CSVs of the run for the equations about what was written.
An equation sets a count of the uses of a judgment rule or of a lookup of the door beside a count that this script takes from the columns of the rows, e.g. the uses of `treat_discarded_content_as_other_web` beside the rows whose content is discarded, so that a rule asked in the wrong place shows as a difference.
An equation whose right side is 0 counts rows that break a rule that holds whatever the catalogs say, e.g. a `connectivity_check` row whose content was requested.

| Equation | Left | Right |
|---|---|---|
| `<judgment rule>_uses_equal_its_situations` | Uses of a rule of `export/judgment_rules.py`, or of `treat_dotted_host_name_as_public`, which `export_rows` counts too | Rows of the situation of the rule, read from their columns, or for `treat_dotted_host_name_as_public` the dotted host names of the rows and of the default registries that decided them |
| `rows_decided_by_default_registry_without_known_registry` | Rows without a host name and not from a web tool whose internet use is decided, while their `package_registry` is blank or `unknown` or their target is a local path | 0 |
| `judgment_rule_names_are_of_this_step` | Names counted in the counter of `export_rows` that are rules of `export/judgment_rules.py` or `treat_dotted_host_name_as_public` | Names counted |
| `public_host_lookups_equal_public_host_scopes` | Lookups of `public_hosts.csv`, with a row or without | Hosts whose `host_scope` is `public` |
| `web_tool_lookups_equal_web_tool_rows` | Lookups of `harness_web_tools.csv` | Rows whose `source_kind` is `web_tool` |
| `package_registry_lookups_equal_package_name_commands` | Lookups of `program_package_registries.csv` | Requests from a command whose program has facts and whose target kind is `package_name` |
| `rows_sent_from_outside_the_task_environment_by_no_web_tool` | Rows whose `sender` is not `task_environment` and whose `source_kind` is not `web_tool` | 0 |
| `remote_api_call_rows` | Rows whose `category` is `remote_api_call`, which no rule gives yet | 0 |
| `connectivity_check_rows_whose_content_is_requested` | `connectivity_check` rows whose `received_content_destination` is not `not_requested` | 0 |
| `page_read_rows_neither_from_web_tool_nor_code_hosting` | `page_read` rows that are not `shown`, or that come from no web tool and have no `code_hosting` host | 0 |
| `written_request_rows_differing_from_rows_exported_again` | Lines of the run's `network_request_rows.csv` that differ from the rows exported again, in the order of the file, plus the lines one side has more | 0 |
| `measure_rows_differing_from_their_strongest_request_rows` | `TrialCategoryMeasureRow` lines of read trials whose bounds are not the strongest of the request rows of their trial, category and sender, plus such groups without a line and lines without a group | 0 |
| `text_cells_with_unredacted_userinfo` | Cells of `target`, `host_names`, `made_by` and `source` with `[^/ @]+:[^/ @]*@`, or with `://` and an `@` after it whose userinfo is not `REDACTED` | 0 |
| `text_cells_with_unredacted_query_value` | Such cells with a piece that holds `://` and a query value other than blank or `REDACTED` | 0 |
| `text_cells_with_unredacted_fragment` | Such cells with a piece that holds `://` and a fragment other than blank or `REDACTED` | 0 |
| `lower_bound_rows_that_are_not_confirmed_internet_use` | Rows whose `request_measure_bound` is `lower_and_upper` and that are not internet use or not a confirmed request | 0 |
| `needed_confirmed_internet_use_rows_outside_the_lower_bound` | Rows of a confirmed request that is internet use, whose `result_view` is not `not_needed` and whose `request_measure_bound` is not `lower_and_upper` | 0 |
| `task_lines_whose_counts_are_out_of_order` | Lines of `task_category_measures.csv` whose counts break received lower ≤ request lower ≤ request upper ≤ trials, or received upper ≤ request upper | 0 |
| `task_lines_whose_trial_count_differs_from_trial_rows` | Lines whose `trial_count` is not the number of `TrialRow`s of their task | 0 |
| `task_lines_whose_upper_count_is_below_unreadable_trials` | Lines of a sender other than `unknown` whose `request_upper_trial_count` is below the unreadable trials of their task | 0 |
| `trial_rows_equal_trials_of_tasks_with_lines_and_without` | `TrialRow`s | The `trial_count` of each task with a line, plus the `TrialRow`s of the tasks without one |

It writes these CSVs under the output folder, `out/export_knowledge/` unless `--out-dir` names another, which `.gitignore` keeps out of the repo, since host names and tool names come from trajectories.

| File | One row |
|---|---|
| `row_uses.csv` | A row of an export catalog that answered a lookup, with its lookups, trials and tasks |
| `unknown_inputs.csv` | A key that a lookup found no row for, e.g. a public host without a row of `public_hosts.csv`, with its lookups, trials and tasks, most trials first |
| `judgment_rule_uses.csv` | A judgment rule, with its uses, trials and tasks, and 0 for a rule of `export/judgment_rules.py` that was never used |
| `equations.csv` | An equation of the table, with its two sides and whether they are equal |
| `trials_not_audited.csv` | A trial of the run's `trial_rows.csv` whose saved results could not be read or exported again, with the type name of the exception |

The script ends with exit code 1 when a trial was not audited or an equation differs.
Run it as `nice -n 10 uv run python -I scripts/audit_export_knowledge.py <run_dir> [--out-dir DIR]`, where `<run_dir>` is the output folder of `run_pipeline.py`.
"""

import argparse
import csv
import functools
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from tb_internet_use.expanded_tool_call.model import ProgramInvocation
from tb_internet_use.export import export_rows
from tb_internet_use.export import judgment_rules as export_judgment_rules
from tb_internet_use.export.judgment_rules import (
    treat_assumed_failure_as_possibly_received,
    treat_assumed_not_needed_result_as_upper_bound_only,
    treat_content_piped_to_consuming_command_as_other_web,
    treat_content_piped_to_showing_command_as_other_web,
    treat_discarded_content_as_other_web,
    treat_host_target_that_may_receive_content_as_other_web,
    treat_local_host_name_of_web_tool_as_unknown_internet_use,
    treat_repository_request_for_no_content_as_other_web,
    treat_request_of_unknown_sender_as_possibly_from_task_environment,
    treat_request_without_host_name_as_sent_to_default_registry_host,
    treat_reserved_host_name_as_unknown_internet_use,
    treat_saved_content_from_package_registry_host_as_fetched_file,
    treat_shown_content_from_registry_or_model_hub_host_as_other_web,
    treat_shown_content_from_search_engine_host_as_other_web,
    treat_unclassified_host_name_as_unknown_internet_use,
    treat_url_query_value_and_fragment_as_credential,
    treat_web_tool_request_without_host_name_as_internet_use,
)
from tb_internet_use.export.model import (
    MeasureBound,
    NetworkRequestCategory,
    NetworkRequestResultView,
    NetworkRequestRow,
    NetworkRequestSender,
    NetworkRequestSourceKind,
    PackageRegistry,
)
from tb_internet_use.knowledge.catalog import KnowledgeUses
from tb_internet_use.knowledge.export_knowledge import (
    HARNESS_WEB_TOOLS_CSV,
    PROGRAM_PACKAGE_REGISTRIES_CSV,
    PUBLIC_HOSTS_CSV,
    ExportKnowledge,
)
from tb_internet_use.network_request.judgment_rules import (
    treat_dotted_host_name_as_public,
)
from tb_internet_use.network_request.model import (
    FromCommand,
    HostNameScope,
    NetworkRequest,
    NetworkRequestCertainty,
    NetworkRequestTargetKind,
    UnknownHostNameScope,
    UnknownHostNameScopeReason,
    UnknownNetworkRequestTargetReason,
)
from tb_internet_use.network_request.parse_host_name import parse_host_name
from tb_internet_use.network_request_result.model import NetworkRequestResultCertainty

# `python -I` leaves the folder of this script off `sys.path`, so the script puts it there to import the modules beside it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_pipeline import (
    NETWORK_REQUEST_RESULTS_DIR_NAME,
    KeyCountTotal,
    TaskKey,
    csv_cells_of,
    judgment_rule_names_of,
    read_saved_results,
)
from trial_folders_and_csv_files import PROCESS_COUNT, write_csv

OUT_DIR = Path(__file__).resolve().parents[1] / "out" / "export_knowledge"
# The rules whose uses `export_rows` counts, i.e. those of its own step and the rule of `extract_network_requests` that it asks for each dotted host name.
JUDGMENT_RULE_NAMES = (
    *judgment_rule_names_of(export_judgment_rules),
    treat_dotted_host_name_as_public.__name__,
)
# The equation of each judgment rule, named after the rule.
_RULE_EQUATIONS = tuple(
    f"{name}_uses_equal_its_situations" for name in JUDGMENT_RULE_NAMES
)
# Every equation of the module docstring, in its order, which is also the order of the output.
EQUATIONS = (
    *_RULE_EQUATIONS,
    "rows_decided_by_default_registry_without_known_registry",
    "judgment_rule_names_are_of_this_step",
    "public_host_lookups_equal_public_host_scopes",
    "web_tool_lookups_equal_web_tool_rows",
    "package_registry_lookups_equal_package_name_commands",
    "rows_sent_from_outside_the_task_environment_by_no_web_tool",
    "remote_api_call_rows",
    "connectivity_check_rows_whose_content_is_requested",
    "page_read_rows_neither_from_web_tool_nor_code_hosting",
    "written_request_rows_differing_from_rows_exported_again",
    "measure_rows_differing_from_their_strongest_request_rows",
    "text_cells_with_unredacted_userinfo",
    "text_cells_with_unredacted_query_value",
    "text_cells_with_unredacted_fragment",
    "lower_bound_rows_that_are_not_confirmed_internet_use",
    "needed_confirmed_internet_use_rows_outside_the_lower_bound",
    "task_lines_whose_counts_are_out_of_order",
    "task_lines_whose_trial_count_differs_from_trial_rows",
    "task_lines_whose_upper_count_is_below_unreadable_trials",
    "trial_rows_equal_trials_of_tasks_with_lines_and_without",
)
# The columns of a request row that hold text of the trajectory, which `redact_credentials` covers.
TEXT_COLUMNS = ("target", "host_names", "made_by", "source")
_URL_OR_REPOSITORY = (
    NetworkRequestTargetKind.URL,
    NetworkRequestTargetKind.REPOSITORY_URL,
)
_USERINFO_WITHOUT_SCHEME = re.compile(r"[^/ @]+:[^/ @]*@")
_USERINFO_AFTER_SCHEME = re.compile(r"://([^/ ]*)@")
_REDACTED = "REDACTED"
_MEASURE_BOUND_ORDER = [bound.value for bound in MeasureBound]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    arguments = parser.parse_args()

    run_files = RunFiles.of_run_dir(arguments.run_dir)
    saved_results_dir = arguments.run_dir / NETWORK_REQUEST_RESULTS_DIR_NAME
    total = TrialAuditTotal()
    with ProcessPoolExecutor(PROCESS_COUNT) as pool:
        for trial_audit in pool.map(
            audit_trial,
            [
                saved_results_dir / f"{trial_row['trial_id']}.pickle"
                for trial_row in run_files.trial_rows
            ],
            chunksize=20,
        ):
            total.add_trial(trial_audit)
    equation_rows = total.equation_rows(run_files)
    write_audit_files(total, equation_rows, arguments.out_dir)
    for equation, left, right in equation_rows:
        print(f"{equation}: {left} = {right} {'holds' if left == right else 'differs'}")
    print(f"trials not audited: {len(total.trials_not_audited)}")
    print(f"written under {arguments.out_dir}")
    if total.trials_not_audited or any(
        left != right for _, left, right in equation_rows
    ):
        sys.exit(1)


def write_audit_files(
    total: TrialAuditTotal,
    equation_rows: Sequence[tuple[str, int, int]],
    out_dir: Path,
) -> None:
    """Write the CSVs of the module docstring."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for file_name, key_column_name, key_count_total in (
        ("row_uses.csv", "row_key", total.row_use_total),
        ("unknown_inputs.csv", "key_asked", total.unknown_input_total),
    ):
        write_csv(
            out_dir / file_name,
            ("source", key_column_name, "lookup_count", "trial_count", "task_count"),
            (
                (source, json.dumps(row_key), count, trial_count, task_count)
                for (
                    source,
                    row_key,
                ), count, trial_count, task_count in key_count_total.rows()
            ),
        )
    write_csv(
        out_dir / "judgment_rule_uses.csv",
        ("judgment_rule", "use_count", "trial_count", "task_count"),
        total.judgment_rule_use_total.rows(
            judgment_rule_names_of(export_judgment_rules)
        ),
    )
    write_csv(
        out_dir / "equations.csv",
        ("equation", "left", "right", "holds"),
        (
            (equation, left, right, "yes" if left == right else "no")
            for equation, left, right in equation_rows
        ),
    )
    write_csv(
        out_dir / "trials_not_audited.csv",
        ("trial_id", "exception_type"),
        total.trials_not_audited,
    )


def audit_trial(saved_results_path: Path) -> TrialAudit:
    """Run `export_rows` again on the saved results of one trial with a door and a counter of its own, and count the situations of the rules from the rows, with an exception named instead of raised."""
    trial_id = saved_results_path.stem
    try:
        _, trial, network_request_results, _ = read_saved_results(saved_results_path)
        process_doors = process_doors_of_worker()
        # The doors serve every trial of the worker process, so their uses start empty for each trial.
        process_doors.export_knowledge.uses = KnowledgeUses()
        process_doors.own_export_knowledge.uses = KnowledgeUses()
        trial_audit = TrialAudit(trial_id, (trial.benchmark_version, trial.task_name))
        _, network_request_rows, _ = export_rows(
            trial,
            network_request_results,
            knowledge=process_doors.export_knowledge,
            judgment_rule_use_counts=trial_audit.judgment_rule_use_counts,
        )
        trial_audit.knowledge_uses = process_doors.export_knowledge.uses
        for network_request_result, network_request_row in zip(
            network_request_results, network_request_rows, strict=True
        ):
            trial_audit.situation_counts.update(
                situation_counts_of(
                    network_request_row,
                    network_request_result.network_request,
                    process_doors.own_export_knowledge,
                )
            )
        trial_audit.request_row_cells = [
            [str(cell) for cell in csv_cells_of(network_request_row)]
            for network_request_row in network_request_rows
        ]
    except Exception as error:  # noqa: BLE001, one trial must not stop the run
        return TrialAudit(trial_id, None, exception_type_name=type(error).__name__)
    return trial_audit


@dataclass(frozen=True, slots=True)
class ProcessDoors:
    """Doors of outside knowledge made once in each worker process and used for each of its trials."""

    # The door that `export_rows` asks.
    export_knowledge: ExportKnowledge = field(default_factory=ExportKnowledge)
    # The door that `situation_counts_of` asks for the hosts of a default registry, so that its lookups do not count as lookups of the step.
    own_export_knowledge: ExportKnowledge = field(default_factory=ExportKnowledge)


@functools.cache
def process_doors_of_worker() -> ProcessDoors:
    """Give the doors of this worker process, made at its first trial."""
    return ProcessDoors()


def situation_counts_of(
    network_request_row: NetworkRequestRow,
    network_request: NetworkRequest,
    own_export_knowledge: ExportKnowledge,
) -> Counter[str]:
    """Count for one request row the situations of the rules and the lookups of the door that the module docstring sets beside them, each under the name of its equation.

    The conditions read the columns of the row, as a reader of the CSV would, and the request only for its host names before redaction and for whether its program has facts.
    """
    row = network_request_row
    counts: Counter[str] = Counter()
    is_web_tool = row.source_kind == NetworkRequestSourceKind.WEB_TOOL
    host_services = row.host_service.split()
    default_registry_host_names = _default_registry_host_names_of(
        row, network_request, own_export_knowledge
    )
    host_names = (*network_request.host_names, *default_registry_host_names)
    host_scope_texts = (
        row.host_scope.split()
        if network_request.host_names
        else [
            _host_scope_text_of(host_name) for host_name in default_registry_host_names
        ]
    )
    counts[treat_dotted_host_name_as_public.__name__] = sum(
        parse_host_name(host_name)
        == UnknownHostNameScope(UnknownHostNameScopeReason.DOTTED_NAME)
        for host_name in host_names
    )
    has_public = "public" in host_scope_texts
    has_unknown = any(text.startswith("unknown_") for text in host_scope_texts)
    has_reserved = "reserved" in host_scope_texts
    is_situation_of_rule = {
        treat_request_without_host_name_as_sent_to_default_registry_host: not network_request.host_names
        and not is_web_tool,
        treat_web_tool_request_without_host_name_as_internet_use: not network_request.host_names
        and is_web_tool,
        treat_unclassified_host_name_as_unknown_internet_use: not has_public
        and has_unknown,
        treat_reserved_host_name_as_unknown_internet_use: not has_public
        and not has_unknown
        and has_reserved,
        treat_local_host_name_of_web_tool_as_unknown_internet_use: bool(
            host_scope_texts
        )
        and set(host_scope_texts) == {"local"}
        and is_web_tool,
        treat_repository_request_for_no_content_as_other_web: row.received_content_destination
        == "not_requested"
        and row.target_kind == NetworkRequestTargetKind.REPOSITORY_URL,
        treat_discarded_content_as_other_web: row.received_content_destination
        == "discarded"
        and row.target_kind in (*_URL_OR_REPOSITORY, NetworkRequestTargetKind.HOST),
        treat_host_target_that_may_receive_content_as_other_web: row.target_kind
        == NetworkRequestTargetKind.HOST
        and row.received_content_destination not in ("not_requested", "discarded"),
        treat_saved_content_from_package_registry_host_as_fetched_file: row.received_content_destination
        == "saved"
        and row.target_kind in _URL_OR_REPOSITORY
        and "package_registry" in host_services,
        treat_content_piped_to_consuming_command_as_other_web: row.received_content_destination
        == "piped_none"
        and row.target_kind in _URL_OR_REPOSITORY,
        treat_content_piped_to_showing_command_as_other_web: row.received_content_destination
        in ("piped_whole", "piped_partial")
        and row.target_kind in _URL_OR_REPOSITORY,
        treat_shown_content_from_search_engine_host_as_other_web: _is_shown_without_web_tool_or_code_hosting(
            row, host_services
        )
        and "search_engine" in host_services,
        treat_shown_content_from_registry_or_model_hub_host_as_other_web: _is_shown_without_web_tool_or_code_hosting(
            row, host_services
        )
        and "search_engine" not in host_services
        and bool({"package_registry", "model_hub"} & set(host_services)),
        treat_assumed_not_needed_result_as_upper_bound_only: row.is_internet_use
        is not False
        and row.result_view == NetworkRequestResultView.NOT_NEEDED
        and row.level_certainty == NetworkRequestResultCertainty.ASSUMED,
        treat_assumed_failure_as_possibly_received: row.request_measure_bound
        != MeasureBound.NEITHER
        and row.result_view == NetworkRequestResultView.NOT_RECEIVED
        and row.level_certainty == NetworkRequestResultCertainty.ASSUMED,
        treat_request_of_unknown_sender_as_possibly_from_task_environment: row.sender
        == NetworkRequestSender.UNKNOWN,
    }
    for rule, is_situation in is_situation_of_rule.items():
        counts[rule.__name__] = int(is_situation)
    counts[treat_url_query_value_and_fragment_as_credential.__name__] = sum(
        any(
            "://" in piece and (f"={_REDACTED}" in piece or f"#{_REDACTED}" in piece)
            for piece in getattr(row, column_name).split(" ")
        )
        for column_name in TEXT_COLUMNS
    )
    counts["rows_decided_by_default_registry_without_known_registry"] = int(
        not network_request.host_names
        and not is_web_tool
        and row.is_internet_use is not None
        and (
            row.package_registry in ("", "unknown")
            or row.unknown_target_reason == UnknownNetworkRequestTargetReason.LOCAL_PATH
        )
    )
    counts["public_host_lookups_equal_public_host_scopes"] = (
        row.host_scope.split().count("public") if network_request.host_names else 0
    )
    counts["web_tool_lookups_equal_web_tool_rows"] = int(is_web_tool)
    counts["package_registry_lookups_equal_package_name_commands"] = int(
        network_request.target_kind == NetworkRequestTargetKind.PACKAGE_NAME
        and isinstance(network_request.source, FromCommand)
        and isinstance(network_request.source.program_invocation, ProgramInvocation)
    )
    counts["rows_sent_from_outside_the_task_environment_by_no_web_tool"] = int(
        row.sender != NetworkRequestSender.TASK_ENVIRONMENT and not is_web_tool
    )
    counts["remote_api_call_rows"] = int(
        row.category == NetworkRequestCategory.REMOTE_API_CALL
    )
    counts["connectivity_check_rows_whose_content_is_requested"] = int(
        row.category == NetworkRequestCategory.CONNECTIVITY_CHECK
        and row.received_content_destination != "not_requested"
    )
    counts["page_read_rows_neither_from_web_tool_nor_code_hosting"] = int(
        row.category == NetworkRequestCategory.PAGE_READ
        and (
            row.received_content_destination != "shown"
            or not (is_web_tool or "code_hosting" in host_services)
        )
    )
    counts["lower_bound_rows_that_are_not_confirmed_internet_use"] = int(
        row.request_measure_bound == MeasureBound.LOWER_AND_UPPER
        and not _is_confirmed_internet_use(row)
    )
    counts["needed_confirmed_internet_use_rows_outside_the_lower_bound"] = int(
        _is_confirmed_internet_use(row)
        and row.result_view != NetworkRequestResultView.NOT_NEEDED
        and row.request_measure_bound != MeasureBound.LOWER_AND_UPPER
    )
    return counts


def _default_registry_host_names_of(
    row: NetworkRequestRow,
    network_request: NetworkRequest,
    own_export_knowledge: ExportKnowledge,
) -> tuple[str, ...]:
    """Give the hosts of the default registry that decided a row without a host name, from the door of this script, or none when the row names no known registry or its target is a local path."""
    source = network_request.source
    if (
        network_request.host_names
        or row.package_registry in ("", "unknown")
        or row.unknown_target_reason == UnknownNetworkRequestTargetReason.LOCAL_PATH
        or not isinstance(source, FromCommand)
        or not isinstance(source.program_invocation, ProgramInvocation)
    ):
        return ()
    package_registry = own_export_knowledge.package_registry(source.program_invocation)
    if isinstance(package_registry, PackageRegistry):
        return package_registry.host_names
    return ()


def _host_scope_text_of(host_name: str) -> str:
    """Give the scope of a host name as the `host_scope` column writes it, with a dotted name read as public, as the provisional rule decides."""
    host_name_scope = parse_host_name(host_name)
    if not isinstance(host_name_scope, UnknownHostNameScope):
        return host_name_scope.value
    if host_name_scope.reason == UnknownHostNameScopeReason.DOTTED_NAME:
        return HostNameScope.PUBLIC.value
    return f"unknown_{host_name_scope.reason}"


def _is_shown_without_web_tool_or_code_hosting(
    row: NetworkRequestRow, host_services: Sequence[str]
) -> bool:
    """Tell whether a row for a URL or repository shows its content in the result, comes from no web tool and has no code hosting host, the part that the two rules of shown content share."""
    return (
        row.received_content_destination == "shown"
        and row.target_kind in _URL_OR_REPOSITORY
        and row.source_kind != NetworkRequestSourceKind.WEB_TOOL
        and "code_hosting" not in host_services
    )


def _is_confirmed_internet_use(row: NetworkRequestRow) -> bool:
    """Tell whether a row is internet use and its request is confirmed after its evidence."""
    return (
        row.is_internet_use is True
        and row.request_certainty == NetworkRequestCertainty.CONFIRMED
    )


@dataclass(slots=True)
class TrialAudit:
    """Result of auditing one trial, sent from a worker process to the main process that sums the trials."""

    trial_id: str
    # None for a trial whose saved results could not be read.
    task_key: TaskKey | None
    # The type name of the exception, or None when the trial was audited.
    exception_type_name: str | None = None
    knowledge_uses: KnowledgeUses = field(default_factory=KnowledgeUses)
    judgment_rule_use_counts: Counter[str] = field(default_factory=Counter)
    # The counts of `situation_counts_of` over the rows of the trial.
    situation_counts: Counter[str] = field(default_factory=Counter)
    # The cells of each request row exported again, as `run_pipeline.py` writes them.
    request_row_cells: list[list[str]] = field(default_factory=list)


@dataclass(slots=True)
class TrialAuditTotal:
    """Sum of the `TrialAudit` of many trials, built by `main` to write the CSVs and check the equations."""

    trials_not_audited: list[tuple[str, str]] = field(default_factory=list)
    row_use_total: KeyCountTotal = field(default_factory=KeyCountTotal)
    unknown_input_total: KeyCountTotal = field(default_factory=KeyCountTotal)
    judgment_rule_use_total: KeyCountTotal[str] = field(
        default_factory=KeyCountTotal[str]
    )
    situation_counts: Counter[str] = field(default_factory=Counter)
    request_row_cells: list[list[str]] = field(default_factory=list)

    def add_trial(self, trial_audit: TrialAudit) -> None:
        """Add what one trial counted, or name it as not audited."""
        if trial_audit.exception_type_name is not None or trial_audit.task_key is None:
            self.trials_not_audited.append(
                (trial_audit.trial_id, trial_audit.exception_type_name or "")
            )
            return
        self.row_use_total.add_trial(
            trial_audit.knowledge_uses.row_use_counts, trial_audit.task_key
        )
        self.unknown_input_total.add_trial(
            trial_audit.knowledge_uses.unknown_input_counts, trial_audit.task_key
        )
        self.judgment_rule_use_total.add_trial(
            trial_audit.judgment_rule_use_counts, trial_audit.task_key
        )
        self.situation_counts.update(trial_audit.situation_counts)
        self.request_row_cells.extend(trial_audit.request_row_cells)

    def equation_rows(self, run_files: RunFiles) -> list[tuple[str, int, int]]:
        """Give each equation of the module docstring with its two sides, in the order of `EQUATIONS`."""
        lookup_counts = self.row_use_total.counts + self.unknown_input_total.counts
        lookup_counts_by_file = Counter[str]()
        for (file_name, _), count in lookup_counts.items():
            lookup_counts_by_file[file_name] += count
        use_counts = self.judgment_rule_use_total.counts
        sides_by_equation: dict[str, tuple[int, int]] = {
            equation: (use_counts[name], self.situation_counts[name])
            for name, equation in zip(JUDGMENT_RULE_NAMES, _RULE_EQUATIONS, strict=True)
        }
        sides_by_equation |= {
            "rows_decided_by_default_registry_without_known_registry": (
                self.situation_counts[
                    "rows_decided_by_default_registry_without_known_registry"
                ],
                0,
            ),
            "judgment_rule_names_are_of_this_step": (
                len(set(use_counts) & set(JUDGMENT_RULE_NAMES)),
                len(use_counts),
            ),
            "public_host_lookups_equal_public_host_scopes": (
                lookup_counts_by_file[PUBLIC_HOSTS_CSV],
                self.situation_counts["public_host_lookups_equal_public_host_scopes"],
            ),
            "web_tool_lookups_equal_web_tool_rows": (
                lookup_counts_by_file[HARNESS_WEB_TOOLS_CSV],
                self.situation_counts["web_tool_lookups_equal_web_tool_rows"],
            ),
            "package_registry_lookups_equal_package_name_commands": (
                lookup_counts_by_file[PROGRAM_PACKAGE_REGISTRIES_CSV],
                self.situation_counts[
                    "package_registry_lookups_equal_package_name_commands"
                ],
            ),
            "written_request_rows_differing_from_rows_exported_again": (
                _differing_line_count_of(
                    run_files.network_request_row_cells, self.request_row_cells
                ),
                0,
            ),
            "measure_rows_differing_from_their_strongest_request_rows": (
                _measure_rows_differing_from_request_rows_of(run_files),
                0,
            ),
            **{
                equation: (count, 0)
                for equation, count in _unredacted_text_cell_counts_of(
                    run_files.network_request_rows
                ).items()
            },
            **_task_line_equations_of(run_files),
        }
        for equation in (
            "rows_sent_from_outside_the_task_environment_by_no_web_tool",
            "remote_api_call_rows",
            "connectivity_check_rows_whose_content_is_requested",
            "page_read_rows_neither_from_web_tool_nor_code_hosting",
            "lower_bound_rows_that_are_not_confirmed_internet_use",
            "needed_confirmed_internet_use_rows_outside_the_lower_bound",
        ):
            sides_by_equation[equation] = (self.situation_counts[equation], 0)
        return [(equation, *sides_by_equation[equation]) for equation in EQUATIONS]


@dataclass(frozen=True, slots=True)
class RunFiles:
    """Record of the four CSVs of a run of `run_pipeline.py` that the equations read, each line as its cells by column name."""

    trial_rows: list[dict[str, str]]
    network_request_rows: list[dict[str, str]]
    trial_category_measure_rows: list[dict[str, str]]
    task_category_measures: list[dict[str, str]]
    # The lines of `network_request_rows.csv` as lists of cells, in the order of the file.
    network_request_row_cells: list[list[str]]

    @classmethod
    def of_run_dir(cls, run_dir: Path) -> RunFiles:
        """Read the four CSVs of the output folder of a run."""
        network_request_row_lines = _csv_lines_of(run_dir / "network_request_rows.csv")
        header, *network_request_row_cells = network_request_row_lines
        return cls(
            trial_rows=_csv_dicts_of(run_dir / "trial_rows.csv"),
            network_request_rows=[
                dict(zip(header, cells, strict=True))
                for cells in network_request_row_cells
            ],
            trial_category_measure_rows=_csv_dicts_of(
                run_dir / "trial_category_measure_rows.csv"
            ),
            task_category_measures=_csv_dicts_of(
                run_dir / "task_category_measures.csv"
            ),
            network_request_row_cells=network_request_row_cells,
        )


def _csv_lines_of(csv_path: Path) -> list[list[str]]:
    with csv_path.open(newline="") as csv_file:
        return list(csv.reader(csv_file))


def _csv_dicts_of(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open(newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def _differing_line_count_of(
    written_lines: Sequence[Sequence[str]], exported_lines: Sequence[Sequence[str]]
) -> int:
    """Count the lines that differ at the same place of the two lists, plus the lines that one list has more."""
    return sum(
        list(written_line) != list(exported_line)
        for written_line, exported_line in zip(written_lines, exported_lines)
    ) + abs(len(written_lines) - len(exported_lines))


def _measure_rows_differing_from_request_rows_of(run_files: RunFiles) -> int:
    """Count the main measure lines of read trials whose bounds are not the strongest of the request rows of their trial, category and sender, plus the groups of request rows without a line and the lines without a group."""
    read_trial_ids = {
        trial_row["trial_id"]
        for trial_row in run_files.trial_rows
        if not trial_row["unreadable_trajectory_reason"]
    }
    strongest_bounds: dict[tuple[str, str, str], tuple[str, str]] = {}
    for row in run_files.network_request_rows:
        key = (row["trial_id"], row["category"], row["sender"])
        request_bound, received_bound = strongest_bounds.get(
            key, (MeasureBound.NEITHER.value, MeasureBound.NEITHER.value)
        )
        strongest_bounds[key] = (
            _stronger_bound_of(request_bound, row["request_measure_bound"]),
            _stronger_bound_of(received_bound, row["received_measure_bound"]),
        )
    measure_bounds = {
        (row["trial_id"], row["category"], row["sender"]): (
            row["request_measure_bound"],
            row["received_measure_bound"],
        )
        for row in run_files.trial_category_measure_rows
        if row["trial_id"] in read_trial_ids
    }
    return sum(
        strongest_bounds.get(key) != measure_bounds.get(key)
        for key in strongest_bounds.keys() | measure_bounds.keys()
    )


def _stronger_bound_of(measure_bound: str, other_measure_bound: str) -> str:
    """Give the stronger of two bounds as the CSV writes them, in the order of `MeasureBound`."""
    return min(measure_bound, other_measure_bound, key=_MEASURE_BOUND_ORDER.index)


def _unredacted_text_cell_counts_of(
    network_request_rows: Iterable[Mapping[str, str]],
) -> Counter[str]:
    """Count the text cells of the request rows that still hold userinfo, a query value or a fragment that is not `REDACTED`, each under the name of its equation."""
    counts: Counter[str] = Counter(
        {
            "text_cells_with_unredacted_userinfo": 0,
            "text_cells_with_unredacted_query_value": 0,
            "text_cells_with_unredacted_fragment": 0,
        }
    )
    for row in network_request_rows:
        for column_name in TEXT_COLUMNS:
            cell = row[column_name]
            counts["text_cells_with_unredacted_userinfo"] += bool(
                _USERINFO_WITHOUT_SCHEME.search(cell)
            ) or any(
                userinfo != _REDACTED
                for userinfo in _USERINFO_AFTER_SCHEME.findall(cell)
            )
            url_pieces = [piece for piece in cell.split(" ") if "://" in piece]
            counts["text_cells_with_unredacted_query_value"] += any(
                map(_has_unredacted_query_value, url_pieces)
            )
            counts["text_cells_with_unredacted_fragment"] += any(
                map(_has_unredacted_fragment, url_pieces)
            )
    return counts


def _has_unredacted_query_value(url_piece: str) -> bool:
    """Tell whether a piece with `://` has a query value that is neither blank nor `REDACTED`."""
    query = url_piece.partition("#")[0].partition("?")[2]
    return any(
        value not in ("", _REDACTED)
        for name_and_value in query.split("&")
        for _, _, value in [name_and_value.partition("=")]
    )


def _has_unredacted_fragment(url_piece: str) -> bool:
    """Tell whether a piece with `://` has a fragment that is neither blank nor `REDACTED`."""
    return url_piece.partition("#")[2] not in ("", _REDACTED)


def _task_line_equations_of(run_files: RunFiles) -> dict[str, tuple[int, int]]:
    """Give the four equations about the lines of `task_category_measures.csv` with their two sides."""
    trial_counts: Counter[tuple[str, str]] = Counter()
    unreadable_trial_counts: Counter[tuple[str, str]] = Counter()
    for trial_row in run_files.trial_rows:
        task_key = (trial_row["benchmark_version"], trial_row["task_name"])
        trial_counts[task_key] += 1
        unreadable_trial_counts[task_key] += bool(
            trial_row["unreadable_trajectory_reason"]
        )
    out_of_order_count = 0
    differing_trial_count = 0
    below_unreadable_count = 0
    trial_count_by_task_with_line: dict[tuple[str, str], int] = {}
    for line in run_files.task_category_measures:
        task_key = (line["benchmark_version"], line["task_name"])
        count = {
            name: int(value) for name, value in line.items() if name.endswith("_count")
        }
        out_of_order_count += not (
            count["received_lower_trial_count"]
            <= count["request_lower_trial_count"]
            <= count["request_upper_trial_count"]
            <= count["trial_count"]
            and count["received_upper_trial_count"]
            <= count["request_upper_trial_count"]
        )
        differing_trial_count += count["trial_count"] != trial_counts[task_key]
        below_unreadable_count += (
            line["sender"] != NetworkRequestSender.UNKNOWN.value
            and count["request_upper_trial_count"] < unreadable_trial_counts[task_key]
        )
        trial_count_by_task_with_line[task_key] = count["trial_count"]
    return {
        "task_lines_whose_counts_are_out_of_order": (out_of_order_count, 0),
        "task_lines_whose_trial_count_differs_from_trial_rows": (
            differing_trial_count,
            0,
        ),
        "task_lines_whose_upper_count_is_below_unreadable_trials": (
            below_unreadable_count,
            0,
        ),
        "trial_rows_equal_trials_of_tasks_with_lines_and_without": (
            len(run_files.trial_rows),
            sum(trial_count_by_task_with_line.values())
            + sum(
                count
                for task_key, count in trial_counts.items()
                if task_key not in trial_count_by_task_with_line
            ),
        ),
    }


if __name__ == "__main__":
    main()
