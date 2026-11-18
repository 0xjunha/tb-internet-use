"""Extract the targets of the requests that one fetching program makes, one per target that its words show and one for the targets they do not show.

One command can ask for several targets, e.g. `pip install requests git+https://github.com/a/b` asks for a package and a repository.
A word can hold a variable, e.g. `pip install $p` in `for p in A B C`, so one written word can give a target per value.
"""

import re
from collections import Counter
from collections.abc import Mapping, Sequence

from tb_internet_use.expanded_tool_call.model import (
    ProgramInvocation,
    VariableValues,
)
from tb_internet_use.network_request.judgment_rules import (
    treat_values_outside_their_for_loop_as_one_request_each,
)
from tb_internet_use.network_request.model import (
    FetchingProgramLabel,
    NetworkRequestTargetKind,
    ProgramOptionEffect,
    TargetArguments,
    TargetWithoutTargetArguments,
    UnknownNetworkRequestTarget,
    UnknownNetworkRequestTargetReason,
    UnknownProgramOptionEffect,
)
from tb_internet_use.network_request.parse_target import parse_target
from tb_internet_use.network_request.parse_url import parse_url

# A variable written `$NAME` or `${NAME}`, which `VariableValues` can fill, e.g. `p` in `pip install $p` or `U` in `https://$U/x`.
_PLAIN_VARIABLE = re.compile(r"\$(?:\{(\w+)\}|(\w+))")
# A character that a shell expands when the command runs, left in a word after its plain variables are filled, e.g. in `$(cat f)`, `${U:-a.org}` or a backtick.
_RUN_TIME_EXPANSION_CHARACTER = re.compile(r"[$`]")

type _TargetWithKindAndHostNames = tuple[
    str | UnknownNetworkRequestTarget | None,
    NetworkRequestTargetKind,
    tuple[str, ...],
]


def extract_network_request_targets(
    program_invocation: ProgramInvocation,
    fetching_program_label: FetchingProgramLabel,
    program_option_effects: Sequence[ProgramOptionEffect | UnknownProgramOptionEffect],
    next_program_name: str | None,
    variable_values: Sequence[VariableValues],
    *,
    judgment_rule_use_counts: Counter[str],
) -> tuple[_TargetWithKindAndHostNames, ...]:
    """Extract the target, the target kind and the host names of each request of a fetching program, in the order of its target words, then the targets its words do not show.

    `program_option_effects` holds the answer of `NetworkRequestKnowledge` for each of `program_invocation.options`, in the same order.
    Each target word gives a request per value, e.g. three for `pip install $p` in `for p in A B C`, except that the local paths among them give one `LOCAL_PATH` request together, e.g. `pip install ./x.whl ./y.whl`.
    Then one `NAMED_IN_FILE` request stands for all the options whose value is a file of targets, e.g. `pip install -r a.txt -r b.txt`, and one `VALUE_SET_AT_RUN_TIME` request for the arguments the program gets when it runs, e.g. `xargs curl`.
    When none of these is there, the row says whether the program makes one request without a target, e.g. `apt-get update`, one whose targets a file names, e.g. `lake build`, or none, e.g. `curl` alone.
    The hosts that the options name, e.g. `pypi.org` of `pip install -i https://pypi.org/simple x`, are hosts of every request.

    The caller has already given no request for an option that sends none, e.g. `--help`, and one request with an unknown target for unread words, e.g. `curl --foo x u`, so `ValueError` is raised for an invocation with either.
    An option without a row of the catalog names no target and no host here, and the caller makes the requests uncertain.
    When no word names a target and the row gives no request then, e.g. `curl -K cfg`, such an option gives one request whose target is unknown, since its value may name one.
    """
    if program_invocation.unread_words:
        raise ValueError(
            f"{program_invocation.program_name} has unread words {program_invocation.unread_words}"
        )
    if ProgramOptionEffect.SENDS_NO_REQUEST in program_option_effects:
        raise ValueError(
            f"{program_invocation.program_name} has an option that sends no request"
        )
    option_effect_pairs = list(
        zip(program_invocation.options, program_option_effects, strict=True)
    )
    target_words = [
        *_target_arguments_of(
            program_invocation, fetching_program_label, next_program_name
        ),
        *(
            program_option.value
            for program_option, program_option_effect in option_effect_pairs
            if program_option_effect == ProgramOptionEffect.NAMES_TARGET_IN_VALUE
            and program_option.value is not None
        ),
    ]
    names_targets_in_file = any(
        program_option_effect == ProgramOptionEffect.NAMES_TARGETS_IN_FILE
        for _, program_option_effect in option_effect_pairs
    )
    option_host_names = tuple(
        host_name
        for program_option, program_option_effect in option_effect_pairs
        if program_option_effect == ProgramOptionEffect.NAMES_HOST_IN_VALUE
        and program_option.value is not None
        and (host_name := _host_name_of_url_word(program_option.value, variable_values))
        is not None
    )
    target_kind = fetching_program_label.target_kind
    if (
        not target_words
        and not names_targets_in_file
        and not program_invocation.gets_more_arguments_at_run_time
    ):
        return _targets_without_target_arguments(
            fetching_program_label,
            option_host_names,
            has_option_of_unknown_effect=any(
                isinstance(program_option_effect, UnknownProgramOptionEffect)
                for program_option_effect in program_option_effects
            ),
        )
    network_request_targets: list[_TargetWithKindAndHostNames] = []
    has_local_path = False
    for target_word in target_words:
        for target_value in _target_values_from_word(
            target_word, variable_values, judgment_rule_use_counts
        ):
            if isinstance(target_value, UnknownNetworkRequestTarget):
                word_host_name = _host_name_of_url_word(target_word, variable_values)
                network_request_targets.append(
                    (
                        target_value,
                        target_kind,
                        _join_host_names(word_host_name, option_host_names),
                    )
                )
                continue
            parsed_target = parse_target(
                target_value, fetching_program_label.target_notation
            )
            if parsed_target.is_local_path:
                has_local_path = True
                continue
            network_request_targets.append(
                (
                    target_value,
                    parsed_target.target_kind or target_kind,
                    _join_host_names(parsed_target.host_name, option_host_names),
                )
            )
    unknown_target_reasons = [
        *([UnknownNetworkRequestTargetReason.NAMED_IN_FILE] * names_targets_in_file),
        *([UnknownNetworkRequestTargetReason.LOCAL_PATH] * has_local_path),
        *(
            [UnknownNetworkRequestTargetReason.VALUE_SET_AT_RUN_TIME]
            * program_invocation.gets_more_arguments_at_run_time
        ),
    ]
    network_request_targets += [
        (UnknownNetworkRequestTarget(reason), target_kind, option_host_names)
        for reason in unknown_target_reasons
    ]
    return tuple(network_request_targets)


