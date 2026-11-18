"""Extract the network requests of one shell command, asking for each of its programs, the outermost first, whether it fetches and for which targets.

One command can run several programs, e.g. `sudo curl u` or `npx -y playwright install chromium`, and each is asked on its own.
A program that runs another one whose text the trial holds gives no request itself, e.g. sudo in `sudo curl u` or bash in `bash fetch.sh`, since the program it runs gives them.
"""

from collections import Counter
from collections.abc import Sequence
from typing import TYPE_CHECKING

from tb_internet_use.expanded_tool_call.model import (
    ArgumentText,
    ExpandedToolCall,
    FileText,
    ProgramInvocation,
    RanCodeText,
    RanCommand,
    RanShellText,
    RanText,
    RanTextSource,
    StdinText,
    UnknownProgramInvocation,
    VariableValues,
)
from tb_internet_use.network_request._extract_network_request_targets import (
    extract_network_request_targets,
    fill_variables_of_word,
)
from tb_internet_use.network_request._extract_received_content_destination import (
    extract_received_content_destination,
)
from tb_internet_use.network_request.judgment_rules import (
    treat_dotted_host_name_as_public,
    treat_single_label_or_templated_host_name_as_possibly_public,
)
from tb_internet_use.network_request.model import (
    FetchingProgramLabel,
    FromCommand,
    HostNameScope,
    NetworkRequest,
    NetworkRequestCertainty,
    NetworkRequestTargetKind,
    NetworkRequestUncertaintyReason,
    NoNetworkRequestReason,
    NonFetchingProgramLabel,
    ProgramOptionEffect,
    UnknownHostNameScopeReason,
    UnknownNetworkRequestTarget,
    UnknownNetworkRequestTargetReason,
    UnknownProgramNetworkRequestLabel,
    UnknownProgramOptionEffect,
    UnknownReceivedContentDestination,
)
from tb_internet_use.network_request.parse_host_name import (
    TEMPLATE_CHARACTER,
    parse_host_name,
)
from tb_internet_use.network_request.parse_url import parse_url
from tb_internet_use.network_request.parse_urls_in_text import parse_urls_in_text

if TYPE_CHECKING:
    # The door is passed in and named in annotations only, so that this module never loads `knowledge/` itself.
    from tb_internet_use.knowledge.network_request_knowledge import (
        NetworkRequestKnowledge,
    )


def extract_command_network_requests(
    ran_command: RanCommand,
    ran_text_source: RanTextSource,
    expanded_tool_call: ExpandedToolCall,
    first_index_in_tool_call: int,
    *,
    knowledge: NetworkRequestKnowledge,
    judgment_rule_use_counts: Counter[str],
    no_network_request_counts: Counter[NoNetworkRequestReason],
) -> tuple[NetworkRequest, ...]:
    """Extract the requests of the programs of one command, the outermost first, numbering them in the call from `first_index_in_tool_call` on.

    | Program | Requests |
    |---|---|
    | No fact of `expand_tool_calls` covers it, and it runs a text that the trial holds, e.g. `./fetch.sh https://a.org/x` after another call wrote fetch.sh | none, since the commands of the text give them |
    | No fact of `expand_tool_calls` covers it otherwise, e.g. `mytool https://a.org/x` | one uncertain request per URL in its words that may be public or whose host cannot be read |
    | The request catalog says it does not fetch, e.g. `echo https://a.org` | none |
    | No row of the request catalog, and it runs a next program or a text that the trial holds, e.g. sudo in `sudo curl u` | none, since what it runs gives them |
    | No row of the request catalog otherwise, e.g. `bash setup.sh https://a.org/x` for a setup.sh that the trial does not hold | one uncertain request per URL in its words that may be public |
    | The request catalog says it fetches, e.g. `curl u` | one request per target that its words show, and one for those they do not show |

    Every program run that gives no request adds one to `no_network_request_counts` under its reason.
    """
    command_id = ran_command.shell_command.id
    network_requests: list[NetworkRequest] = []
    for position, program_invocation in enumerate(ran_command.program_invocations):
        next_index_in_tool_call = first_index_in_tool_call + len(network_requests)
        if isinstance(program_invocation, UnknownProgramInvocation):
            if _has_ran_text(command_id, expanded_tool_call.ran_texts):
                no_network_request_counts[
                    NoNetworkRequestReason.PROGRAM_RUNS_SOMETHING_ELSE
                ] += 1
                continue
            network_requests += _extract_public_url_network_requests(
                program_invocation,
                program_invocation.words,
                ran_command,
                ran_text_source,
                expanded_tool_call,
                next_index_in_tool_call,
                judgment_rule_use_counts=judgment_rule_use_counts,
                no_network_request_counts=no_network_request_counts,
            )
            continue
        next_program_invocations = ran_command.program_invocations[position + 1 :]
        program_network_request_label = knowledge.program_network_request_label(
            program_invocation
        )
        match program_network_request_label:
            case NonFetchingProgramLabel():
                no_network_request_counts[
                    NoNetworkRequestReason.NON_FETCHING_PROGRAM
                ] += 1
            case FetchingProgramLabel():
                network_requests += _extract_program_network_requests(
                    program_invocation,
                    program_network_request_label,
                    next_program_invocations[0].program_name
                    if next_program_invocations
                    else None,
                    ran_command,
                    ran_text_source,
                    expanded_tool_call,
                    next_index_in_tool_call,
                    knowledge=knowledge,
                    judgment_rule_use_counts=judgment_rule_use_counts,
                    no_network_request_counts=no_network_request_counts,
                )
            case UnknownProgramNetworkRequestLabel():
                if next_program_invocations or _has_ran_text(
                    command_id, expanded_tool_call.ran_texts
                ):
                    no_network_request_counts[
                        NoNetworkRequestReason.PROGRAM_RUNS_SOMETHING_ELSE
                    ] += 1
                    continue
                network_requests += _extract_public_url_network_requests(
                    program_invocation,
                    _words_of_program_invocation(program_invocation),
                    ran_command,
                    ran_text_source,
                    expanded_tool_call,
                    next_index_in_tool_call,
                    judgment_rule_use_counts=judgment_rule_use_counts,
                    no_network_request_counts=no_network_request_counts,
                )
    return tuple(network_requests)


