"""Tests for the checks that the types of network_request/model.py make when they are built or read as true or false."""

import itertools

import pytest

from tb_internet_use.expanded_tool_call.model import (
    ArgumentText,
    CallCommandText,
    CodeLanguage,
    ProgramInvocation,
    UnknownProgramInvocation,
)
from tb_internet_use.network_request.model import (
    CodeCall,
    CodeCallEffect,
    CodeCallLabel,
    ContentShownInResult,
    FromCode,
    FromCommand,
    FromWebTool,
    NetworkRequest,
    NetworkRequestCertainty,
    NetworkRequestSource,
    NetworkRequestTargetKind,
    NetworkRequestUncertaintyReason,
    TargetNotation,
    UnknownCodeCall,
    UnknownNetworkRequestTarget,
    UnknownNetworkRequestTargetKind,
    UnknownNetworkRequestTargetReason,
    UnknownProgramNetworkRequestLabel,
    UnreadableCodeCallArguments,
)
from tb_internet_use.tool_call.model import HarnessTool, ToolCallKey

TOOL_CALL_KEY = ToolCallKey("trial", "main", 1, 0)
CURL_INVOCATION = ProgramInvocation(
    program_name="curl",
    subcommand_words=(),
    options=(),
    arguments=("https://a.org/x",),
    gets_more_arguments_at_run_time=False,
    unread_words=(),
    exits_with_exit_code_of_next_program=False,
)
MYTOOL_INVOCATION = UnknownProgramInvocation("mytool", ("https://a.org/x",))
CURL_SOURCE = FromCommand(0, CallCommandText(), CURL_INVOCATION)
CONFIRMED = NetworkRequestCertainty.CONFIRMED
UNCERTAIN = NetworkRequestCertainty.UNCERTAIN
UNKNOWN_PROGRAM = NetworkRequestUncertaintyReason.UNKNOWN_PROGRAM
UNREAD_WORDS = NetworkRequestUncertaintyReason.UNREAD_WORDS
UNKNOWN_OPTION_EFFECT = NetworkRequestUncertaintyReason.UNKNOWN_OPTION_EFFECT
UNKNOWN_CODE_CALL = NetworkRequestUncertaintyReason.UNKNOWN_CODE_CALL
URL_OUTSIDE_CODE_CALL = NetworkRequestUncertaintyReason.URL_OUTSIDE_CODE_CALL
PROGRAM_RUN_BY_CODE = NetworkRequestUncertaintyReason.PROGRAM_RUN_BY_CODE
FETCHES_ONLY_WHAT_IS_MISSING = (
    NetworkRequestUncertaintyReason.FETCHES_ONLY_WHAT_IS_MISSING
)
# One source of each kind that gives requests of different reasons.
SOURCES_BY_NAME: dict[str, NetworkRequestSource] = {
    "command of a program with a row": CURL_SOURCE,
    "command of a program without a row": FromCommand(
        0, CallCommandText(), MYTOOL_INVOCATION
    ),
    "code call with a row": FromCode(
        0, ArgumentText(0), CodeLanguage.PYTHON, "subprocess.run"
    ),
    "code without a known call": FromCode(
        0, ArgumentText(0), CodeLanguage.PYTHON, UnknownCodeCall()
    ),
    "web tool": FromWebTool(None, HarnessTool("claude-code", "WebFetch")),
}
# The reasons that `extract_network_requests` gives a request of each source, None for a confirmed request, written out by hand.
ACCEPTED_UNCERTAINTY_REASONS_OF_SOURCE: dict[
    str, set[NetworkRequestUncertaintyReason | None]
] = {
    # `curl u`, `curl --foo x u`, `curl -L u` without an option row, `npx tsc`, and a program that the request catalog has no row for, e.g. `python -m ensurepip https://a.org/x`.
    "command of a program with a row": {
        None,
        UNREAD_WORDS,
        UNKNOWN_OPTION_EFFECT,
        FETCHES_ONLY_WHAT_IS_MISSING,
        UNKNOWN_PROGRAM,
    },
    # `mytool https://a.org/x`.
    "command of a program without a row": {UNKNOWN_PROGRAM},
    # `requests.get(u)`, `subprocess.run(["pip", "install", "x"])` and a program without a row that code runs, e.g. `subprocess.run(["mytool", u])`.
    "code call with a row": {None, PROGRAM_RUN_BY_CODE, UNKNOWN_PROGRAM},
    # `mylib.fetch(u)` and `URL = u`.
    "code without a known call": {UNKNOWN_CODE_CALL, URL_OUTSIDE_CODE_CALL},
    # Every web tool request is confirmed.
    "web tool": {None},
}


def build_network_request(
    source: NetworkRequestSource,
    certainty: NetworkRequestCertainty,
    uncertainty_reason: NetworkRequestUncertaintyReason | None,
) -> NetworkRequest:
    return NetworkRequest(
        tool_call_key=TOOL_CALL_KEY,
        index_in_tool_call=0,
        source=source,
        target="https://a.org/x",
        target_kind=NetworkRequestTargetKind.URL,
        host_names=("a.org",),
        received_content_destination=ContentShownInResult(),
        certainty=certainty,
        uncertainty_reason=uncertainty_reason,
    )