def _target_arguments_of(
    program_invocation: ProgramInvocation,
    fetching_program_label: FetchingProgramLabel,
    next_program_name: str | None,
) -> tuple[str, ...]:
    """Give the words that the row names as targets, e.g. all arguments of `pip install A B`, the first of `git clone u d` or the next program `tsc` of `npx tsc`."""
    match fetching_program_label.target_arguments:
        case TargetArguments.ALL:
            return program_invocation.arguments
        case TargetArguments.FIRST:
            return program_invocation.arguments[:1]
        case TargetArguments.NEXT_PROGRAM:
            return () if next_program_name is None else (next_program_name,)
        case TargetArguments.NONE:
            return ()


def _targets_without_target_arguments(
    fetching_program_label: FetchingProgramLabel,
    option_host_names: tuple[str, ...],
    *,
    has_option_of_unknown_effect: bool,
) -> tuple[_TargetWithKindAndHostNames, ...]:
    """Give the request that the row names for a run whose words name no target, e.g. one without a target for `apt-get update`, or none for `curl` alone.

    Where the row names none, an option of unknown effect gives one request with an unknown target, e.g. `curl -K cfg`, since the option may name the target.
    """
    target_kind = fetching_program_label.target_kind
    match fetching_program_label.target_without_target_arguments:
        case TargetWithoutTargetArguments.NO_TARGET:
            return ((None, target_kind, option_host_names),)
        case TargetWithoutTargetArguments.NAMED_IN_FILE:
            named_in_file = UnknownNetworkRequestTarget(
                UnknownNetworkRequestTargetReason.NAMED_IN_FILE
            )
            return ((named_in_file, target_kind, option_host_names),)
        case TargetWithoutTargetArguments.NO_REQUEST:
            if has_option_of_unknown_effect:
                unknown_option_effect = UnknownNetworkRequestTarget(
                    UnknownNetworkRequestTargetReason.UNKNOWN_OPTION_EFFECT
                )
                return ((unknown_option_effect, target_kind, option_host_names),)
            return ()