def _extract_program_network_requests(
    program_invocation: ProgramInvocation,
    fetching_program_label: FetchingProgramLabel,
    next_program_name: str | None,
    ran_command: RanCommand,
    ran_text_source: RanTextSource,
    expanded_tool_call: ExpandedToolCall,
    first_index_in_tool_call: int,
    *,
    knowledge: NetworkRequestKnowledge,
    judgment_rule_use_counts: Counter[str],
    no_network_request_counts: Counter[NoNetworkRequestReason],
) -> tuple[NetworkRequest, ...]:
    """Extract the requests of a program that the request catalog says fetches, e.g. three for `pip install A B C` and none for `curl --version`.

    An option that sends no request gives none. Unread words give one request whose target and content destination are unknown, e.g. `curl --foo x u`, since the unread option may name the target or a file.
    Otherwise `extract_network_request_targets` gives the targets, and no target means no request, e.g. `curl` alone.
    A request is uncertain when an option has no row of the request catalog, e.g. `curl -L u` without a row of `-L`, or else when the program or an option fetches only what is missing, e.g. `npx tsc`.
    """
    program_option_effects = _program_option_effects_of(program_invocation, knowledge)
    if ProgramOptionEffect.SENDS_NO_REQUEST in program_option_effects:
        no_network_request_counts[NoNetworkRequestReason.OPTION_SENDS_NO_REQUEST] += 1
        return ()
    source = FromCommand(
        ran_command.shell_command.id, ran_text_source, program_invocation
    )
    tool_call_key = expanded_tool_call.tool_call.harness_tool_call.key
    if program_invocation.unread_words:
        return (
            NetworkRequest(
                tool_call_key,
                first_index_in_tool_call,
                source,
                UnknownNetworkRequestTarget(
                    UnknownNetworkRequestTargetReason.UNREAD_WORDS
                ),
                fetching_program_label.target_kind,
                _host_names_from_words(
                    (*program_invocation.arguments, *program_invocation.unread_words),
                    ran_command.variable_values,
                ),
                UnknownReceivedContentDestination(),
                NetworkRequestCertainty.UNCERTAIN,
                NetworkRequestUncertaintyReason.UNREAD_WORDS,
            ),
        )
    network_request_targets = extract_network_request_targets(
        program_invocation,
        fetching_program_label,
        program_option_effects,
        next_program_name,
        ran_command.variable_values,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )
    if not network_request_targets:
        no_network_request_counts[NoNetworkRequestReason.NO_TARGET_ARGUMENTS] += 1
        return ()
    uncertainty_reason = _uncertainty_reason_of(
        fetching_program_label, program_option_effects
    )
    received_content_destination = extract_received_content_destination(
        fetching_program_label.content_route,
        program_option_effects,
        program_invocation,
        ran_command,
        expanded_tool_call.written_files,
        len(network_request_targets),
    )
    return tuple(
        NetworkRequest(
            tool_call_key,
            first_index_in_tool_call + target_index,
            source,
            target,
            target_kind,
            host_names,
            received_content_destination,
            NetworkRequestCertainty.CONFIRMED
            if uncertainty_reason is None
            else NetworkRequestCertainty.UNCERTAIN,
            uncertainty_reason,
        )
        for target_index, (target, target_kind, host_names) in enumerate(
            network_request_targets
        )
    )


