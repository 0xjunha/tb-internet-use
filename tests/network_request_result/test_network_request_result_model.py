"""Tests for the checks that the types of network_request_result/model.py make when they are built."""

import itertools
from dataclasses import replace

import pytest

from tb_internet_use.expanded_tool_call.model import (
    CallCommandText,
    ProgramInvocation,
)
from tb_internet_use.network_request.model import (
    ContentShownInResult,
    FromCommand,
    NetworkRequest,
    NetworkRequestCertainty,
    NetworkRequestTargetKind,
    NetworkRequestUncertaintyReason,
    NoContentRequested,
    ReceivedContentDestination,
    UnknownReceivedContentDestination,
)
from tb_internet_use.network_request_result.model import (
    ExitCodeEvidence,
    JudgmentRuleAssumptionReason,
    NetworkRequestResult,
    NetworkRequestResultAssumptionReason,
    NetworkRequestResultCertainty,
    NetworkRequestResultEvidence,
    NetworkRequestResultLevel,
    NetworkRequestResultStopReason,
    OutputLineEvidence,
    OutputLineKind,
    SharedOutputLineAssumptionReason,
)
from tb_internet_use.tool_call.model import ToolCallKey

TOOL_CALL_KEY = ToolCallKey("trial", "main", 1, 0)
CONTENT_SHOWN_IN_RESULT = ContentShownInResult()
EXIT_CODE_EVIDENCE = ExitCodeEvidence(TOOL_CALL_KEY, 0, False)
# A `NOT_FOUND` line that only this request can have printed. `NetworkRequestResult` reads only that the line is not shared.
OWN_OUTPUT_LINE_EVIDENCE = OutputLineEvidence(
    TOOL_CALL_KEY, 0, None, OutputLineKind.NOT_FOUND, False
)
# `Could not resolve host` after `curl a; curl b`, a line that either request can have printed.
SHARED_OUTPUT_LINE_EVIDENCE = OutputLineEvidence(
    TOOL_CALL_KEY, 0, None, OutputLineKind.NAME_NOT_RESOLVED, True
)
NPX_INVOCATION = ProgramInvocation(
    program_name="npx",
    subcommand_words=(),
    options=(),
    arguments=("tsc",),
    gets_more_arguments_at_run_time=False,
    unread_words=(),
    exits_with_exit_code_of_next_program=False,
)
ATTEMPTED = NetworkRequestResultLevel.ATTEMPTED
EXECUTED = NetworkRequestResultLevel.EXECUTED
REACHED = NetworkRequestResultLevel.REACHED
RECEIVED = NetworkRequestResultLevel.RECEIVED
FAILED = NetworkRequestResultStopReason.FAILED
NOT_VISIBLE = NetworkRequestResultStopReason.NOT_VISIBLE
NOT_NEEDED = NetworkRequestResultStopReason.NOT_NEEDED
CONFIRMED = NetworkRequestCertainty.CONFIRMED
UNCERTAIN = NetworkRequestCertainty.UNCERTAIN
# The levels and stop reasons of a request that asks for content, written out by hand. It has no stop reason only at `RECEIVED`.
LEVELS_AND_STOP_REASONS_OF_REQUEST_FOR_CONTENT = {
    (RECEIVED, None),
    (REACHED, FAILED),
    (EXECUTED, FAILED),
    (ATTEMPTED, FAILED),
    (REACHED, NOT_VISIBLE),
    (EXECUTED, NOT_VISIBLE),
    (ATTEMPTED, NOT_VISIBLE),
    (EXECUTED, NOT_NEEDED),
}
# A request that asks for no content, e.g. `ping`, succeeds at `REACHED` and cannot receive content.
LEVELS_AND_STOP_REASONS_OF_REQUEST_FOR_NO_CONTENT = (
    LEVELS_AND_STOP_REASONS_OF_REQUEST_FOR_CONTENT - {(RECEIVED, None)}
) | {(REACHED, None)}


def build_network_request(
    *,
    certainty: NetworkRequestCertainty = CONFIRMED,
    received_content_destination: ReceivedContentDestination = CONTENT_SHOWN_IN_RESULT,
) -> NetworkRequest:
    return NetworkRequest(
        tool_call_key=TOOL_CALL_KEY,
        index_in_tool_call=0,
        source=FromCommand(0, CallCommandText(), NPX_INVOCATION),
        target="tsc",
        target_kind=NetworkRequestTargetKind.PACKAGE_NAME,
        host_names=(),
        received_content_destination=received_content_destination,
        certainty=certainty,
        uncertainty_reason=(
            None
            if certainty == CONFIRMED
            else NetworkRequestUncertaintyReason.FETCHES_ONLY_WHAT_IS_MISSING
        ),
    )