def _target_values_from_word(
    target_word: str,
    variable_values: Sequence[VariableValues],
    judgment_rule_use_counts: Counter[str],
) -> tuple[str | UnknownNetworkRequestTarget, ...]:
    """Fill in the variables of one target word, giving a target per value that the command runs with and an unknown target for a value set when it runs.

    A word without a variable is its own target. Variables of one value are filled in, e.g. `https://a.org/x` for `https://$U/x` after `U=a.org`.
    One variable of several values gives a target per value when it is the item of the innermost for loop around the command, e.g. `A`, `B` and `C` for `$p` in `for p in A B C`, and otherwise as many as `treat_values_outside_their_for_loop_as_one_request_each` gives.
    The target is one unknown target when a variable has no literal value, a command substitution or backtick is left, or two variables have several values, e.g. `$PKG`, `$(cat f)` or `$a-$b`.
    One unknown target is added after the literal ones when a variable of the word may also get a value set when it runs, e.g. `U=$(cat u.txt)`.
    """
    value_set_at_run_time = UnknownNetworkRequestTarget(
        UnknownNetworkRequestTargetReason.VALUE_SET_AT_RUN_TIME
    )
    if not _RUN_TIME_EXPANSION_CHARACTER.search(target_word):
        return (target_word,)
    variable_values_by_name = {
        assigned_variable_values.name: assigned_variable_values
        for assigned_variable_values in variable_values
    }
    # A variable of the word without values is left as written, so the check of the filled word below finds it.
    known_variable_values = [
        variable_values_by_name[name]
        for name in _variable_names_of(target_word)
        if name in variable_values_by_name
    ]
    variable_values_with_several_values = [
        assigned_variable_values
        for assigned_variable_values in known_variable_values
        if len(assigned_variable_values.values) > 1
    ]
    first_value_by_name = {
        assigned_variable_values.name: assigned_variable_values.values[0]
        for assigned_variable_values in known_variable_values
    }
    if len(
        variable_values_with_several_values
    ) > 1 or _RUN_TIME_EXPANSION_CHARACTER.search(
        fill_variables_of_word(target_word, first_value_by_name)
    ):
        return (value_set_at_run_time,)
    if not variable_values_with_several_values:
        values_of_requests = [fill_variables_of_word(target_word, first_value_by_name)]
    else:
        (several_valued_variable_values,) = variable_values_with_several_values
        values_of_variable = (
            several_valued_variable_values.values
            if several_valued_variable_values.takes_each_value_in_turn
            else treat_values_outside_their_for_loop_as_one_request_each(
                several_valued_variable_values, use_counts=judgment_rule_use_counts
            )
        )
        if not values_of_variable:
            return (value_set_at_run_time,)
        values_of_requests = [
            fill_variables_of_word(
                target_word,
                first_value_by_name | {several_valued_variable_values.name: value},
            )
            for value in values_of_variable
        ]
    if any(
        assigned_variable_values.has_value_set_at_run_time
        for assigned_variable_values in known_variable_values
    ):
        return (*values_of_requests, value_set_at_run_time)
    return tuple(values_of_requests)


def _host_name_of_url_word(
    word: str, variable_values: Sequence[VariableValues]
) -> str | None:
    """Find the host that a URL word writes, filling in the variables of one value that no run sets, e.g. `a.org` for `https://a.org/$F` and for `https://$U/x` after `U=a.org`.

    It is None when the word has no scheme or its host holds a value set when it runs, e.g. `https://$H/x` without a value of `H`, since only a host written in the text is a host of a request.
    """
    single_value_by_name = {
        assigned_variable_values.name: assigned_variable_values.values[0]
        for assigned_variable_values in variable_values
        if len(assigned_variable_values.values) == 1
        and not assigned_variable_values.has_value_set_at_run_time
    }
    filled_word = fill_variables_of_word(word, single_value_by_name)
    _, _, after_scheme = filled_word.partition("://")
    host_part = after_scheme.split("/", 1)[0]
    if _RUN_TIME_EXPANSION_CHARACTER.search(host_part):
        return None
    return parse_url(filled_word)


def _join_host_names(
    host_name: str | None, option_host_names: tuple[str, ...]
) -> tuple[str, ...]:
    """Give the host that a target writes, then the hosts its program's options name, each once."""
    return tuple(
        dict.fromkeys((*((host_name,) if host_name else ()), *option_host_names))
    )


def _variable_names_of(word: str) -> tuple[str, ...]:
    """Give the names that a word uses as `$NAME` or `${NAME}`, in order and each once."""
    return tuple(
        dict.fromkeys(
            match.group(1) or match.group(2) for match in _PLAIN_VARIABLE.finditer(word)
        )
    )


def fill_variables_of_word(word: str, value_by_name: Mapping[str, str]) -> str:
    """Fill in the variables of a word whose values are given, keeping the others as written, e.g. `a.org/x` for `$U/x`."""
    return _PLAIN_VARIABLE.sub(
        lambda match: value_by_name.get(
            match.group(1) or match.group(2), match.group(0)
        ),
        word,
    )