def _extract_public_url_network_requests(
    program_invocation: ProgramInvocation | UnknownProgramInvocation,
    words: Sequence[str],
    ran_command: RanCommand,
    ran_text_source: RanTextSource,
    expanded_tool_call: ExpandedToolCall,
    first_index_in_tool_call: int,
    *,
    judgment_rule_use_counts: Counter[str],
    no_network_request_counts: Counter[NoNetworkRequestReason],
) -> tuple[NetworkRequest, ...]:
    """Extract one uncertain request per URL that may be public in the words of a program that no fact says fetches, e.g. `mytool https://a.org/x`, and none for `mytool sync` or `mytool http://localhost:8000/x`.

    The target is the URL with the variables of one literal value filled in, and the host is the one it writes, also a template such as `$HOST`.
    A URL whose host cannot be read also gives a request, with no host, e.g. `mytool http://[::1/x`, since what it reaches is unknown.
    """
    public_urls = _public_urls_from_words(
        words, ran_command.variable_values, judgment_rule_use_counts
    )
    if not public_urls:
        no_network_request_counts[NoNetworkRequestReason.NO_URL_THAT_MAY_BE_PUBLIC] += 1
        return ()
    source = FromCommand(
        ran_command.shell_command.id, ran_text_source, program_invocation
    )
    tool_call_key = expanded_tool_call.tool_call.harness_tool_call.key
    return tuple(
        NetworkRequest(
            tool_call_key,
            first_index_in_tool_call + url_index,
            source,
            public_url,
            NetworkRequestTargetKind.URL,
            _host_names_of_url(public_url),
            UnknownReceivedContentDestination(),
            NetworkRequestCertainty.UNCERTAIN,
            NetworkRequestUncertaintyReason.UNKNOWN_PROGRAM,
        )
        for url_index, public_url in enumerate(public_urls)
    )


def _program_option_effects_of(
    program_invocation: ProgramInvocation, knowledge: NetworkRequestKnowledge
) -> tuple[ProgramOptionEffect | UnknownProgramOptionEffect, ...]:
    """Give the answer of the door for each option of a program, in the order of its options, e.g. `NONE` for `-o` of `curl -o a.tgz u`."""
    return tuple(
        knowledge.program_option_effect(program_invocation, program_option)
        for program_option in program_invocation.options
    )


def _uncertainty_reason_of(
    fetching_program_label: FetchingProgramLabel,
    program_option_effects: Sequence[ProgramOptionEffect | UnknownProgramOptionEffect],
) -> NetworkRequestUncertaintyReason | None:
    """Give why the requests of a fetching program are uncertain, an option without a row before fetching only what is missing, or None when they are confirmed."""
    if any(
        isinstance(program_option_effect, UnknownProgramOptionEffect)
        for program_option_effect in program_option_effects
    ):
        return NetworkRequestUncertaintyReason.UNKNOWN_OPTION_EFFECT
    if (
        fetching_program_label.fetches_only_what_is_missing
        or ProgramOptionEffect.FETCHES_ONLY_WHAT_IS_MISSING in program_option_effects
    ):
        return NetworkRequestUncertaintyReason.FETCHES_ONLY_WHAT_IS_MISSING
    return None


def _has_ran_text(command_id: int, ran_texts: Sequence[RanText]) -> bool:
    """Tell whether the command runs a shell or code text that the trial holds, e.g. the fetch.sh of `bash fetch.sh` after another call wrote it, as opposed to an unknown one such as a setup.sh of the task image."""
    return any(
        isinstance(ran_text, RanShellText | RanCodeText)
        and isinstance(ran_text.source, FileText | StdinText | ArgumentText)
        and ran_text.source.runner_command_id == command_id
        for ran_text in ran_texts
    )


