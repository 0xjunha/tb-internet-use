"""Decide the evidence of one network request, each piece with the level and stop reason that it shows, from its own output lines, the run of its command and the later sight of what it received.

A request is judged by its own evidence only. A line counts for it only when it owns the line, e.g. `Successfully installed x-1.0` under `pip install x`, and whether a command ran is read from the exit code of the call's text only where that code belongs to the command, e.g. for both commands of `cd /app && pip install x` that ended with exit 0, but not for `curl -s u` in `curl -s u | tar xz`.
A request that saved what it received gets evidence from a later use of the file, e.g. `tar xzf a.tgz` after `curl -s -o a.tgz u`, since its own output often shows nothing.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from tb_internet_use.expanded_tool_call.model import (
    CallCommandText,
    ExpandedToolCall,
    FileUse,
    FileUseKind,
    ProgramInvocation,
    RanCommand,
    RanShellText,
    UnknownProgramInvocation,
    WrittenFile,
)
from tb_internet_use.network_request.model import (
    ContentSaved,
    ContentShownInResult,
    FromCommand,
    FromWebTool,
    NetworkRequest,
    NetworkRequestTargetKind,
    NoContentRequested,
)
from tb_internet_use.network_request_result import judgment_rules
from tb_internet_use.network_request_result._decide_output_line_owners import (
    command_id_of_network_request,
    has_unknown_run_beside,
    is_missing_program_of_command,
    network_requests_of_output_place,
    program_output_lines_of,
    ran_commands_of,
    stopped_command_ids_from_missing_program_line,
    stopping_command_ids_of,
)
from tb_internet_use.network_request_result.model import (
    EvidenceWithLevel,
    ExecutionStatusEvidence,
    ExitCodeEvidence,
    FileUseEvidence,
    HttpStatusEvidence,
    JudgmentRuleAssumptionReason,
    MissingProgramOfAnotherCommandAssumptionReason,
    NetworkRequestResultAssumptionReason,
    NetworkRequestResultLevel,
    NetworkRequestResultStopReason,
    OutputLineEvidence,
    OutputLineKind,
    OutputLineMeaning,
    OutputLineOwners,
    OutputPlaceSources,
    PrintingProgram,
    ProgramExitCodeMeaning,
    SharedFileUseAssumptionReason,
    SharedHttpStatusAssumptionReason,
    SharedOutputLineAssumptionReason,
    ShownContentEvidence,
    UnknownProgramOutputLines,
    UnknownProgramOutputLinesAssumptionReason,
    UnknownRunBesideAssumptionReason,
    UnreadablePackageNamesText,
)
from tb_internet_use.network_request_result.parse_package_names_text import (
    parse_package_names_text,
)
from tb_internet_use.tool_call.model import (
    ExecutionStatus,
    ExitOutcome,
    ToolCallKey,
    may_have_run,
)

if TYPE_CHECKING:
    # `NetworkRequestResultKnowledge` is passed in and named in annotations only, so that this module never loads `knowledge/` itself.
    from tb_internet_use.knowledge.network_request_result_knowledge import (
        NetworkRequestResultKnowledge,
    )

_ATTEMPTED = NetworkRequestResultLevel.ATTEMPTED
_EXECUTED = NetworkRequestResultLevel.EXECUTED
_REACHED = NetworkRequestResultLevel.REACHED
_RECEIVED = NetworkRequestResultLevel.RECEIVED
_FAILED = NetworkRequestResultStopReason.FAILED
_NOT_VISIBLE = NetworkRequestResultStopReason.NOT_VISIBLE
_NOT_NEEDED = NetworkRequestResultStopReason.NOT_NEEDED

# The kinds of line that show that the run failed before it reached a server, as a fact of the line.
_FAILURE_BEFORE_SERVER_KINDS = frozenset(
    {
        OutputLineKind.NAME_NOT_RESOLVED,
        OutputLineKind.CONNECTION_FAILED,
        OutputLineKind.REFUSED_LOCALLY,
    }
)
# The kinds of line that show only that a server answered, without what it sent.
_SERVER_ANSWER_KINDS = frozenset(
    {OutputLineKind.SERVER_ANSWERED, OutputLineKind.DOWNLOAD_STARTED}
)
# The kinds of a download line of a package file and of a line of a finished install, which together show that the content arrived.
_DOWNLOAD_AND_INSTALL_KINDS = frozenset(
    {OutputLineKind.DOWNLOAD_STARTED, OutputLineKind.INSTALLED}
)
# The status code that curl prints for `%{http_code}` when no answer came, as curl(1) says of `-w`.
_NO_ANSWER_STATUS_CODE = 0


def decide_network_request_result_evidence(
    network_request: NetworkRequest,
    network_requests: Sequence[NetworkRequest],
    expanded_tool_calls: Sequence[ExpandedToolCall],
    output_place_sources: Sequence[OutputPlaceSources],
    output_line_owners: Sequence[OutputLineOwners],
    *,
    knowledge: NetworkRequestResultKnowledge,
    judgment_rule_use_counts: Counter[str],
) -> tuple[EvidenceWithLevel, ...]:
    """Decide every piece of evidence of `network_request`, each with the level and stop reason it shows, its lines first, then the evidence of its run, then that of what it received.

    `network_requests` are all requests of the trial, so that a line of command a can stop the request of b in `a && b`, and `output_place_sources` tell whether the place of a line may show file content or page text and which runs reach it.
    Every use of a rule of `judgment_rules.py` adds one to `judgment_rule_use_counts`, and a request without evidence of its run counts `treat_command_without_own_evidence_as_no_evidence_of_run` once.
    A call whose result is `NOT_RUN` ran nothing, so its requests get only the evidence of its status, e.g. a `curl u` call marked not run whose result holds a message of the harness.
    """
    expanded_tool_call_by_key = {
        expanded_tool_call.tool_call.harness_tool_call.key: expanded_tool_call
        for expanded_tool_call in expanded_tool_calls
    }
    tool_call = expanded_tool_call_by_key[network_request.tool_call_key].tool_call
    if not may_have_run(tool_call):
        return (
            EvidenceWithLevel(
                ExecutionStatusEvidence(
                    tool_call.harness_tool_call.key,
                    ExecutionStatus.NOT_RUN,
                    _has_other_request_in_call(network_request, network_requests),
                ),
                _ATTEMPTED,
                _FAILED,
                assumption_reasons=(),
            ),
        )
    output_place_sources_by_key = {
        output_place_sources_of_call.showing_tool_call_key: output_place_sources_of_call
        for output_place_sources_of_call in output_place_sources
    }
    output_line_evidence = _output_line_evidence_of(
        network_request,
        output_line_owners,
        output_place_sources_by_key,
        expanded_tool_call_by_key,
        knowledge=knowledge,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )
    execution_evidence = _execution_evidence_of(
        network_request,
        network_requests,
        output_line_owners,
        output_place_sources_by_key,
        expanded_tool_call_by_key,
        knowledge=knowledge,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )
    received_content_evidence = _received_content_evidence_of(
        network_request,
        network_requests,
        output_line_owners,
        output_place_sources,
        expanded_tool_call_by_key,
        call_index_by_key={
            tool_call_key: call_index
            for call_index, tool_call_key in enumerate(expanded_tool_call_by_key)
        },
        has_failed_line=any(
            isinstance(evidence_with_level.evidence, OutputLineEvidence)
            and evidence_with_level.stop_reason == _FAILED
            for evidence_with_level in (*output_line_evidence, *execution_evidence)
        ),
        judgment_rule_use_counts=judgment_rule_use_counts,
    )
    return (*output_line_evidence, *execution_evidence, *received_content_evidence)


def _output_line_evidence_of(
    network_request: NetworkRequest,
    output_line_owners: Sequence[OutputLineOwners],
    output_place_sources_by_key: Mapping[ToolCallKey, OutputPlaceSources],
    expanded_tool_call_by_key: Mapping[ToolCallKey, ExpandedToolCall],
    *,
    knowledge: NetworkRequestResultKnowledge,
    judgment_rule_use_counts: Counter[str],
) -> list[EvidenceWithLevel]:
    """Find the evidence of each line that the request owns, in the order of `output_line_owners`.

    The line may belong to another request when it has several owners, unless it shows only that their one command ran or that its program is missing, and, whether or not it has several owners, when the request's run has no known lines, e.g. `HTTP/1.1 200 OK` under `mytool https://a.org/x`, or when any program prints it and a run that is not read reaches its place, e.g. `Connection refused` under `curl -s u; ./test.sh`.
    The last two ask `treat_line_that_unknown_printer_may_have_printed_as_shared`. A line that only named programs print, one of them a printing program of the run, stays the request's own beside a run that is not read, e.g. `npm ERR! code E404` under `npx tsc`.
    A line in a place that may show file content or page text asks `treat_line_beside_shown_file_or_page_text_as_not_a_trace`.
    A download line of a package file beside a line of a finished install shows that the content arrived, e.g. `Downloading x-1.0.whl (125 kB)` and `Successfully installed x-1.0`, as `_download_and_install_line_indexes_of` finds them, so those lines show RECEIVED, or REACHED for a request that asks for no content, before any rule is asked of their level. Such a line that the other requests of the command own too stays shared.
    """
    owned_output_line_owners = [
        output_line_owners_of_line
        for output_line_owners_of_line in output_line_owners
        if network_request in output_line_owners_of_line.owner_network_requests
    ]
    places = [
        output_place_sources_by_key[
            output_line_owners_of_line.output_line_with_meaning.showing_tool_call_key
        ]
        for output_line_owners_of_line in owned_output_line_owners
    ]
    is_beside_shown_text_of_lines = [
        (place.may_show_file_content or place.may_show_page_text)
        and judgment_rules.treat_line_beside_shown_file_or_page_text_as_not_a_trace(
            use_counts=judgment_rule_use_counts
        )
        for place in places
    ]
    # A run whose lines are not known may have printed the line too, also when other requests own it, so those reasons come beside the shared one, e.g. `HTTP/1.1 200 OK` under `curl -sI u1; curl -sI u2; ./check.sh`.
    unknown_printer_reasons_of_lines = [
        _unknown_printer_reasons_of(
            network_request,
            output_line_owners_of_line.output_line_with_meaning.output_line_meaning,
            place,
            expanded_tool_call_by_key,
            knowledge=knowledge,
            judgment_rule_use_counts=judgment_rule_use_counts,
        )
        for output_line_owners_of_line, place in zip(
            owned_output_line_owners, places, strict=True
        )
    ]
    download_and_install_line_indexes = _download_and_install_line_indexes_of(
        owned_output_line_owners,
        is_beside_shown_text_of_lines,
        unknown_printer_reasons_of_lines,
    )
    output_line_evidence: list[EvidenceWithLevel] = []
    for owned_line_index, (
        output_line_owners_of_line,
        is_beside_shown_text,
        unknown_printer_reasons,
    ) in enumerate(
        zip(
            owned_output_line_owners,
            is_beside_shown_text_of_lines,
            unknown_printer_reasons_of_lines,
            strict=True,
        )
    ):
        owner_network_requests = output_line_owners_of_line.owner_network_requests
        output_line_with_meaning = output_line_owners_of_line.output_line_with_meaning
        output_line_meaning = output_line_with_meaning.output_line_meaning
        if owned_line_index in download_and_install_line_indexes:
            level, stop_reason, rests_on_judgment_rule = (
                _success_level_of(network_request),
                None,
                False,
            )
        else:
            level, stop_reason, rests_on_judgment_rule = (
                _level_and_stop_reason_from_output_line(
                    network_request,
                    output_line_owners_of_line,
                    judgment_rule_use_counts=judgment_rule_use_counts,
                )
            )
        rests_on_judgment_rule = rests_on_judgment_rule or is_beside_shown_text
        is_shared_with_other_requests = len(owner_network_requests) > 1
        # A missing program and a run are facts about the whole command, so a line that shows only them holds for each request of that command, e.g. both of `pip install a b` under `pip: command not found`.
        may_belong_to_another_request_reasons: tuple[
            NetworkRequestResultAssumptionReason, ...
        ] = (
            (
                SharedOutputLineAssumptionReason(
                    output_line_with_meaning.showing_tool_call_key,
                    output_line_with_meaning.line_index,
                    output_line_with_meaning.line_index_in_json_string,
                ),
            )
            if is_shared_with_other_requests
            and not (
                (
                    output_line_meaning.kind == OutputLineKind.PROGRAM_MISSING
                    or (level, stop_reason) == (_EXECUTED, _NOT_VISIBLE)
                )
                and _are_requests_of_one_command(owner_network_requests)
            )
            else ()
        ) + unknown_printer_reasons
        output_line_evidence.append(
            EvidenceWithLevel(
                evidence=OutputLineEvidence(
                    showing_tool_call_key=output_line_with_meaning.showing_tool_call_key,
                    line_index=output_line_with_meaning.line_index,
                    line_index_in_json_string=output_line_with_meaning.line_index_in_json_string,
                    kind=output_line_meaning.kind,
                    is_shared_with_other_requests=is_shared_with_other_requests,
                ),
                level=level,
                stop_reason=stop_reason,
                assumption_reasons=_evidence_assumption_reasons_from(
                    may_belong_to_another_request_reasons,
                    rests_on_judgment_rule=rests_on_judgment_rule,
                ),
            )
        )
    return output_line_evidence


def _unknown_printer_reasons_of(
    network_request: NetworkRequest,
    output_line_meaning: OutputLineMeaning,
    place: OutputPlaceSources,
    expanded_tool_call_by_key: Mapping[ToolCallKey, ExpandedToolCall],
    *,
    knowledge: NetworkRequestResultKnowledge,
    judgment_rule_use_counts: Counter[str],
) -> tuple[
    UnknownProgramOutputLinesAssumptionReason | UnknownRunBesideAssumptionReason, ...
]:
    """Find the reasons that a line of the request, its own or shared with other requests, may still have been printed by a run whose lines are unknown, none when there is no such run or `treat_line_that_unknown_printer_may_have_printed_as_shared` answers `False`.

    One reason is the run of the request itself, e.g. `HTTP/1.1 200 OK` under `mytool https://a.org/x`. The other is a run that is not read beside it, only for a line that any program prints, e.g. `Connection refused` under `curl -s u; ./test.sh`. Both can hold, e.g. `Connection refused` under `mytool https://a.org/x; ./test.sh`, and the rule is asked once when either does.
    """
    unknown_printer_reasons: list[
        UnknownProgramOutputLinesAssumptionReason | UnknownRunBesideAssumptionReason
    ] = []
    if _has_unknown_printer(
        network_request,
        output_line_meaning.kind,
        expanded_tool_call_by_key,
        knowledge=knowledge,
    ):
        unknown_printer_reasons.append(UnknownProgramOutputLinesAssumptionReason())
    if output_line_meaning.is_printed_by_other_programs_too and has_unknown_run_beside(
        network_request, place, expanded_tool_call_by_key
    ):
        unknown_printer_reasons.append(UnknownRunBesideAssumptionReason())
    if (
        unknown_printer_reasons
        and judgment_rules.treat_line_that_unknown_printer_may_have_printed_as_shared(
            use_counts=judgment_rule_use_counts
        )
    ):
        return tuple(unknown_printer_reasons)
    return ()


def _download_and_install_line_indexes_of(
    owned_output_line_owners: Sequence[OutputLineOwners],
    is_beside_shown_text_of_lines: Sequence[bool],
    unknown_printer_reasons_of_lines: Sequence[
        tuple[
            UnknownProgramOutputLinesAssumptionReason
            | UnknownRunBesideAssumptionReason,
            ...,
        ]
    ],
) -> frozenset[int]:
    """Find the 0-based indexes among the lines that a request owns of its download lines of a package file and its lines of a finished install, when it has both, and none otherwise.

    The pair shows that the command received content, e.g. `Downloading x-1.0.whl (125 kB)` and `Successfully installed x-1.0` under `pip install x`, or `Downloading pandas (10.8MiB)` and ` + pandas==3.0.5` under `uv pip install pandas`, whether or not the lines name the target of the request.
    A line counts only when no other command's request owns it, no run whose lines are not known may have printed it and its place may show no file content or page text, so that a pair that holds only through a line of another request keeps the reading of each line.
    """
    kinds_by_line_index = {
        owned_line_index: output_line_owners_of_line.output_line_with_meaning.output_line_meaning.kind
        for owned_line_index, (
            output_line_owners_of_line,
            is_beside_shown_text,
            unknown_printer_reasons,
        ) in enumerate(
            zip(
                owned_output_line_owners,
                is_beside_shown_text_of_lines,
                unknown_printer_reasons_of_lines,
                strict=True,
            )
        )
        if output_line_owners_of_line.output_line_with_meaning.output_line_meaning.kind
        in _DOWNLOAD_AND_INSTALL_KINDS
        and not is_beside_shown_text
        and not unknown_printer_reasons
        and (
            len(output_line_owners_of_line.owner_network_requests) == 1
            or _are_requests_of_one_command(
                output_line_owners_of_line.owner_network_requests
            )
        )
    }
    if not _DOWNLOAD_AND_INSTALL_KINDS <= set(kinds_by_line_index.values()):
        return frozenset()
    return frozenset(kinds_by_line_index)


def _evidence_assumption_reasons_from(
    may_belong_to_another_request_reasons: tuple[
        NetworkRequestResultAssumptionReason, ...
    ],
    *,
    rests_on_judgment_rule: bool,
) -> tuple[NetworkRequestResultAssumptionReason, ...]:
    """Give the assumption reasons of one piece of evidence, the reasons that another request or run may own it first and then a judgment rule that gave its level."""
    return (
        *may_belong_to_another_request_reasons,
        *((JudgmentRuleAssumptionReason(),) if rests_on_judgment_rule else ()),
    )


def _level_and_stop_reason_from_output_line(
    network_request: NetworkRequest,
    output_line_owners: OutputLineOwners,
    *,
    judgment_rule_use_counts: Counter[str],
) -> tuple[NetworkRequestResultLevel, NetworkRequestResultStopReason | None, bool]:
    """Find the level and stop reason that a line of a request shows, with whether a judgment rule gave them.

    A line that names another target than the request asks `treat_line_naming_another_target_as_no_evidence_of_answer` first, e.g. `Downloading B-1.0.whl` under `pip install A`.
    A line other than one of a missing program shows at least that the program ran, so EXECUTED with NOT_VISIBLE never rests on a rule, also when a rule chose it.
    An install line of pip or apt under a request of a named package asks `treat_pip_or_apt_installed_line_of_named_package_as_received`, whose level rests on no rule, and any other install line asks `treat_installed_line_as_no_evidence_of_download`.
    """
    output_line_meaning = (
        output_line_owners.output_line_with_meaning.output_line_meaning
    )
    kind = output_line_meaning.kind
    if (
        output_line_owners.names_another_target
        and judgment_rules.treat_line_naming_another_target_as_no_evidence_of_answer(
            use_counts=judgment_rule_use_counts
        )
    ):
        return _EXECUTED, _NOT_VISIBLE, False
    level_and_stop_reason: tuple[
        NetworkRequestResultLevel, NetworkRequestResultStopReason | None
    ]
    # A line that names another target reaches here only when that rule took it as the request's, so its level rests on the rule.
    is_given_by_judgment_rule = output_line_owners.names_another_target
    if kind == OutputLineKind.PROGRAM_MISSING:
        level_and_stop_reason = _ATTEMPTED, _FAILED
    elif kind in _FAILURE_BEFORE_SERVER_KINDS:
        level_and_stop_reason = _EXECUTED, _FAILED
    elif kind in (OutputLineKind.TLS_FAILED, OutputLineKind.PROXY_REFUSED):
        is_given_by_judgment_rule = True
        level_and_stop_reason = (
            (_EXECUTED, _FAILED)
            if judgment_rules.treat_tls_or_proxy_failure_as_before_server_answer(
                kind, use_counts=judgment_rule_use_counts
            )
            else (_REACHED, _FAILED)
        )
    elif kind == OutputLineKind.CONNECTION_LOST:
        is_given_by_judgment_rule = True
        level_and_stop_reason = (
            (_REACHED, _FAILED)
            if judgment_rules.treat_lost_connection_as_after_server_answer(
                use_counts=judgment_rule_use_counts
            )
            else (_EXECUTED, _FAILED)
        )
    elif kind == OutputLineKind.ALREADY_PRESENT:
        if _is_target_named_by_package_names_text(
            output_line_meaning.package_names_text, network_request
        ):
            level_and_stop_reason = _EXECUTED, _NOT_NEEDED
        else:
            is_given_by_judgment_rule = True
            level_and_stop_reason = (
                (_EXECUTED, _NOT_NEEDED)
                if judgment_rules.treat_already_present_line_without_matching_target_as_assumed_not_needed(
                    use_counts=judgment_rule_use_counts
                )
                else (_EXECUTED, _NOT_VISIBLE)
            )
    elif kind == OutputLineKind.CONNECTED:
        is_given_by_judgment_rule = True
        level_and_stop_reason = (
            (_REACHED, _NOT_VISIBLE)
            if judgment_rules.treat_connected_line_as_assumed_server_answer(
                use_counts=judgment_rule_use_counts
            )
            else (_EXECUTED, _NOT_VISIBLE)
        )
    elif kind in _SERVER_ANSWER_KINDS:
        level_and_stop_reason = _REACHED, _NOT_VISIBLE
    elif kind == OutputLineKind.NOT_FOUND:
        # pip prints `No matching distribution found for x` also when the index cannot be reached, and apt prints `Unable to locate package x` from its local lists, so the line shows a failure but not that a server answered.
        level_and_stop_reason = _EXECUTED, _FAILED
    elif kind == OutputLineKind.DOWNLOADED:
        level_and_stop_reason = _success_level_of(network_request), None
    elif kind in (OutputLineKind.HTTP_STATUS, OutputLineKind.BARE_STATUS_CODE):
        status_code = output_line_meaning.status_code
        level_and_stop_reason_of_status_code = (
            (_EXECUTED, _FAILED)
            if kind == OutputLineKind.BARE_STATUS_CODE
            and status_code == _NO_ANSWER_STATUS_CODE
            else _level_and_stop_reason_from_status_code(status_code, network_request)
        )
        # The patterns of these kinds read only 000 and codes from 100 to 599.
        if level_and_stop_reason_of_status_code is None:
            raise ValueError(
                f"a line of the kind {kind} with status code {status_code}"
            )
        level_and_stop_reason = level_and_stop_reason_of_status_code
    elif kind == OutputLineKind.INSTALLED and (
        _is_line_of_pip_or_apt_alone(output_line_meaning)
        and _has_package_name_target(network_request)
    ):
        level_and_stop_reason = (
            (_success_level_of(network_request), None)
            if judgment_rules.treat_pip_or_apt_installed_line_of_named_package_as_received(
                use_counts=judgment_rule_use_counts
            )
            else (_EXECUTED, _NOT_VISIBLE)
        )
    elif kind == OutputLineKind.INSTALLED:
        is_given_by_judgment_rule = True
        level_and_stop_reason = (
            (_EXECUTED, _NOT_VISIBLE)
            if judgment_rules.treat_installed_line_as_no_evidence_of_download(
                use_counts=judgment_rule_use_counts
            )
            else (_RECEIVED, None)
        )
    elif kind == OutputLineKind.VERSION_NOTICE:
        is_given_by_judgment_rule = True
        level_and_stop_reason = (
            (_EXECUTED, _NOT_VISIBLE)
            if judgment_rules.treat_version_notice_line_as_no_evidence_of_answer(
                use_counts=judgment_rule_use_counts
            )
            else (_REACHED, _NOT_VISIBLE)
        )
    else:
        raise ValueError(f"a line of the kind {kind}, which gives no level here")
    level, stop_reason = level_and_stop_reason
    return (
        level,
        stop_reason,
        is_given_by_judgment_rule
        and level_and_stop_reason != (_EXECUTED, _NOT_VISIBLE),
    )


def _execution_evidence_of(
    network_request: NetworkRequest,
    network_requests: Sequence[NetworkRequest],
    output_line_owners: Sequence[OutputLineOwners],
    output_place_sources_by_key: Mapping[ToolCallKey, OutputPlaceSources],
    expanded_tool_call_by_key: Mapping[ToolCallKey, ExpandedToolCall],
    *,
    knowledge: NetworkRequestResultKnowledge,
    judgment_rule_use_counts: Counter[str],
) -> list[EvidenceWithLevel]:
    """Find the evidence of whether the request of a call that may have run ran, from the status of its call, the exit code of the call's text, or a command before it in `a && b` that failed.

    A finished call of a web tool shows EXECUTED with NOT_VISIBLE.
    Exit code 0 of the call's text shows EXECUTED for a command of that text that `succeeded_if_text_exits_zero` marks, and `treat_exit_code_meaning_as_assumed_level` may lift it by what the exit code catalog says.
    Another exit code gives no level. `NetworkRequestResultKnowledge` is asked about it only when it belongs to the command, so that a missing row is counted.
    A request without any of this asks `treat_command_without_own_evidence_as_no_evidence_of_run`.
    """
    expanded_tool_call = expanded_tool_call_by_key[network_request.tool_call_key]
    tool_call = expanded_tool_call.tool_call
    is_shared_with_other_requests = _has_other_request_in_call(
        network_request, network_requests
    )
    source = network_request.source
    execution_evidence: list[EvidenceWithLevel] = []
    if isinstance(source, FromWebTool):
        if (
            tool_call.result is not None
            and tool_call.result.execution_status == ExecutionStatus.FINISHED
        ):
            execution_evidence.append(
                EvidenceWithLevel(
                    ExecutionStatusEvidence(
                        tool_call.harness_tool_call.key,
                        ExecutionStatus.FINISHED,
                        is_shared_with_other_requests,
                    ),
                    _EXECUTED,
                    _NOT_VISIBLE,
                    assumption_reasons=(),
                )
            )
    else:
        if isinstance(source, FromCommand):
            execution_evidence += _exit_code_evidence_of(
                network_request,
                source,
                expanded_tool_call,
                is_shared_with_other_requests=is_shared_with_other_requests,
                knowledge=knowledge,
                judgment_rule_use_counts=judgment_rule_use_counts,
            )
        execution_evidence += _stopping_line_evidence_of(
            network_request,
            network_requests,
            output_line_owners,
            output_place_sources_by_key,
            expanded_tool_call_by_key,
            knowledge=knowledge,
            judgment_rule_use_counts=judgment_rule_use_counts,
        )
    if (
        not execution_evidence
        and not judgment_rules.treat_command_without_own_evidence_as_no_evidence_of_run(
            use_counts=judgment_rule_use_counts
        )
    ):
        execution_evidence.append(
            EvidenceWithLevel(
                ExecutionStatusEvidence(
                    tool_call.harness_tool_call.key,
                    _execution_status_of(expanded_tool_call),
                    is_shared_with_other_requests,
                ),
                _EXECUTED,
                _NOT_VISIBLE,
                assumption_reasons=(JudgmentRuleAssumptionReason(),),
            )
        )
    return execution_evidence


def _exit_code_evidence_of(
    network_request: NetworkRequest,
    source: FromCommand,
    expanded_tool_call: ExpandedToolCall,
    *,
    is_shared_with_other_requests: bool,
    knowledge: NetworkRequestResultKnowledge,
    judgment_rule_use_counts: Counter[str],
) -> list[EvidenceWithLevel]:
    """Find the evidence that the exit code of the call's text gives the request of a command, or none when that code does not belong to the command.

    The code belongs to the command when the command is in the text of the call, the text finished, `succeeded_if_text_exits_zero` marks the command, `structure_may_be_wrong` does not, and every program outside the request's program ends with the exit code of the next, e.g. sudo.
    Exit 0 then shows EXECUTED for each such command, both of `a && b` included.
    Another code belongs to the command only when it is the one command of the text so marked, e.g. `curl -f -s u -o x` alone or after `ls;`, and then `NetworkRequestResultKnowledge` is asked and its answer is not used.
    """
    command_text_status = expanded_tool_call.command_text_status
    if (
        command_text_status is None
        or command_text_status.execution_status != ExecutionStatus.FINISHED
        or command_text_status.exit_code is None
    ):
        return []
    call_ran_commands = _call_text_ran_commands_of(expanded_tool_call)
    ran_command = next(
        (
            call_ran_command
            for call_ran_command in call_ran_commands
            if call_ran_command.shell_command.id == source.command_id
        ),
        None,
    )
    if (
        ran_command is None
        or not ran_command.shell_command.succeeded_if_text_exits_zero
        or ran_command.shell_command.structure_may_be_wrong
        or not _ends_with_exit_code_of_program(ran_command, source.program_invocation)
    ):
        return []
    exit_code = command_text_status.exit_code
    # `NetworkRequestResultKnowledge` has no row for a program that no fact covers or for options that were not read, so neither is asked.
    program_invocation = (
        source.program_invocation
        if isinstance(source.program_invocation, ProgramInvocation)
        and not source.program_invocation.unread_words
        else None
    )
    if exit_code != 0:
        if program_invocation is not None and [
            call_ran_command
            for call_ran_command in call_ran_commands
            if call_ran_command.shell_command.succeeded_if_text_exits_zero
        ] == [ran_command]:
            knowledge.program_exit_code_meaning(program_invocation, exit_code)
        return []
    level: NetworkRequestResultLevel = _EXECUTED
    stop_reason: NetworkRequestResultStopReason | None = _NOT_VISIBLE
    rests_on_judgment_rule = False
    program_exit_code_meaning = (
        knowledge.program_exit_code_meaning(program_invocation, 0)
        if program_invocation is not None
        else None
    )
    if (
        isinstance(program_exit_code_meaning, ProgramExitCodeMeaning)
        and program_exit_code_meaning != ProgramExitCodeMeaning.NOTHING
    ) and judgment_rules.treat_exit_code_meaning_as_assumed_level(
        program_exit_code_meaning, use_counts=judgment_rule_use_counts
    ):
        rests_on_judgment_rule = True
        if program_exit_code_meaning == ProgramExitCodeMeaning.SERVER_ANSWERED:
            level, stop_reason = _REACHED, _NOT_VISIBLE
        else:
            level, stop_reason = _success_level_of(network_request), None
    return [
        EvidenceWithLevel(
            ExitCodeEvidence(
                command_text_status.reporter_tool_call_key,
                0,
                is_shared_with_other_requests,
            ),
            level,
            stop_reason,
            assumption_reasons=_evidence_assumption_reasons_from(
                (), rests_on_judgment_rule=rests_on_judgment_rule
            ),
        )
    ]


def _stopping_line_evidence_of(
    network_request: NetworkRequest,
    network_requests: Sequence[NetworkRequest],
    output_line_owners: Sequence[OutputLineOwners],
    output_place_sources_by_key: Mapping[ToolCallKey, OutputPlaceSources],
    expanded_tool_call_by_key: Mapping[ToolCallKey, ExpandedToolCall],
    *,
    knowledge: NetworkRequestResultKnowledge,
    judgment_rule_use_counts: Counter[str],
) -> list[EvidenceWithLevel]:
    """Find the lines of command a that show the command b of the request did not run in `a && b`, each as evidence of ATTEMPTED with FAILED.

    A line of a missing program whose word is a program word of a is a fact, e.g. `rg: command not found` for `pip install y` in `rg x && pip install y`, whether or not a has a request and wherever a's output went.
    It may belong to another command when its word is a program word of another command whose output reaches the place too, e.g. the first rg of `rg a; rg x && pip install y`.
    A line that the request owns is already its own evidence and is not added again, e.g. `pip: command not found` for b in `pip install a && pip install b`.
    A line that shows a request of a failed before a server, e.g. `Failed to connect to a.org` for `curl -sS https://a.org/x && pip install y`, asks `treat_failure_before_server_as_stopping_next_command` once, and only when the line may belong to no other request.
    """
    command_id = command_id_of_network_request(network_request)
    if command_id is None:
        return []
    tool_call_key = network_request.tool_call_key
    ran_commands = ran_commands_of(expanded_tool_call_by_key[tool_call_key])
    stopping_line_evidence: list[EvidenceWithLevel] = []
    for output_line_owners_of_line in output_line_owners:
        output_line_with_meaning = output_line_owners_of_line.output_line_with_meaning
        missing_program_word = (
            output_line_with_meaning.output_line_meaning.missing_program_word
        )
        place = output_place_sources_by_key.get(
            output_line_with_meaning.showing_tool_call_key
        )
        if (
            output_line_with_meaning.output_line_meaning.kind
            != OutputLineKind.PROGRAM_MISSING
            or missing_program_word is None
            or place is None
            or network_request in output_line_owners_of_line.owner_network_requests
            or not any(
                output_place_source_commands.tool_call_key == tool_call_key
                for output_place_source_commands in place.source_commands
            )
            or command_id
            not in stopped_command_ids_from_missing_program_line(
                missing_program_word, ran_commands
            )
        ):
            continue
        stopping_command_ids = _deciding_command_ids_of(ran_commands, command_id)
        stopping_line_evidence.append(
            EvidenceWithLevel(
                _output_line_evidence_of_stopping_line(output_line_owners_of_line),
                _ATTEMPTED,
                _FAILED,
                assumption_reasons=(MissingProgramOfAnotherCommandAssumptionReason(),)
                if any(
                    is_missing_program_of_command(missing_program_word, ran_command)
                    for output_place_source_commands in place.source_commands
                    for ran_command in ran_commands_of(
                        expanded_tool_call_by_key[
                            output_place_source_commands.tool_call_key
                        ]
                    )
                    if ran_command.shell_command.id
                    in output_place_source_commands.command_ids
                    and not (
                        output_place_source_commands.tool_call_key == tool_call_key
                        and ran_command.shell_command.id in stopping_command_ids
                    )
                )
                else (),
            )
        )
    if stopping_line_evidence:
        return stopping_line_evidence
    failure_lines = _failure_before_server_lines_of_deciding_requests(
        network_request,
        network_requests,
        output_line_owners,
        output_place_sources_by_key,
        expanded_tool_call_by_key,
        knowledge=knowledge,
    )
    if (
        failure_lines
        and judgment_rules.treat_failure_before_server_as_stopping_next_command(
            use_counts=judgment_rule_use_counts
        )
    ):
        return [
            EvidenceWithLevel(
                _output_line_evidence_of_stopping_line(output_line_owners_of_line),
                _ATTEMPTED,
                _FAILED,
                assumption_reasons=(JudgmentRuleAssumptionReason(),),
            )
            for output_line_owners_of_line in failure_lines
        ]
    return []


def _failure_before_server_lines_of_deciding_requests(
    network_request: NetworkRequest,
    network_requests: Sequence[NetworkRequest],
    output_line_owners: Sequence[OutputLineOwners],
    output_place_sources_by_key: Mapping[ToolCallKey, OutputPlaceSources],
    expanded_tool_call_by_key: Mapping[ToolCallKey, ExpandedToolCall],
    *,
    knowledge: NetworkRequestResultKnowledge,
) -> list[OutputLineOwners]:
    """Find the lines of a request of a command a that the command b of the request runs only after, which show EXECUTED with FAILED and may belong to no other request.

    The level of each line of a is read again with counts that are thrown away, since those rules are counted for the request of a when its own evidence is decided.
    """
    command_id = command_id_of_network_request(network_request)
    if command_id is None:
        return []
    ran_commands = ran_commands_of(
        expanded_tool_call_by_key[network_request.tool_call_key]
    )
    deciding_command_ids = _deciding_command_ids_of(ran_commands, command_id)
    deciding_network_requests = [
        other_network_request
        for other_network_request in network_requests
        if other_network_request.tool_call_key == network_request.tool_call_key
        and command_id_of_network_request(other_network_request) in deciding_command_ids
    ]
    failure_lines: list[OutputLineOwners] = []
    for deciding_network_request in deciding_network_requests:
        for evidence_with_level, output_line_owners_of_line in zip(
            _output_line_evidence_of(
                deciding_network_request,
                output_line_owners,
                output_place_sources_by_key,
                expanded_tool_call_by_key,
                knowledge=knowledge,
                judgment_rule_use_counts=Counter(),
            ),
            [
                output_line_owners_of_line
                for output_line_owners_of_line in output_line_owners
                if deciding_network_request
                in output_line_owners_of_line.owner_network_requests
            ],
            strict=True,
        ):
            if (
                evidence_with_level.level == _EXECUTED
                and evidence_with_level.stop_reason == _FAILED
                and not evidence_with_level.may_belong_to_another_request
            ):
                failure_lines.append(output_line_owners_of_line)
    return failure_lines


def _received_content_evidence_of(
    network_request: NetworkRequest,
    network_requests: Sequence[NetworkRequest],
    output_line_owners: Sequence[OutputLineOwners],
    output_place_sources: Sequence[OutputPlaceSources],
    expanded_tool_call_by_key: Mapping[ToolCallKey, ExpandedToolCall],
    *,
    call_index_by_key: Mapping[ToolCallKey, int],
    has_failed_line: bool,
    judgment_rule_use_counts: Counter[str],
) -> list[EvidenceWithLevel]:
    """Find the evidence of what the request received, from the HTTP status of a web fetch, the later uses of the file where it saved the content, and the result that shows the content.

    `has_failed_line` tells whether a line of the request shows FAILED, which keeps a shown result text from being taken as the content, as an HTTP status from 400 to 599 of a web fetch does.
    For a request of a web tool, the status and the result text count only when the web tool is the call's own action, since a web step of a tool script prints nothing into the result of the script.
    A status outside 100 to 599 shows no level and gives no evidence.
    A finished call of a web tool with neither a result text nor a status asks `treat_web_tool_call_without_result_text_as_no_evidence_of_answer`, e.g. a Codex `web_search_call` whose result is `null`.
    """
    expanded_tool_call = expanded_tool_call_by_key[network_request.tool_call_key]
    tool_call = expanded_tool_call.tool_call
    result = tool_call.result
    source = network_request.source
    received_content_evidence: list[EvidenceWithLevel] = []
    is_own_web_tool_call = isinstance(source, FromWebTool) and source.step_index is None
    level_and_stop_reason = (
        _level_and_stop_reason_from_status_code(result.http_status, network_request)
        if is_own_web_tool_call and result is not None
        else None
    )
    if result is not None and result.http_status is not None and level_and_stop_reason:
        received_content_evidence.append(
            EvidenceWithLevel(
                HttpStatusEvidence(tool_call.harness_tool_call.key, result.http_status),
                *level_and_stop_reason,
                assumption_reasons=(SharedHttpStatusAssumptionReason(),)
                if _has_other_request_in_call(network_request, network_requests)
                else (),
            )
        )
        # The status is read like an HTTP status line, so a status that failed keeps a shown result text from being taken as the content as a failed line does.
        has_failed_line = has_failed_line or level_and_stop_reason[1] == _FAILED
    received_content_evidence += _file_use_evidence_of(
        network_request,
        network_requests,
        output_line_owners,
        output_place_sources,
        expanded_tool_call_by_key,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )
    if isinstance(network_request.received_content_destination, ContentShownInResult):
        showing_tool_call_keys = _showing_tool_call_keys_of_shown_content(
            network_request,
            network_requests,
            output_line_owners,
            output_place_sources,
            expanded_tool_call_by_key,
            call_index_by_key,
        )
        if (
            showing_tool_call_keys
            and not has_failed_line
            and judgment_rules.treat_shown_result_text_as_assumed_content(
                use_counts=judgment_rule_use_counts
            )
        ):
            received_content_evidence += [
                EvidenceWithLevel(
                    ShownContentEvidence(showing_tool_call_key),
                    _RECEIVED,
                    None,
                    assumption_reasons=(JudgmentRuleAssumptionReason(),),
                )
                for showing_tool_call_key in showing_tool_call_keys
            ]
    if (
        is_own_web_tool_call
        and result is not None
        and result.execution_status == ExecutionStatus.FINISHED
        and not result.tool_output_text
        and result.http_status is None
        and not judgment_rules.treat_web_tool_call_without_result_text_as_no_evidence_of_answer(
            use_counts=judgment_rule_use_counts
        )
    ):
        received_content_evidence.append(
            EvidenceWithLevel(
                ExecutionStatusEvidence(
                    tool_call.harness_tool_call.key, ExecutionStatus.FINISHED, False
                ),
                _REACHED,
                _NOT_VISIBLE,
                assumption_reasons=(JudgmentRuleAssumptionReason(),),
            )
        )
    return received_content_evidence


def _file_use_evidence_of(
    network_request: NetworkRequest,
    network_requests: Sequence[NetworkRequest],
    output_line_owners: Sequence[OutputLineOwners],
    output_place_sources: Sequence[OutputPlaceSources],
    expanded_tool_call_by_key: Mapping[ToolCallKey, ExpandedToolCall],
    *,
    judgment_rule_use_counts: Counter[str],
) -> list[EvidenceWithLevel]:
    """Find the evidence of each later use of the file where the request saved what it received, e.g. `tar xzf a.tgz` after `curl -s -o a.tgz u`.

    A use by a command whose program a line says is missing did not happen and gives nothing, e.g. `unzip -o -q a.zip` under `unzip: command not found`.
    A use of the content that surely happened shows RECEIVED as a fact. One that may not have happened asks `treat_file_use_that_may_not_have_happened_as_assumed_evidence`.
    A use that shows the content asks `treat_shown_content_of_saved_file_as_assumed_content`, and one that shows only its size or kind asks `treat_size_or_type_of_saved_file_as_no_evidence_of_content`. A use of unknown kind gives nothing.
    The evidence may belong to another request when another request of the call wrote the same file, e.g. `curl -o a u1; curl -o a u2`.
    """
    received_content_destination = network_request.received_content_destination
    command_id = command_id_of_network_request(network_request)
    if (
        not isinstance(received_content_destination, ContentSaved)
        or received_content_destination.path is None
        or command_id is None
    ):
        return []
    expanded_tool_call = expanded_tool_call_by_key[network_request.tool_call_key]
    output_place_sources_by_key = {
        output_place_sources_of_call.showing_tool_call_key: output_place_sources_of_call
        for output_place_sources_of_call in output_place_sources
    }
    file_use_evidence: list[EvidenceWithLevel] = []
    for written_file in expanded_tool_call.written_files:
        writer_command_ids = {writer.command_id for writer in written_file.writers}
        if (
            written_file.path != received_content_destination.path
            or command_id not in writer_command_ids
        ):
            continue
        is_written_by_another_request = _is_written_by_another_request(
            written_file, network_request, network_requests
        )
        for file_use in written_file.file_uses:
            if _is_program_of_using_command_missing(
                file_use,
                output_line_owners,
                output_place_sources_by_key,
                expanded_tool_call_by_key,
            ):
                continue
            evidence_with_level = _file_use_evidence_with_level_of(
                file_use,
                expanded_tool_call_by_key,
                is_written_by_another_request=is_written_by_another_request,
                judgment_rule_use_counts=judgment_rule_use_counts,
            )
            if evidence_with_level is not None:
                file_use_evidence.append(evidence_with_level)
    return file_use_evidence


def _is_program_of_using_command_missing(
    file_use: FileUse,
    output_line_owners: Sequence[OutputLineOwners],
    output_place_sources_by_key: Mapping[ToolCallKey, OutputPlaceSources],
    expanded_tool_call_by_key: Mapping[ToolCallKey, ExpandedToolCall],
) -> bool:
    """Tell whether a line of a missing program in a place that the using call reaches names a program word of the command that uses a saved file, e.g. `unzip: command not found` under `unzip -o -q a.zip`.

    A program that is not installed ends every command that runs it before it reads anything, so such a command used no file, wherever its own output went.
    """
    if file_use.command_id is None:
        return False
    using_tool_call_key = file_use.using_tool_call_key
    using_ran_command = next(
        (
            ran_command
            for ran_command in ran_commands_of(
                expanded_tool_call_by_key[using_tool_call_key]
            )
            if ran_command.shell_command.id == file_use.command_id
        ),
        None,
    )
    if using_ran_command is None:
        return False
    for output_line_owners_of_line in output_line_owners:
        output_line_with_meaning = output_line_owners_of_line.output_line_with_meaning
        output_line_meaning = output_line_with_meaning.output_line_meaning
        place = output_place_sources_by_key.get(
            output_line_with_meaning.showing_tool_call_key
        )
        if (
            output_line_meaning.kind == OutputLineKind.PROGRAM_MISSING
            and output_line_meaning.missing_program_word is not None
            and place is not None
            and any(
                output_place_source_commands.tool_call_key == using_tool_call_key
                for output_place_source_commands in place.source_commands
            )
            and is_missing_program_of_command(
                output_line_meaning.missing_program_word, using_ran_command
            )
        ):
            return True
    return False


def _file_use_evidence_with_level_of(
    file_use: FileUse,
    expanded_tool_call_by_key: Mapping[ToolCallKey, ExpandedToolCall],
    *,
    is_written_by_another_request: bool,
    judgment_rule_use_counts: Counter[str],
) -> EvidenceWithLevel | None:
    """Find the evidence of one use of a saved file, or None when the use gives none."""
    match file_use.kind:
        case FileUseKind.USES_CONTENT:
            if _is_file_use_sure_to_have_happened(file_use, expanded_tool_call_by_key):
                rests_on_judgment_rule = False
            elif judgment_rules.treat_file_use_that_may_not_have_happened_as_assumed_evidence(
                use_counts=judgment_rule_use_counts
            ):
                rests_on_judgment_rule = True
            else:
                return None
        case FileUseKind.SHOWS_CONTENT:
            if not judgment_rules.treat_shown_content_of_saved_file_as_assumed_content(
                use_counts=judgment_rule_use_counts
            ):
                return None
            rests_on_judgment_rule = True
        case FileUseKind.SHOWS_SIZE_OR_TYPE:
            if judgment_rules.treat_size_or_type_of_saved_file_as_no_evidence_of_content(
                use_counts=judgment_rule_use_counts
            ):
                return None
            rests_on_judgment_rule = True
        case FileUseKind.UNKNOWN:
            return None
    return EvidenceWithLevel(
        FileUseEvidence(file_use),
        _RECEIVED,
        None,
        assumption_reasons=_evidence_assumption_reasons_from(
            (SharedFileUseAssumptionReason(),) if is_written_by_another_request else (),
            rests_on_judgment_rule=rests_on_judgment_rule,
        ),
    )


def _is_file_use_sure_to_have_happened(
    file_use: FileUse,
    expanded_tool_call_by_key: Mapping[ToolCallKey, ExpandedToolCall],
) -> bool:
    """Tell whether the trajectory shows that a use of a saved file ran and succeeded, e.g. `tar xzf a.tgz` in `curl -s -o a.tgz u && tar xzf a.tgz` that ended with exit 0.

    The path must fit one written file, and the using command must be in the text of the call, read with a sure structure, outside a function or case branch, marked by `succeeded_if_text_exits_zero` in a text that finished with exit 0, and run by programs that each end with the exit code of the next.
    """
    if file_use.fits_several_written_files or file_use.command_id is None:
        return False
    using_expanded_tool_call = expanded_tool_call_by_key[file_use.using_tool_call_key]
    command_text_status = using_expanded_tool_call.command_text_status
    if (
        command_text_status is None
        or command_text_status.execution_status != ExecutionStatus.FINISHED
        or command_text_status.exit_code != 0
    ):
        return False
    ran_command = next(
        (
            call_ran_command
            for call_ran_command in _call_text_ran_commands_of(using_expanded_tool_call)
            if call_ran_command.shell_command.id == file_use.command_id
        ),
        None,
    )
    if ran_command is None or not ran_command.program_invocations:
        return False
    shell_command = ran_command.shell_command
    return (
        shell_command.succeeded_if_text_exits_zero
        and not shell_command.structure_may_be_wrong
        and not shell_command.in_function_body
        and not shell_command.in_case_branch
        and _ends_with_exit_code_of_program(
            ran_command, ran_command.program_invocations[-1]
        )
    )


def _showing_tool_call_keys_of_shown_content(
    network_request: NetworkRequest,
    network_requests: Sequence[NetworkRequest],
    output_line_owners: Sequence[OutputLineOwners],
    output_place_sources: Sequence[OutputPlaceSources],
    expanded_tool_call_by_key: Mapping[ToolCallKey, ExpandedToolCall],
    call_index_by_key: Mapping[ToolCallKey, int],
) -> list[ToolCallKey]:
    """Find the results with a text where the content of a request that goes to the result may be shown.

    A request of a web tool counts only for the result of its own call made of web tool actions only, and only when no line of the web tool result patterns is there, e.g. `not a robot`.
    A request of a command counts for each place that its command reaches and that no other request reaches, as `network_requests_of_output_place` finds them, e.g. the result of `curl https://a.org/x`. A request in code does not count.
    `call_index_by_key` gives the 0-based order of each call in the trial.
    """
    source = network_request.source
    showing_tool_call_keys: list[ToolCallKey] = []
    for place in output_place_sources:
        showing_tool_call = expanded_tool_call_by_key[
            place.showing_tool_call_key
        ].tool_call
        if showing_tool_call.result is None or not (
            showing_tool_call.result.tool_output_text
        ):
            continue
        if isinstance(source, FromWebTool):
            if (
                source.step_index is None
                and place.is_web_tool_result
                and place.showing_tool_call_key == network_request.tool_call_key
                and not any(
                    output_line_owners_of_line.output_line_with_meaning.showing_tool_call_key
                    == place.showing_tool_call_key
                    for output_line_owners_of_line in output_line_owners
                )
            ):
                showing_tool_call_keys.append(place.showing_tool_call_key)
        elif isinstance(source, FromCommand) and network_requests_of_output_place(
            place, network_requests, call_index_by_key
        ) == (network_request,):
            showing_tool_call_keys.append(place.showing_tool_call_key)
    return showing_tool_call_keys


def _has_unknown_printer(
    network_request: NetworkRequest,
    output_line_kind: OutputLineKind,
    expanded_tool_call_by_key: Mapping[ToolCallKey, ExpandedToolCall],
    *,
    knowledge: NetworkRequestResultKnowledge,
) -> bool:
    """Tell whether the run of a request has no known lines, asking `NetworkRequestResultKnowledge` through `program_output_lines_of` as the owners of a line were chosen.

    A request of a web tool prints the lines of its result, and a line of a missing program belongs to the command whose program word it names, so neither has an unknown printer.
    """
    source = network_request.source
    if (
        isinstance(source, FromWebTool)
        or output_line_kind == OutputLineKind.PROGRAM_MISSING
    ):
        return False
    return isinstance(
        program_output_lines_of(
            source,
            expanded_tool_call_by_key[network_request.tool_call_key],
            knowledge=knowledge,
        ),
        UnknownProgramOutputLines,
    )


def _level_and_stop_reason_from_status_code(
    status_code: int | None, network_request: NetworkRequest
) -> tuple[NetworkRequestResultLevel, NetworkRequestResultStopReason | None] | None:
    """Find the level and stop reason that an HTTP status code shows, e.g. REACHED with FAILED for 404, or None for a missing code or one outside 100 to 599, which shows no level.

    A code from 100 to 399 is a success for a request that asks for no content, e.g. `curl -I u`, and shows nothing beyond the answer for any other. A code from 400 to 599 is a refusal.
    """
    if status_code is None:
        return None
    if 100 <= status_code <= 399:
        if isinstance(network_request.received_content_destination, NoContentRequested):
            return _REACHED, None
        return _REACHED, _NOT_VISIBLE
    if 400 <= status_code <= 599:
        return _REACHED, _FAILED
    return None


def _success_level_of(network_request: NetworkRequest) -> NetworkRequestResultLevel:
    """Find the level at which a request got what it asked for, REACHED for one that asks for no content and RECEIVED for any other."""
    if isinstance(network_request.received_content_destination, NoContentRequested):
        return _REACHED
    return _RECEIVED


def _is_target_named_by_package_names_text(
    package_names_text: str | None, network_request: NetworkRequest
) -> bool:
    """Tell whether a line names the package that a request asks for, both read by `parse_package_names_text`, e.g. `requests` in `Requirement already satisfied: requests in /usr/lib` and `pip install requests`."""
    target = network_request.target
    if (
        package_names_text is None
        or not _has_package_name_target(network_request)
        or not isinstance(target, str)
    ):
        return False
    line_package_names = parse_package_names_text(package_names_text)
    target_package_names = parse_package_names_text(target)
    return (
        not isinstance(line_package_names, UnreadablePackageNamesText)
        and not isinstance(target_package_names, UnreadablePackageNamesText)
        and not line_package_names.isdisjoint(target_package_names)
    )


def _has_package_name_target(network_request: NetworkRequest) -> bool:
    """Tell whether a request asks for a package that its words name, e.g. `requests` of `pip install requests`, and not for a local path or the packages of a file, e.g. `pip install -e /app` or `pip install -r reqs.txt`."""
    return (
        isinstance(network_request.target_kind, NetworkRequestTargetKind)
        and network_request.target_kind == NetworkRequestTargetKind.PACKAGE_NAME
        and isinstance(network_request.target, str)
    )


def _is_line_of_pip_or_apt_alone(output_line_meaning: OutputLineMeaning) -> bool:
    """Tell whether only pip or only apt prints a line, e.g. `Successfully installed x-1.0` or `Setting up curl (7.88)`, as its pattern says."""
    return not output_line_meaning.is_printed_by_other_programs_too and (
        output_line_meaning.printing_programs
        in (frozenset({PrintingProgram.PIP}), frozenset({PrintingProgram.APT}))
    )


def _ends_with_exit_code_of_program(
    ran_command: RanCommand,
    program_invocation: ProgramInvocation | UnknownProgramInvocation,
) -> bool:
    """Tell whether a command ends with the exit code of one of its programs, i.e. every program outside it is known to end with the exit code of the next, e.g. sudo in `sudo curl u`."""
    outer_program_invocations = ran_command.program_invocations[
        : ran_command.program_invocations.index(program_invocation)
    ]
    return all(
        isinstance(outer_program_invocation, ProgramInvocation)
        and outer_program_invocation.exits_with_exit_code_of_next_program is True
        for outer_program_invocation in outer_program_invocations
    )


def _are_requests_of_one_command(network_requests: Sequence[NetworkRequest]) -> bool:
    """Tell whether requests all come from one command of one call, itself or by the code it ran, e.g. the two of `pip install a b`."""
    return (
        len(
            {
                (
                    network_request.tool_call_key,
                    command_id_of_network_request(network_request),
                )
                for network_request in network_requests
            }
        )
        == 1
        and command_id_of_network_request(network_requests[0]) is not None
    )


def _has_other_request_in_call(
    network_request: NetworkRequest, network_requests: Sequence[NetworkRequest]
) -> bool:
    """Tell whether the call of a request made another request too, e.g. `pip install A B`."""
    return any(
        other_network_request.tool_call_key == network_request.tool_call_key
        for other_network_request in network_requests
        if other_network_request != network_request
    )


def _is_written_by_another_request(
    written_file: WrittenFile,
    network_request: NetworkRequest,
    network_requests: Sequence[NetworkRequest],
) -> bool:
    """Tell whether a command of another request of the same call writes the file too."""
    writer_command_ids = {writer.command_id for writer in written_file.writers}
    return any(
        other_network_request.tool_call_key == network_request.tool_call_key
        and command_id_of_network_request(other_network_request) in writer_command_ids
        for other_network_request in network_requests
        if other_network_request != network_request
    )


def _output_line_evidence_of_stopping_line(
    output_line_owners: OutputLineOwners,
) -> OutputLineEvidence:
    """Give the evidence of a line of command a for the request of command b that a stopped, which no other request shares since it is about b."""
    output_line_with_meaning = output_line_owners.output_line_with_meaning
    return OutputLineEvidence(
        showing_tool_call_key=output_line_with_meaning.showing_tool_call_key,
        line_index=output_line_with_meaning.line_index,
        line_index_in_json_string=output_line_with_meaning.line_index_in_json_string,
        kind=output_line_with_meaning.output_line_meaning.kind,
        is_shared_with_other_requests=False,
    )


def _deciding_command_ids_of(
    ran_commands: Sequence[RanCommand], command_id: int
) -> frozenset[int]:
    """Find the ids of the commands whose failure shows that a command did not run, e.g. the id of a for b in `a && b` but not for c in `a || b && c`, none when either may be read with a wrong structure."""
    ran_command_by_id = {
        ran_command.shell_command.id: ran_command for ran_command in ran_commands
    }
    shell_command = ran_command_by_id[command_id].shell_command
    if shell_command.structure_may_be_wrong:
        return frozenset()
    return frozenset(
        deciding_command_id
        for deciding_command_id in stopping_command_ids_of(
            shell_command, ran_commands
        )
        if deciding_command_id in ran_command_by_id
        and not ran_command_by_id[
            deciding_command_id
        ].shell_command.structure_may_be_wrong
    )


def _execution_status_of(expanded_tool_call: ExpandedToolCall) -> ExecutionStatus:
    """Find the end state of a call's work, from its command text when it has one and else from its result, `UNKNOWN` without either."""
    if expanded_tool_call.command_text_status is not None:
        return expanded_tool_call.command_text_status.execution_status
    if expanded_tool_call.tool_call.result is not None:
        return expanded_tool_call.tool_call.result.execution_status
    return ExecutionStatus.UNKNOWN


def _call_text_ran_commands_of(
    expanded_tool_call: ExpandedToolCall,
) -> tuple[RanCommand, ...]:
    """List the commands of the text of the call itself, without those of files, heredocs or `bash -c` arguments that it runs."""
    return tuple(
        ran_command
        for ran_text in expanded_tool_call.ran_texts
        if isinstance(ran_text, RanShellText)
        and isinstance(ran_text.source, CallCommandText)
        for ran_command in ran_text.ran_commands
    )
