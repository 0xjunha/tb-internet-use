"""Decide the owners of each output line of one trial, i.e. the requests among those whose output reaches the result that shows the line and whose run can have printed it.

A line is evidence only of a request that can have printed it, e.g. `Successfully installed x-1.0` in the result of `pip install x; ls` belongs to the request of pip, and one `Could not resolve host` line under `curl a; curl b` belongs to both requests.
A line that no request owns makes no request. It is counted by the reason it gave no evidence, e.g. `Downloading torch-2.3.0.whl` in the result of `./setup.sh`, whose text the trial does not hold.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from tb_internet_use.expanded_tool_call.model import (
    ArgumentText,
    ExpandedToolCall,
    FileText,
    FileTextWithoutKnownWriter,
    PollInputText,
    RanCommand,
    RanShellText,
    StdinText,
    UnknownProgramInvocation,
    UnknownRanText,
)
from tb_internet_use.network_request.model import (
    FromCode,
    FromCommand,
    FromWebTool,
    NetworkRequest,
    NetworkRequestTargetKind,
)
from tb_internet_use.network_request_result.model import (
    OutputLineKind,
    OutputLineMeaning,
    OutputLineOwners,
    OutputLineWithMeaning,
    OutputPlaceSourceCommands,
    OutputPlaceSources,
    ProgramOutputLines,
    UnknownProgramOutputLines,
    UnreadablePackageNamesText,
    UnusedOutputLineReason,
)
from tb_internet_use.network_request_result.parse_package_names_text import (
    parse_package_names_text,
)
from tb_internet_use.tool_call.model import ExitOutcome, ToolCallKey

if TYPE_CHECKING:
    # The door is passed in and named in annotations only, so that this module never loads `knowledge/` itself.
    from tb_internet_use.knowledge.network_request_result_knowledge import (
        NetworkRequestResultKnowledge,
    )

# The reasons under which a line without an owner is also counted by the programs that reach its place.
_REASONS_COUNTED_BY_PROGRAM = frozenset(
    {
        UnusedOutputLineReason.NO_UNKNOWN_RUN,
        UnusedOutputLineReason.UNOWNED_LINE_IN_UNKNOWN_RUN,
    }
)


def decide_output_line_owners(
    output_place_sources: Sequence[OutputPlaceSources],
    output_lines_with_meaning: Sequence[OutputLineWithMeaning],
    expanded_tool_calls: Sequence[ExpandedToolCall],
    network_requests: Sequence[NetworkRequest],
    *,
    knowledge: NetworkRequestResultKnowledge,
    unused_output_line_counts: Counter[tuple[UnusedOutputLineReason, OutputLineKind]],
    program_counts_of_unowned_output_lines: Counter[
        tuple[UnusedOutputLineReason, OutputLineKind, str]
    ],
) -> tuple[OutputLineOwners, ...]:
    """Decide the owners of each of `output_lines_with_meaning`, one `OutputLineOwners` per line in their order, with no owner when no request can have printed it.

    The owners are the requests whose output reaches the place of the line and whose run can print it.
    Those whose target the line contradicts are left out when another of them has the package or host of the line, e.g. the request of `b.org` alone for `Could not resolve host: b.org` under `curl a.org; curl b.org`.
    When none of them has it, all stay owners, and the line names another target when it contradicts one of them, e.g. `Downloading B-1.0.whl` under `pip install A`.
    One owner makes the line evidence of that request alone, and several make it evidence they share.
    A line without an owner adds one to `unused_output_line_counts` under its reason and kind, unless it shows that a command with a request did not run, e.g. `rg: command not found` before `&& pip install y`.
    Under `NO_UNKNOWN_RUN` and `UNOWNED_LINE_IN_UNKNOWN_RUN` it also adds one to `program_counts_of_unowned_output_lines` for each program name that `_program_names_of_unowned_output_line` gives.
    """
    expanded_tool_call_by_key = {
        expanded_tool_call.tool_call.harness_tool_call.key: expanded_tool_call
        for expanded_tool_call in expanded_tool_calls
    }
    call_index_by_key = {
        tool_call_key: call_index
        for call_index, tool_call_key in enumerate(expanded_tool_call_by_key)
    }
    output_place_sources_by_key = {
        output_place_sources_of_call.showing_tool_call_key: output_place_sources_of_call
        for output_place_sources_of_call in output_place_sources
    }
    reaching_network_requests_by_key: dict[ToolCallKey, tuple[NetworkRequest, ...]] = {}
    output_line_owners: list[OutputLineOwners] = []
    for output_line_with_meaning in output_lines_with_meaning:
        showing_tool_call_key = output_line_with_meaning.showing_tool_call_key
        place = output_place_sources_by_key.get(showing_tool_call_key)
        owner_network_requests: tuple[NetworkRequest, ...] = ()
        names_another_target = False
        if place is not None:
            if showing_tool_call_key not in reaching_network_requests_by_key:
                reaching_network_requests_by_key[showing_tool_call_key] = (
                    network_requests_of_output_place(
                        place, network_requests, call_index_by_key
                    )
                )
            output_line_meaning = output_line_with_meaning.output_line_meaning
            printing_network_requests = tuple(
                network_request
                for network_request in reaching_network_requests_by_key[
                    showing_tool_call_key
                ]
                if _may_print_output_line(
                    network_request,
                    output_line_meaning,
                    expanded_tool_call_by_key[network_request.tool_call_key],
                    knowledge=knowledge,
                )
            )
            owner_network_requests, names_another_target = (
                _keep_network_requests_that_output_line_can_name(
                    output_line_meaning, printing_network_requests
                )
            )
        output_line_owners.append(
            OutputLineOwners(
                output_line_with_meaning, owner_network_requests, names_another_target
            )
        )
        if not owner_network_requests:
            _count_unowned_output_line(
                output_line_with_meaning,
                place,
                expanded_tool_call_by_key,
                network_requests,
                unused_output_line_counts=unused_output_line_counts,
                program_counts_of_unowned_output_lines=program_counts_of_unowned_output_lines,
            )
    return tuple(output_line_owners)


def stopped_command_ids_from_missing_program_line(
    missing_program_word: str, ran_commands: Sequence[RanCommand]
) -> tuple[int, ...]:
    """Find the ids of the commands of one call that run only if a command whose program the line says is missing succeeds, e.g. the id of `pip install y` for `rg: command not found` and `rg x && pip install y`.

    A program that is not installed ends every command that runs it with a code other than 0, so the line shows that each such command failed, wherever its own output went.
    `ran_commands` are all commands of one call that is a source of the place of the line, as `RanShellText.ran_commands` holds them, so that the ids of `runs_if` point into them.
    A command whose `structure_may_be_wrong` is set neither stops another nor is stopped, since its `runs_if` may be wrong.
    The ids are in the order of `ran_commands`.
    """
    failed_command_ids = {
        ran_command.shell_command.id
        for ran_command in ran_commands
        if not ran_command.shell_command.structure_may_be_wrong
        and is_missing_program_of_command(missing_program_word, ran_command)
    }
    return tuple(
        ran_command.shell_command.id
        for ran_command in ran_commands
        if not ran_command.shell_command.structure_may_be_wrong
        and any(
            run_condition.required_outcome_of_deciding_commands == ExitOutcome.SUCCESS
            and not failed_command_ids.isdisjoint(run_condition.deciding_command_ids)
            for run_condition in ran_command.shell_command.runs_if
        )
    )


def has_unknown_run_beside(
    network_request: NetworkRequest,
    output_place_sources: OutputPlaceSources,
    expanded_tool_call_by_key: Mapping[ToolCallKey, ExpandedToolCall],
) -> bool:
    """Tell whether a run whose lines are not known can print into a place beside the run of a request, so that a line that any program prints there may not be the request's.

    That is a source command of the place other than the request's own command that runs a program no fact covers or a text the trial does not hold, e.g. `./test.sh` beside `curl -s u` in `curl -s u; ./test.sh`.
    It is also a program of the request's own command other than the request's program that no fact covers, or a text of that command that the trial does not hold, e.g. `tsc` of the request of `npx tsc`.
    """
    own_command_id = command_id_of_network_request(network_request)
    for output_place_source_commands in output_place_sources.source_commands:
        expanded_tool_call = expanded_tool_call_by_key[
            output_place_source_commands.tool_call_key
        ]
        ran_command_by_id = _ran_command_by_id_of(expanded_tool_call)
        unknown_runner_command_ids = _unknown_runner_command_ids_of(expanded_tool_call)
        if any(
            _is_unknown_run(ran_command_by_id[command_id], unknown_runner_command_ids)
            for command_id in output_place_source_commands.command_ids
            if not (
                output_place_source_commands.tool_call_key
                == network_request.tool_call_key
                and command_id == own_command_id
            )
        ):
            return True
    if own_command_id is None:
        return False
    own_expanded_tool_call = expanded_tool_call_by_key[network_request.tool_call_key]
    own_ran_command = _ran_command_by_id_of(own_expanded_tool_call)[own_command_id]
    other_program_invocations = list(own_ran_command.program_invocations)
    source = network_request.source
    if (
        isinstance(source, FromCommand)
        and source.program_invocation in other_program_invocations
    ):
        other_program_invocations.remove(source.program_invocation)
    return any(
        isinstance(program_invocation, UnknownProgramInvocation)
        for program_invocation in other_program_invocations
    ) or own_command_id in _unknown_runner_command_ids_of(own_expanded_tool_call)


def network_requests_of_output_place(
    output_place_sources: OutputPlaceSources,
    network_requests: Sequence[NetworkRequest],
    call_index_by_key: Mapping[ToolCallKey, int],
) -> tuple[NetworkRequest, ...]:
    """Find the requests whose output reaches a place, in the order of `network_requests`, `call_index_by_key` giving the 0-based order of each call in the trial.

    A request of a command or of code that a command ran reaches it when that command is among the source commands of its call, e.g. curl of `curl u > log` reaches the place of `cat log`.
    A request of code typed through a poll is matched by `_is_output_place_reached_by_typed_code`, since no command of the typing call ran that code.
    A request of a web tool reaches only the result of its own call made only of web tool actions, since a web step of a tool script prints nothing into the result of the script.
    """
    command_ids_by_key = {
        output_place_source_commands.tool_call_key: frozenset(
            output_place_source_commands.command_ids
        )
        for output_place_source_commands in output_place_sources.source_commands
    }
    reaching_network_requests: list[NetworkRequest] = []
    for network_request in network_requests:
        source = network_request.source
        if isinstance(source, FromWebTool):
            if (
                output_place_sources.is_web_tool_result
                and source.step_index is None
                and network_request.tool_call_key
                == output_place_sources.showing_tool_call_key
            ):
                reaching_network_requests.append(network_request)
            continue
        if isinstance(source, FromCode) and source.runner_command_id is None:
            if _is_output_place_reached_by_typed_code(
                network_request, source, output_place_sources, call_index_by_key
            ):
                reaching_network_requests.append(network_request)
            continue
        if command_id_of_network_request(network_request) in command_ids_by_key.get(
            network_request.tool_call_key, frozenset()
        ):
            reaching_network_requests.append(network_request)
    return tuple(reaching_network_requests)


def _is_output_place_reached_by_typed_code(
    network_request: NetworkRequest,
    source: FromCode,
    output_place_sources: OutputPlaceSources,
    call_index_by_key: Mapping[ToolCallKey, int],
) -> bool:
    """Tell whether the output of code typed through a poll reaches a place, i.e. the place is the result of the typing call or a later result whose sources include the call that started the polled handle.

    The program that took the code is a command of that starting call, so its output shows where the output of the starting call shows, e.g. call 2 types `requests.get(u)` into `python3` of call 1, and the poll of call 3 shows output of call 1.
    A result before the typing call cannot show what the code printed, e.g. the result of call 1 itself.
    """
    typing_tool_call_key = network_request.tool_call_key
    if output_place_sources.showing_tool_call_key == typing_tool_call_key:
        return True
    code_text_source = source.code_text_source
    if (
        not isinstance(code_text_source, PollInputText)
        or code_text_source.starter_tool_call_key is None
    ):
        return False
    return call_index_by_key[
        output_place_sources.showing_tool_call_key
    ] > call_index_by_key[typing_tool_call_key] and any(
        output_place_source_commands.tool_call_key
        == code_text_source.starter_tool_call_key
        for output_place_source_commands in output_place_sources.source_commands
    )


def _may_print_output_line(
    network_request: NetworkRequest,
    output_line_meaning: OutputLineMeaning,
    expanded_tool_call: ExpandedToolCall,
    *,
    knowledge: NetworkRequestResultKnowledge,
) -> bool:
    """Tell whether the run of a request can print a line, `expanded_tool_call` being the call of the request.

    A line of a missing program is printed for the command whose program word it names, e.g. `pip3: command not found` for `pip3 install x`.
    A bare number is printed only by a run that the door says prints a status code, e.g. `curl -w "%{http_code}" u`, so a run whose lines are not known prints none.
    A run whose lines are not known can print any other line, since the door does not know that it cannot.
    A run that the door says prints no line of a pattern prints none of them, e.g. `getent hosts a.org`, which shows only entries of the hosts database, beside the `HTTP/1.1 405` of `curl -i` in the same result.
    Any other line that any program prints can be printed by any other run, and a line that only some programs print needs one of them among the printing programs of the run.
    A request of a web tool can print every line of its result, which is read with the web tool result patterns only.
    """
    source = network_request.source
    if isinstance(source, FromWebTool):
        return True
    if output_line_meaning.kind == OutputLineKind.PROGRAM_MISSING:
        own_command_id = command_id_of_network_request(network_request)
        return (
            own_command_id is not None
            and output_line_meaning.missing_program_word is not None
            and is_missing_program_of_command(
                output_line_meaning.missing_program_word,
                _ran_command_by_id_of(expanded_tool_call)[own_command_id],
            )
        )
    if output_line_meaning.kind == OutputLineKind.BARE_STATUS_CODE:
        program_output_lines = program_output_lines_of(
            source, expanded_tool_call, knowledge=knowledge
        )
        return (
            isinstance(program_output_lines, ProgramOutputLines)
            and program_output_lines.prints_status_code
        )
    program_output_lines = program_output_lines_of(
        source, expanded_tool_call, knowledge=knowledge
    )
    if isinstance(program_output_lines, UnknownProgramOutputLines):
        return True
    if not program_output_lines.printing_programs:
        return False
    if output_line_meaning.is_printed_by_other_programs_too:
        return True
    return not output_line_meaning.printing_programs.isdisjoint(
        program_output_lines.printing_programs
    )


def program_output_lines_of(
    source: FromCommand | FromCode,
    expanded_tool_call: ExpandedToolCall,
    *,
    knowledge: NetworkRequestResultKnowledge,
) -> ProgramOutputLines | UnknownProgramOutputLines:
    """Find the lines that the run of a request prints, asking the door about the program of a command, or about the last program of the command that ran the code of a request in code, e.g. python of `python get.py`.

    A program that no fact covers and one with unread words are not asked about, since the door has no row for them.
    Code typed through a poll is not asked about, since the trajectory does not say which command of the starting call took it.
    """
    if isinstance(source, FromCommand):
        program_invocation = source.program_invocation
    else:
        if source.runner_command_id is None:
            return UnknownProgramOutputLines()
        program_invocations = _ran_command_by_id_of(expanded_tool_call)[
            source.runner_command_id
        ].program_invocations
        if not program_invocations:
            return UnknownProgramOutputLines()
        program_invocation = program_invocations[-1]
    if (
        isinstance(program_invocation, UnknownProgramInvocation)
        or program_invocation.unread_words
    ):
        return UnknownProgramOutputLines()
    return knowledge.program_output_lines(program_invocation)


def _keep_network_requests_that_output_line_can_name(
    output_line_meaning: OutputLineMeaning,
    network_requests: tuple[NetworkRequest, ...],
) -> tuple[tuple[NetworkRequest, ...], bool]:
    """Keep the requests whose target a line does not contradict when one of them is named by the line, else keep all with whether the line names another target.

    The package names of a line contradict a request for a package that is not among them, e.g. `Downloading B-1.0.whl` and the request of `pip install A`.
    The host of a line contradicts a request whose words name hosts that differ from it, e.g. `Could not resolve host: a.org` and the request of `curl https://b.org/y`.
    A request whose words name no package or no host is not compared on that, e.g. `apt-get install x` with the host of `Get:1 http://archive.ubuntu.com/ubuntu jammy/main amd64 x amd64 1.0 [10 kB]`.
    Contradicted requests are dropped only when a kept request has the line's package or host, e.g. `curl https://b.org/y` for `Could not resolve host: b.org` under `curl https://a.org/x; curl https://b.org/y`.
    Otherwise every request can have printed the line and all are kept, and the line names another target when it contradicts any of them, e.g. `Could not resolve host: cdn.b.net` under `curl https://a.org/x -o x; pip install y`.
    A line under visible commands that names another target is evidence of their requests and no new request, shared when several can have printed it.
    """
    kept_network_requests = tuple(
        network_request
        for network_request in network_requests
        if not _is_target_contradicted_by_output_line(
            output_line_meaning, network_request
        )
    )
    if len(kept_network_requests) == len(network_requests):
        return network_requests, False
    if any(
        _is_target_named_by_output_line(output_line_meaning, network_request)
        for network_request in kept_network_requests
    ):
        return kept_network_requests, False
    return network_requests, True


def _is_target_contradicted_by_output_line(
    output_line_meaning: OutputLineMeaning, network_request: NetworkRequest
) -> bool:
    """Tell whether the package names or the host of a line differ from those that a request names.

    Package names are compared as `parse_package_names_text` spells them, and a text of the line or the target that it cannot read contradicts nothing. Host names are compared in lowercase.
    """
    package_names_pair = _package_names_of_line_and_target(
        output_line_meaning, network_request
    )
    if package_names_pair is not None and package_names_pair[0].isdisjoint(
        package_names_pair[1]
    ):
        return True
    if output_line_meaning.host_name_text is not None and network_request.host_names:
        return not _is_host_of_line_among_host_names(
            output_line_meaning.host_name_text, network_request.host_names
        )
    return False


def _is_target_named_by_output_line(
    output_line_meaning: OutputLineMeaning, network_request: NetworkRequest
) -> bool:
    """Tell whether a line has a package name or the host that a request names, e.g. `Could not resolve host: b.org` and the request of `curl https://b.org/y`, compared as in `_is_target_contradicted_by_output_line`."""
    package_names_pair = _package_names_of_line_and_target(
        output_line_meaning, network_request
    )
    if package_names_pair is not None and not package_names_pair[0].isdisjoint(
        package_names_pair[1]
    ):
        return True
    return output_line_meaning.host_name_text is not None and (
        _is_host_of_line_among_host_names(
            output_line_meaning.host_name_text, network_request.host_names
        )
    )


def _package_names_of_line_and_target(
    output_line_meaning: OutputLineMeaning, network_request: NetworkRequest
) -> tuple[frozenset[str], frozenset[str]] | None:
    """Find the package names of a line and of the target of a request for a package, as `parse_package_names_text` spells them, or None when either has none or cannot be read."""
    target = network_request.target
    if (
        output_line_meaning.package_names_text is None
        or not isinstance(network_request.target_kind, NetworkRequestTargetKind)
        or network_request.target_kind != NetworkRequestTargetKind.PACKAGE_NAME
        or not isinstance(target, str)
    ):
        return None
    line_package_names = parse_package_names_text(
        output_line_meaning.package_names_text
    )
    target_package_names = parse_package_names_text(target)
    if isinstance(line_package_names, UnreadablePackageNamesText) or isinstance(
        target_package_names, UnreadablePackageNamesText
    ):
        return None
    return line_package_names, target_package_names


def _is_host_of_line_among_host_names(
    host_name_text: str, host_names: Sequence[str]
) -> bool:
    """Tell whether the host of a line is one of the host names of a request, in lowercase."""
    return host_name_text.lower() in {host_name.lower() for host_name in host_names}


def _count_unowned_output_line(
    output_line_with_meaning: OutputLineWithMeaning,
    output_place_sources: OutputPlaceSources | None,
    expanded_tool_call_by_key: Mapping[ToolCallKey, ExpandedToolCall],
    network_requests: Sequence[NetworkRequest],
    *,
    unused_output_line_counts: Counter[tuple[UnusedOutputLineReason, OutputLineKind]],
    program_counts_of_unowned_output_lines: Counter[
        tuple[UnusedOutputLineReason, OutputLineKind, str]
    ],
) -> None:
    """Count a line without an owner under its reason and kind, and under each program name that reaches its place when the reason is one counted by program."""
    unused_output_line_reason = _unused_output_line_reason_of(
        output_line_with_meaning,
        output_place_sources,
        expanded_tool_call_by_key,
        network_requests,
    )
    if unused_output_line_reason is None:
        return
    output_line_kind = output_line_with_meaning.output_line_meaning.kind
    unused_output_line_counts[unused_output_line_reason, output_line_kind] += 1
    if unused_output_line_reason not in _REASONS_COUNTED_BY_PROGRAM:
        return
    assert output_place_sources is not None
    for program_name in _program_names_of_unowned_output_line(
        unused_output_line_reason, output_place_sources, expanded_tool_call_by_key
    ):
        program_counts_of_unowned_output_lines[
            unused_output_line_reason, output_line_kind, program_name
        ] += 1


def _unused_output_line_reason_of(
    output_line_with_meaning: OutputLineWithMeaning,
    output_place_sources: OutputPlaceSources | None,
    expanded_tool_call_by_key: Mapping[ToolCallKey, ExpandedToolCall],
    network_requests: Sequence[NetworkRequest],
) -> UnusedOutputLineReason | None:
    """Find the reason a line without an owner gave no evidence, taking the first that holds in a fixed order, or None when the line shows that a command with a request did not run.

    The order is no output place, then a place that may show file content or page text, then a missing program of a command without a request, then a bare number, then a place that no unknown run reaches.
    A line in a place that an unknown run reaches is left last, e.g. `Downloading torch-2.3.0.whl` in the result of `./setup.sh`.
    The case of None comes before the content of a file or a page, since such a line is the evidence of the stopped command, e.g. `rg: command not found` before `&& pip install y`, and a line is either evidence or counted once.
    """
    if output_place_sources is None:
        return UnusedOutputLineReason.NOT_AN_OUTPUT_PLACE
    output_line_meaning = output_line_with_meaning.output_line_meaning
    missing_program_word = (
        output_line_meaning.missing_program_word
        if output_line_meaning.kind == OutputLineKind.PROGRAM_MISSING
        else None
    )
    if missing_program_word is not None and _has_stopped_command_with_network_request(
        missing_program_word,
        output_place_sources,
        expanded_tool_call_by_key,
        network_requests,
    ):
        return None
    if output_place_sources.may_show_file_content:
        return UnusedOutputLineReason.FILE_CONTENT
    if output_place_sources.may_show_page_text:
        return UnusedOutputLineReason.PAGE_TEXT
    if (
        missing_program_word is not None
        and _has_missing_program_of_command_without_network_request(
            missing_program_word,
            output_place_sources,
            expanded_tool_call_by_key,
            network_requests,
        )
    ):
        return UnusedOutputLineReason.MISSING_PROGRAM_OF_COMMAND_WITHOUT_REQUEST
    if output_line_meaning.kind == OutputLineKind.BARE_STATUS_CODE:
        return UnusedOutputLineReason.STATUS_CODE_NOT_PRINTED_BY_RUN
    if not any(
        _has_unknown_run(
            output_place_source_commands,
            expanded_tool_call_by_key[output_place_source_commands.tool_call_key],
        )
        for output_place_source_commands in output_place_sources.source_commands
    ):
        return UnusedOutputLineReason.NO_UNKNOWN_RUN
    return UnusedOutputLineReason.UNOWNED_LINE_IN_UNKNOWN_RUN


def _has_stopped_command_with_network_request(
    missing_program_word: str,
    output_place_sources: OutputPlaceSources,
    expanded_tool_call_by_key: Mapping[ToolCallKey, ExpandedToolCall],
    network_requests: Sequence[NetworkRequest],
) -> bool:
    """Tell whether a line of a missing program stopped a command with a request in a call that is a source of the place, e.g. `pip install y` of `rg x && pip install y`."""
    for output_place_source_commands in output_place_sources.source_commands:
        tool_call_key = output_place_source_commands.tool_call_key
        stopped_command_ids = stopped_command_ids_from_missing_program_line(
            missing_program_word,
            ran_commands_of(expanded_tool_call_by_key[tool_call_key]),
        )
        if any(
            _has_network_request(tool_call_key, command_id, network_requests)
            for command_id in stopped_command_ids
        ):
            return True
    return False


def _has_missing_program_of_command_without_network_request(
    missing_program_word: str,
    output_place_sources: OutputPlaceSources,
    expanded_tool_call_by_key: Mapping[ToolCallKey, ExpandedToolCall],
    network_requests: Sequence[NetworkRequest],
) -> bool:
    """Tell whether a line of a missing program names the program word of a source command of the place that has no request, e.g. `rg: command not found` under `rg foo`."""
    for output_place_source_commands in output_place_sources.source_commands:
        tool_call_key = output_place_source_commands.tool_call_key
        ran_command_by_id = _ran_command_by_id_of(
            expanded_tool_call_by_key[tool_call_key]
        )
        if any(
            is_missing_program_of_command(
                missing_program_word, ran_command_by_id[command_id]
            )
            and not _has_network_request(tool_call_key, command_id, network_requests)
            for command_id in output_place_source_commands.command_ids
        ):
            return True
    return False


def _has_network_request(
    tool_call_key: ToolCallKey,
    command_id: int,
    network_requests: Sequence[NetworkRequest],
) -> bool:
    """Tell whether a command of a call made a request, itself or by the code it ran."""
    return any(
        network_request.tool_call_key == tool_call_key
        and command_id_of_network_request(network_request) == command_id
        for network_request in network_requests
    )


def is_missing_program_of_command(
    missing_program_word: str, ran_command: RanCommand
) -> bool:
    """Tell whether the word of a line of a missing program is a program word of a command, both without their folder, e.g. `pip3` of `bash: pip3: command not found` and of `pip3 install x`.

    The program words are the first word of the command and each word that is, without its folder, the name of one of its program invocations, e.g. pip in `python -m pip install x`.
    A word that `expand_tool_calls` reads under another name is no program word unless it comes first, e.g. pip3 in `sudo pip3 install x`, whose program invocation is named pip.
    """
    words = ran_command.shell_command.words
    if not words:
        return False
    program_names = {
        program_invocation.program_name
        for program_invocation in ran_command.program_invocations
    }
    missing_program_name = _word_without_folder(missing_program_word)
    return missing_program_name == _word_without_folder(words[0]) or any(
        _word_without_folder(word) == missing_program_name
        and missing_program_name in program_names
        for word in words[1:]
    )


def _word_without_folder(word: str) -> str:
    """Find the part of a word after its last `/`, e.g. x of `/opt/tool/bin/x`, or the word as written when nothing follows the `/`, e.g. `dir/`."""
    return word.rsplit("/", 1)[-1] or word


def _has_unknown_run(
    output_place_source_commands: OutputPlaceSourceCommands,
    expanded_tool_call: ExpandedToolCall,
) -> bool:
    """Tell whether a source command of a place, in its call `expanded_tool_call`, runs a program that no fact covers or a text that the trial does not hold, e.g. `./setup.sh` or `bash setup.sh` when no call wrote setup.sh.

    A command whose output does not reach the place is no source and is not asked about, e.g. `./setup.sh > /dev/null`. A source without commands, e.g. a tool script without command steps, has no unknown run.
    """
    ran_command_by_id = _ran_command_by_id_of(expanded_tool_call)
    unknown_runner_command_ids = _unknown_runner_command_ids_of(expanded_tool_call)
    return any(
        _is_unknown_run(ran_command_by_id[command_id], unknown_runner_command_ids)
        for command_id in output_place_source_commands.command_ids
    )


def _is_unknown_run(
    ran_command: RanCommand, unknown_runner_command_ids: frozenset[int]
) -> bool:
    """Tell whether a command runs a program that no fact covers or runs a text that the trial does not hold, given the ids of the commands of its call that run such a text."""
    return ran_command.shell_command.id in unknown_runner_command_ids or any(
        isinstance(program_invocation, UnknownProgramInvocation)
        for program_invocation in ran_command.program_invocations
    )


def _program_names_of_unowned_output_line(
    unused_output_line_reason: UnusedOutputLineReason,
    output_place_sources: OutputPlaceSources,
    expanded_tool_call_by_key: Mapping[ToolCallKey, ExpandedToolCall],
) -> frozenset[str]:
    """Find the program names under which a line without an owner is counted, i.e. the name of the last program invocation of each source command of its place, or of each one with an unknown run under `UNOWNED_LINE_IN_UNKNOWN_RUN`.

    A command that ran code is counted under the program that ran it, e.g. python of `python get.py`, and `./setup.sh` under setup.sh.
    A place without such a command, e.g. the result of a tool script without command steps, gives the empty name.
    """
    program_names: set[str] = set()
    for output_place_source_commands in output_place_sources.source_commands:
        expanded_tool_call = expanded_tool_call_by_key[
            output_place_source_commands.tool_call_key
        ]
        ran_command_by_id = _ran_command_by_id_of(expanded_tool_call)
        unknown_runner_command_ids = _unknown_runner_command_ids_of(expanded_tool_call)
        for command_id in output_place_source_commands.command_ids:
            ran_command = ran_command_by_id[command_id]
            if (
                unused_output_line_reason
                == UnusedOutputLineReason.UNOWNED_LINE_IN_UNKNOWN_RUN
                and not _is_unknown_run(ran_command, unknown_runner_command_ids)
            ):
                continue
            if ran_command.program_invocations:
                program_names.add(ran_command.program_invocations[-1].program_name)
    return frozenset(program_names) or frozenset({""})


def command_id_of_network_request(network_request: NetworkRequest) -> int | None:
    """Find the id of the command in the call of a request that made it, itself or by the code it ran, or None for code typed through a poll and for a web tool."""
    source = network_request.source
    if isinstance(source, FromCommand):
        return source.command_id
    if isinstance(source, FromCode):
        return source.runner_command_id
    return None


def ran_commands_of(expanded_tool_call: ExpandedToolCall) -> tuple[RanCommand, ...]:
    """List the commands of every shell text that a call ran, in the order of its texts."""
    return tuple(
        ran_command
        for ran_text in expanded_tool_call.ran_texts
        if isinstance(ran_text, RanShellText)
        for ran_command in ran_text.ran_commands
    )


def _ran_command_by_id_of(
    expanded_tool_call: ExpandedToolCall,
) -> dict[int, RanCommand]:
    """Find each command of a call by its id, which is unique within the call."""
    return {
        ran_command.shell_command.id: ran_command
        for ran_command in ran_commands_of(expanded_tool_call)
    }


def _unknown_runner_command_ids_of(
    expanded_tool_call: ExpandedToolCall,
) -> frozenset[int]:
    """Find the ids of the commands of a call that run a text the trial does not hold, e.g. `bash setup.sh` when no call wrote setup.sh."""
    return frozenset(
        ran_text.source.runner_command_id
        for ran_text in expanded_tool_call.ran_texts
        if isinstance(ran_text, UnknownRanText)
        and isinstance(
            ran_text.source,
            FileText | FileTextWithoutKnownWriter | StdinText | ArgumentText,
        )
    )