def build_network_request_result(
    network_request: NetworkRequest,
    *,
    request_certainty_after_evidence: NetworkRequestCertainty = CONFIRMED,
    level: NetworkRequestResultLevel = EXECUTED,
    stop_reason: NetworkRequestResultStopReason | None = NOT_VISIBLE,
    evidence: tuple[NetworkRequestResultEvidence, ...] = (EXIT_CODE_EVIDENCE,),
    level_certainty: NetworkRequestResultCertainty = NetworkRequestResultCertainty.CONFIRMED,
    assumption_reasons: tuple[NetworkRequestResultAssumptionReason, ...] = (),
) -> NetworkRequestResult:
    return NetworkRequestResult(
        network_request=network_request,
        request_certainty_after_evidence=request_certainty_after_evidence,
        level=level,
        stop_reason=stop_reason,
        level_certainty=level_certainty,
        evidence=evidence,
        assumption_reasons=assumption_reasons,
    )


@pytest.mark.parametrize(
    ("received_content_destination", "accepted_levels_and_stop_reasons"),
    [
        (ContentShownInResult(), LEVELS_AND_STOP_REASONS_OF_REQUEST_FOR_CONTENT),
        # A destination that is not known, e.g. of a request in code, succeeds only at `RECEIVED`.
        (
            UnknownReceivedContentDestination(),
            LEVELS_AND_STOP_REASONS_OF_REQUEST_FOR_CONTENT,
        ),
        (NoContentRequested(), LEVELS_AND_STOP_REASONS_OF_REQUEST_FOR_NO_CONTENT),
    ],
)
@pytest.mark.parametrize(
    ("level", "stop_reason"),
    list(
        itertools.product(
            NetworkRequestResultLevel, [None, *NetworkRequestResultStopReason]
        )
    ),
)
def test_network_request_result_accepts_a_stop_reason_only_where_the_request_can_stop_for_it(
    received_content_destination: ReceivedContentDestination,
    accepted_levels_and_stop_reasons: set[
        tuple[NetworkRequestResultLevel, NetworkRequestResultStopReason | None]
    ],
    level: NetworkRequestResultLevel,
    stop_reason: NetworkRequestResultStopReason | None,
):
    network_request = build_network_request(
        received_content_destination=received_content_destination
    )
    if (level, stop_reason) in accepted_levels_and_stop_reasons:
        result = build_network_request_result(
            network_request, level=level, stop_reason=stop_reason
        )
        assert (result.level, result.stop_reason) == (level, stop_reason)
    else:
        with pytest.raises(ValueError):
            build_network_request_result(
                network_request, level=level, stop_reason=stop_reason
            )


@pytest.mark.parametrize(
    ("level", "stop_reason", "is_accepted"),
    [
        # Nothing shows that it ran, e.g. `test -f x || curl -s u -o x`.
        (ATTEMPTED, NOT_VISIBLE, True),
        # A failure is recorded only with a trace of it, e.g. `pip: command not found`.
        (ATTEMPTED, FAILED, False),
        (EXECUTED, NOT_VISIBLE, False),
        (EXECUTED, FAILED, False),
        (EXECUTED, NOT_NEEDED, False),
        (REACHED, NOT_VISIBLE, False),
        (REACHED, FAILED, False),
        (RECEIVED, None, False),
    ],
)
def test_network_request_result_without_evidence_claims_no_level_above_attempted_and_no_failure(
    level: NetworkRequestResultLevel,
    stop_reason: NetworkRequestResultStopReason | None,
    is_accepted: bool,
):
    network_request = build_network_request()
    if is_accepted:
        result = build_network_request_result(
            network_request, level=level, stop_reason=stop_reason, evidence=()
        )
        assert result.evidence == ()
    else:
        with pytest.raises(ValueError):
            build_network_request_result(
                network_request, level=level, stop_reason=stop_reason, evidence=()
            )


def test_network_request_result_that_asks_for_no_content_and_reached_its_server_needs_evidence():
    network_request = build_network_request(
        received_content_destination=NoContentRequested()
    )

    with pytest.raises(ValueError):
        build_network_request_result(
            network_request, level=REACHED, stop_reason=None, evidence=()
        )


@pytest.mark.parametrize(
    ("certainty", "request_certainty_after_evidence", "evidence", "is_accepted"),
    [
        (CONFIRMED, CONFIRMED, (EXIT_CODE_EVIDENCE,), True),
        (UNCERTAIN, UNCERTAIN, (EXIT_CODE_EVIDENCE,), True),
        (UNCERTAIN, UNCERTAIN, (), True),
        (CONFIRMED, UNCERTAIN, (EXIT_CODE_EVIDENCE,), False),
        # An output line of this request alone lifts an uncertain request.
        (UNCERTAIN, CONFIRMED, (EXIT_CODE_EVIDENCE, OWN_OUTPUT_LINE_EVIDENCE), True),
        (UNCERTAIN, CONFIRMED, (), False),
        # Evidence that is no output line, or a line that another request can have printed, lifts nothing.
        (UNCERTAIN, CONFIRMED, (EXIT_CODE_EVIDENCE,), False),
        (UNCERTAIN, CONFIRMED, (SHARED_OUTPUT_LINE_EVIDENCE,), False),
    ],
)
def test_network_request_result_lifts_a_request_to_confirmed_only_by_an_output_line_of_its_own(
    certainty: NetworkRequestCertainty,
    request_certainty_after_evidence: NetworkRequestCertainty,
    evidence: tuple[NetworkRequestResultEvidence, ...],
    is_accepted: bool,
):
    network_request = build_network_request(certainty=certainty)
    # A result without evidence stays at `ATTEMPTED`, so that only the certainty decides.
    level = EXECUTED if evidence else ATTEMPTED
    if is_accepted:
        result = build_network_request_result(
            network_request,
            request_certainty_after_evidence=request_certainty_after_evidence,
            evidence=evidence,
            level=level,
        )
        assert result.request_certainty_after_evidence == (
            request_certainty_after_evidence
        )
    else:
        with pytest.raises(ValueError):
            build_network_request_result(
                network_request,
                request_certainty_after_evidence=request_certainty_after_evidence,
                evidence=evidence,
                level=level,
            )