@pytest.mark.parametrize(
    ("certainty", "uncertainty_reason", "is_accepted"),
    [
        (CONFIRMED, None, True),
        (UNCERTAIN, FETCHES_ONLY_WHAT_IS_MISSING, True),
        (UNCERTAIN, None, False),
        (CONFIRMED, FETCHES_ONLY_WHAT_IS_MISSING, False),
    ],
)
def test_network_request_has_an_uncertainty_reason_exactly_when_it_is_uncertain(
    certainty: NetworkRequestCertainty,
    uncertainty_reason: NetworkRequestUncertaintyReason | None,
    is_accepted: bool,
):
    if is_accepted:
        request = build_network_request(CURL_SOURCE, certainty, uncertainty_reason)
        assert request.uncertainty_reason == uncertainty_reason
    else:
        with pytest.raises(ValueError):
            build_network_request(CURL_SOURCE, certainty, uncertainty_reason)


@pytest.mark.parametrize(
    ("source_name", "uncertainty_reason"),
    list(itertools.product(SOURCES_BY_NAME, [None, *NetworkRequestUncertaintyReason])),
)
def test_network_request_accepts_only_the_uncertainty_reasons_that_its_source_can_give(
    source_name: str, uncertainty_reason: NetworkRequestUncertaintyReason | None
):
    source = SOURCES_BY_NAME[source_name]
    certainty = CONFIRMED if uncertainty_reason is None else UNCERTAIN
    if uncertainty_reason in ACCEPTED_UNCERTAINTY_REASONS_OF_SOURCE[source_name]:
        request = build_network_request(source, certainty, uncertainty_reason)
        assert (request.source, request.uncertainty_reason) == (
            source,
            uncertainty_reason,
        )
    else:
        with pytest.raises(ValueError):
            build_network_request(source, certainty, uncertainty_reason)


@pytest.mark.parametrize(
    "unknown_value",
    [
        UnknownNetworkRequestTarget(UnknownNetworkRequestTargetReason.NAMED_IN_FILE),
        UnknownNetworkRequestTargetKind(),
        UnknownProgramNetworkRequestLabel(),
    ],
)
def test_unknown_value_that_stands_beside_none_or_a_bool_refuses_to_be_read_as_true_or_false(
    unknown_value: object,
):
    with pytest.raises(TypeError):
        bool(unknown_value)


@pytest.mark.parametrize(
    ("effect", "target_notation", "target_kind", "is_accepted"),
    [
        (
            CodeCallEffect.SENDS_NETWORK_REQUEST,
            TargetNotation.URL,
            NetworkRequestTargetKind.URL,
            True,
        ),
        # A row of a call that sends one may leave the kind blank, e.g. `from_pretrained`.
        (
            CodeCallEffect.SENDS_NETWORK_REQUEST,
            TargetNotation.NAME,
            UnknownNetworkRequestTargetKind(),
            True,
        ),
        (
            CodeCallEffect.SENDS_NETWORK_REQUEST,
            None,
            NetworkRequestTargetKind.URL,
            False,
        ),
        (CodeCallEffect.SENDS_NETWORK_REQUEST, TargetNotation.URL, None, False),
        (
            CodeCallEffect.HOLDS_NETWORK_REQUEST_TARGET,
            TargetNotation.URL,
            NetworkRequestTargetKind.URL,
            True,
        ),
        (CodeCallEffect.HOLDS_NETWORK_REQUEST_TARGET, None, None, False),
        (CodeCallEffect.RUNS_PROGRAM, None, None, True),
        (CodeCallEffect.RUNS_PROGRAM, TargetNotation.URL, None, False),
        (CodeCallEffect.SENDS_NO_NETWORK_REQUEST, None, None, True),
        (
            CodeCallEffect.SENDS_NO_NETWORK_REQUEST,
            None,
            NetworkRequestTargetKind.URL,
            False,
        ),
    ],
)
def test_code_call_label_has_a_target_notation_and_kind_exactly_when_the_call_sends_a_request(
    effect: CodeCallEffect,
    target_notation: TargetNotation | None,
    target_kind: NetworkRequestTargetKind | UnknownNetworkRequestTargetKind | None,
    is_accepted: bool,
):
    if is_accepted:
        label = CodeCallLabel(
            "requests.get", effect, target_notation, target_kind, "requests"
        )
        assert label.target_kind == target_kind
    else:
        with pytest.raises(ValueError):
            CodeCallLabel(
                "requests.get", effect, target_notation, target_kind, "requests"
            )


@pytest.mark.parametrize(
    "values_read_from_arguments",
    [
        (("https://a.org/x",), None, None, None, None),
        ((), "https://a.org/x", None, None, None),
        ((), None, "URL", None, None),
        ((), None, None, "BASE", None),
        ((), None, None, None, 1),
    ],
)
def test_code_call_with_unreadable_arguments_holds_no_values_read_from_them(
    values_read_from_arguments: tuple[
        tuple[str, ...], str | None, str | None, str | None, int | None
    ],
):
    empty_call = CodeCall(
        "requests.get", UnreadableCodeCallArguments(), (), None, None, None, None
    )
    assert empty_call.string_literals == ()
    with pytest.raises(ValueError):
        CodeCall(
            "requests.get", UnreadableCodeCallArguments(), *values_read_from_arguments
        )
    # The same values are kept when the arguments could be read.
    call = CodeCall("requests.get", '"https://a.org/x"', *values_read_from_arguments)
    assert call.string_literals == values_read_from_arguments[0]
