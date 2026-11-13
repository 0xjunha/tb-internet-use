"""Extract the candidate requests of each call from its commands, code and web tool actions, before any output is read."""

from tb_internet_use.interpret.callrun.model import CallRun, RanCommand
from tb_internet_use.interpret.request._code_requests import code_request
from tb_internet_use.interpret.request._program_options import option_facts
from tb_internet_use.interpret.request._program_rules import matched_request_rule
from tb_internet_use.interpret.request._targets import (
    asked_package_names,
    request_hosts,
    request_targets,
)
from tb_internet_use.interpret.request.model import (
    CandidateRequest,
    FromCommand,
    FromWebTool,
    RequestTarget,
)
from tb_internet_use.network.hosts import host_from_name, host_name_in_url
from tb_internet_use.parse.program.catalog_rows import last_program_words
from tb_internet_use.parse.program.model import RequestKind
from tb_internet_use.parse.shell.programs import (
    gets_arguments_at_run_time,
    program_words,
)
from tb_internet_use.parse.toolcall.model import (
    Action,
    ToolCallKey,
    WebFetchAction,
    WebFindAction,
    WebSearchAction,
    action_steps_with_index,
)


def extract_candidate_requests(call_run: CallRun) -> tuple[CandidateRequest, ...]:
    """Extract the candidate requests of one call, from its commands in id order, then its code texts, then its web tool steps."""
    call_key = call_run.call.raw.key
    ran_commands = [c for text in call_run.shell_texts for c in text.commands or ()]
    # The program that runs each code text, past programs that run the next program, e.g. python for `uv run python get.py`.
    program_name_of_command = {
        c.command.id: words[0]
        for c in ran_commands
        if (words := last_program_words(program_words(c.command)))
    }
    command_requests = [_command_request(call_key, c) for c in ran_commands]
    code_requests = [
        code_request(
            call_key, code, program_name_of_command.get(code.source.runner_command_id)
        )
        for code in call_run.code_texts
    ]
    web_tool_requests = [
        _web_tool_request(call_key, step_index, step)
        for step_index, step in action_steps_with_index(call_run.call.action)
    ]
    return tuple(
        request
        for request in (*command_requests, *code_requests, *web_tool_requests)
        if request is not None
    )


def _command_request(
    call_key: ToolCallKey, ran_command: RanCommand
) -> CandidateRequest | None:
    """Make the candidate request of a command whose program matches a request rule, if any.

    A run that only asks for help makes none, and so does a program that needs a target and has none, unless it gets them at run time, e.g. `xargs curl`.
    """
    command = ran_command.command
    match = matched_request_rule(program_words(command))
    if match is None:
        return None
    facts = option_facts(match.program_name, match.parsed_arguments, match.rule)
    if facts.sends_no_request:
        return None
    if (
        not match.target_words
        and not match.subcommand_words
        and not gets_arguments_at_run_time(command)
    ):
        return None
    rule = facts.rule
    targets = request_targets(match.target_words, ran_command.variable_values)
    hosts = request_hosts(match.program_name, rule.kind, targets, facts.index_urls)
    if rule.kind == RequestKind.REMOTE_HOST and not hosts:
        return None  # e.g. rsync between two local paths
    return CandidateRequest(
        call=call_key,
        source=FromCommand(command.id),
        kind=rule.kind,
        program_name=match.program_name,
        targets=targets,
        hosts=hosts,
        asked_package_names=asked_package_names(
            rule.asked_packages_source, targets, facts.names_packages_in_files
        ),
        printing_programs=rule.printing_programs
        | match.printing_programs_of_programs_running_it,
        fetches_only_to_run_or_build=rule.fetches_only_to_run_or_build,
        has_offline_option=facts.has_offline_option,
        exit_zero_means=rule.exit_zero_means,
        asks_for_no_content=rule.asks_for_no_content,
        prints_response_body=rule.prints_response_body,
        prints_status_code=facts.prints_status_code,
        quiet_progress_lines=facts.quiet_progress_lines,
        quiet_error_lines=facts.quiet_error_lines,
    )


def _web_tool_request(
    call_key: ToolCallKey, step_index: int | None, step: Action
) -> CandidateRequest | None:
    """Make the candidate request of a web search, fetch or find step, or None for another action."""
    match step:
        case WebSearchAction(queries=texts):
            kind = RequestKind.WEB_SEARCH
        case WebFetchAction(urls=texts):
            kind = RequestKind.WEB_FETCH
        case WebFindAction(urls=texts):
            kind = RequestKind.WEB_FIND
        case _:
            return None
    host_names = [name for text in texts if (name := host_name_in_url(text))]
    return CandidateRequest(
        call=call_key,
        source=FromWebTool(step_index),
        kind=kind,
        program_name=None,
        targets=tuple(RequestTarget(text, text, None) for text in texts),
        hosts=tuple(dict.fromkeys(map(host_from_name, host_names))),
        asked_package_names=frozenset(),
        printing_programs=frozenset(),
        fetches_only_to_run_or_build=False,
        has_offline_option=False,
        exit_zero_means=None,
        asks_for_no_content=False,
        prints_response_body=True,
        prints_status_code=False,
        quiet_progress_lines=False,
        quiet_error_lines=False,
    )