def test_network_request_result_never_lifts_a_request_of_the_last_known_content_of_a_file():
    """An output line of its own, which would lift `npx tsc`, does not lift it, since the file may hold other content whose run printed the line."""
    network_request = replace(
        build_network_request(certainty=UNCERTAIN),
        uncertainty_reason=NetworkRequestUncertaintyReason.FILE_MAY_HOLD_OTHER_CONTENT,
    )

    with pytest.raises(ValueError, match="last known content"):
        build_network_request_result(
            network_request,
            request_certainty_after_evidence=CONFIRMED,
            evidence=(EXIT_CODE_EVIDENCE, OWN_OUTPUT_LINE_EVIDENCE),
        )


# The reason that names the line of `SHARED_OUTPUT_LINE_EVIDENCE`.
SHARED_OUTPUT_LINE_REASON = SharedOutputLineAssumptionReason(TOOL_CALL_KEY, 0, None)


def test_network_request_result_refuses_assumption_reasons_of_a_confirmed_result():
    with pytest.raises(ValueError, match="confirmed result with assumption reasons"):
        build_network_request_result(
            build_network_request(),
            level=EXECUTED,
            stop_reason=FAILED,
            evidence=(SHARED_OUTPUT_LINE_EVIDENCE,),
            assumption_reasons=(JudgmentRuleAssumptionReason(),),
        )


def test_network_request_result_refuses_an_assumed_result_without_reasons():
    with pytest.raises(ValueError, match="assumed result without assumption reasons"):
        build_network_request_result(
            build_network_request(),
            level=EXECUTED,
            stop_reason=FAILED,
            evidence=(SHARED_OUTPUT_LINE_EVIDENCE,),
            level_certainty=NetworkRequestResultCertainty.ASSUMED,
        )


@pytest.mark.parametrize(
    "evidence",
    [
        pytest.param((OWN_OUTPUT_LINE_EVIDENCE,), id="the line no other request owns"),
        pytest.param(
            (
                OutputLineEvidence(
                    TOOL_CALL_KEY, 1, None, OutputLineKind.NAME_NOT_RESOLVED, True
                ),
            ),
            id="another shared line of the result",
        ),
        pytest.param(
            (
                OutputLineEvidence(
                    TOOL_CALL_KEY, 0, 0, OutputLineKind.NAME_NOT_RESOLVED, True
                ),
            ),
            id="a shared line inside the JSON string of the same line",
        ),
        pytest.param(
            (
                OutputLineEvidence(
                    ToolCallKey("trial", "main", 2, 0),
                    0,
                    None,
                    OutputLineKind.NAME_NOT_RESOLVED,
                    True,
                ),
            ),
            id="a shared line at the same index of another call",
        ),
        pytest.param((EXIT_CODE_EVIDENCE,), id="no line"),
    ],
)
def test_network_request_result_refuses_a_shared_output_line_reason_whose_line_is_no_shared_line_of_the_evidence(
    evidence: tuple[NetworkRequestResultEvidence, ...],
):
    with pytest.raises(ValueError, match="names no output line"):
        build_network_request_result(
            build_network_request(),
            level=EXECUTED,
            stop_reason=FAILED if evidence != (EXIT_CODE_EVIDENCE,) else NOT_VISIBLE,
            evidence=evidence,
            level_certainty=NetworkRequestResultCertainty.ASSUMED,
            assumption_reasons=(SHARED_OUTPUT_LINE_REASON,),
        )


def test_network_request_result_accepts_a_shared_output_line_reason_that_names_a_shared_line_of_the_evidence():
    build_network_request_result(
        build_network_request(),
        level=EXECUTED,
        stop_reason=FAILED,
        evidence=(EXIT_CODE_EVIDENCE, SHARED_OUTPUT_LINE_EVIDENCE),
        level_certainty=NetworkRequestResultCertainty.ASSUMED,
        assumption_reasons=(SHARED_OUTPUT_LINE_REASON, JudgmentRuleAssumptionReason()),
    )
