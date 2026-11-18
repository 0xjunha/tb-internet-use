"""Tests for _decide_network_request_results.py."""

from collections import Counter

from tb_internet_use.expanded_tool_call.model import (
    CallCommandText,
    UnknownProgramInvocation,
)
from tb_internet_use.network_request.model import (
    ContentShownInResult,
    FromCommand,
    FromWebTool,
    NetworkRequest,
    NetworkRequestCertainty,
    NetworkRequestSource,
    NetworkRequestTargetKind,
    NetworkRequestUncertaintyReason,
)
from tb_internet_use.network_request_result import decide_network_request_results
from tb_internet_use.network_request_result.model import (
    NetworkRequestResultCertainty,
    NetworkRequestResultLevel,
    NetworkRequestResultStopReason,
)
from tb_internet_use.tool_call.model import HarnessTool, ToolCallKey


def build_network_request(
    index_in_tool_call: int,
    source: NetworkRequestSource,
    certainty: NetworkRequestCertainty,
    uncertainty_reason: NetworkRequestUncertaintyReason | None,
) -> NetworkRequest:
    return NetworkRequest(
        tool_call_key=ToolCallKey("trial", "main", 1, 0),
        index_in_tool_call=index_in_tool_call,
        source=source,
        target=f"https://a.org/{index_in_tool_call}",
        target_kind=NetworkRequestTargetKind.URL,
        host_names=("a.org",),
        received_content_destination=ContentShownInResult(),
        certainty=certainty,
        uncertainty_reason=uncertainty_reason,
    )


def test_each_request_without_evidence_gets_one_attempted_result_in_order_with_its_own_certainty():
    network_requests = (
        build_network_request(
            0,
            FromWebTool(None, HarnessTool("claude-code", "WebFetch")),
            NetworkRequestCertainty.CONFIRMED,
            None,
        ),
        build_network_request(
            1,
            FromCommand(
                0,
                CallCommandText(),
                UnknownProgramInvocation("mytool", ("https://a.org/1",)),
            ),
            NetworkRequestCertainty.UNCERTAIN,
            NetworkRequestUncertaintyReason.UNKNOWN_PROGRAM,
        ),
    )

    # A result without evidence asks the door nothing, so None stands in for it.
    results = decide_network_request_results(
        (),
        network_requests,
        knowledge=None,  # pyright: ignore[reportArgumentType]
        judgment_rule_use_counts=Counter(),
        unused_output_line_counts=Counter(),
        program_counts_of_unowned_output_lines=Counter(),
    )

    assert [result.network_request for result in results] == list(network_requests)
    assert [result.request_certainty_after_evidence for result in results] == [
        NetworkRequestCertainty.CONFIRMED,
        NetworkRequestCertainty.UNCERTAIN,
    ]
    for result in results:
        assert result.level == NetworkRequestResultLevel.ATTEMPTED
        assert result.stop_reason == NetworkRequestResultStopReason.NOT_VISIBLE
        assert result.level_certainty == NetworkRequestResultCertainty.CONFIRMED
        assert result.evidence == ()