def _words_of_program_invocation(
    program_invocation: ProgramInvocation,
) -> tuple[str, ...]:
    """Give the words of a program that may hold a URL, i.e. its option values, then its arguments, then its unread words."""
    return (
        *(
            program_option.value
            for program_option in program_invocation.options
            if program_option.value is not None
        ),
        *program_invocation.arguments,
        *program_invocation.unread_words,
    )


def _public_urls_from_words(
    words: Sequence[str],
    variable_values: Sequence[VariableValues],
    judgment_rule_use_counts: Counter[str],
) -> tuple[str, ...]:
    """Find the URLs in words that may be public or whose host cannot be read, each once, after filling in the variables of one literal value, e.g. `https://a.org/x` for `https://$U/x` after `U=a.org`."""
    single_value_by_name = _single_value_by_name_of(variable_values)
    urls = tuple(
        dict.fromkeys(
            url
            for word in words
            for url in parse_urls_in_text(
                fill_variables_of_word(word, single_value_by_name)
            )
        )
    )
    public_urls = set(urls_that_may_be_public(urls, judgment_rule_use_counts))
    return tuple(url for url in urls if url in public_urls or parse_url(url) is None)


def urls_that_may_be_public(
    urls: Sequence[str], judgment_rule_use_counts: Counter[str]
) -> tuple[str, ...]:
    """Find the URLs whose host is public or may be, e.g. `https://a.org/x`, `http://db:5432` and `https://$HOST/x` but not `http://localhost:8000/x` or `https://example.com`.

    A host that the standards settle is kept when public. A dotted name that they do not settle is kept when `treat_dotted_host_name_as_public` reads it as public, and a single label or a template when `treat_single_label_or_templated_host_name_as_possibly_public` says it may be.
    A URL whose host cannot be read is not kept, e.g. `http://[::1/x`.
    """
    return tuple(
        url
        for url in urls
        if (host_name := parse_url(url)) is not None
        and _may_host_name_be_public(host_name, judgment_rule_use_counts)
    )


def _may_host_name_be_public(
    host_name: str, judgment_rule_use_counts: Counter[str]
) -> bool:
    """Tell whether a host name is public by the standards or by the rules of `judgment_rules.py`, e.g. True for `files.acme.org` and `db`, False for `127.0.0.1`."""
    host_name_scope = parse_host_name(host_name)
    if isinstance(host_name_scope, HostNameScope):
        return host_name_scope == HostNameScope.PUBLIC
    if host_name_scope.reason == UnknownHostNameScopeReason.DOTTED_NAME:
        return (
            treat_dotted_host_name_as_public(
                host_name_scope, use_counts=judgment_rule_use_counts
            )
            == HostNameScope.PUBLIC
        )
    return treat_single_label_or_templated_host_name_as_possibly_public(
        host_name_scope, use_counts=judgment_rule_use_counts
    )


def _host_names_from_words(
    words: Sequence[str], variable_values: Sequence[VariableValues]
) -> tuple[str, ...]:
    """Find the hosts that the URLs in words write, each once, leaving out a host that holds a value set when it runs, e.g. `a.org` for `https://a.org/$F` and none for `https://$H/x`."""
    single_value_by_name = _single_value_by_name_of(variable_values)
    return tuple(
        dict.fromkeys(
            host_name
            for word in words
            for url in parse_urls_in_text(
                fill_variables_of_word(word, single_value_by_name)
            )
            if (host_name := parse_url(url)) is not None
            and not TEMPLATE_CHARACTER.search(host_name)
        )
    )


def _host_names_of_url(url: str) -> tuple[str, ...]:
    """Give the host that a URL writes, or none when it cannot be read."""
    host_name = parse_url(url)
    return () if host_name is None else (host_name,)


def _single_value_by_name_of(
    variable_values: Sequence[VariableValues],
) -> dict[str, str]:
    """Give the value of each variable that has one literal value and no value set when it runs, e.g. `a.org` for `U` after `U=a.org`."""
    return {
        assigned_variable_values.name: assigned_variable_values.values[0]
        for assigned_variable_values in variable_values
        if len(assigned_variable_values.values) == 1
        and not assigned_variable_values.has_value_set_at_run_time
    }
