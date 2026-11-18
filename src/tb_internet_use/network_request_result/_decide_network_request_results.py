"""Decide the result of every network request of one trial from the output lines, exit codes, statuses and file uses that the trajectory shows of it."""

from collections import Counter
from collections.abc import Sequence
from typing import TYPE_CHECKING

from tb_internet_use.expanded_tool_call.model import ExpandedToolCall
from tb_internet_use.network_request.model import NetworkRequest
from tb_internet_use.network_request_result.model import (
    NetworkRequestResult,
    NetworkRequestResultCertainty,
    NetworkRequestResultLevel,
    NetworkRequestResultStopReason,
    OutputLineKind,
    UnusedOutputLineReason,
)

if TYPE_CHECKING:
    # The door is passed in and named in annotations only, so that `decide_network_request_results` never loads `knowledge/` itself.
    # The door module does not exist yet, so pyright is told to skip the missing import until it does.
    from tb_internet_use.knowledge.network_request_result_knowledge import (  # pyright: ignore[reportMissingImports]
        NetworkRequestResultKnowledge,
    )


def decide_network_request_results(
    expanded_tool_calls: Sequence[ExpandedToolCall],
    network_requests: Sequence[NetworkRequest],
    *,
    knowledge: NetworkRequestResultKnowledge,
    judgment_rule_use_counts: Counter[str],
    unused_output_line_counts: Counter[tuple[UnusedOutputLineReason, OutputLineKind]],
    program_counts_of_unowned_output_lines: Counter[
        tuple[UnusedOutputLineReason, OutputLineKind, str]
    ],
) -> tuple[NetworkRequestResult, ...]:
    """Decide one `NetworkRequestResult` for each of `network_requests`, in their order, from the output of `expanded_tool_calls`.

    Every use of a rule of `judgment_rules.py` adds one to `judgment_rule_use_counts` under the name of the rule.
    Every output line that a pattern fits and that gives no evidence adds one to `unused_output_line_counts` under its reason and kind. A line that no request owns also adds one to `program_counts_of_unowned_output_lines` for each program that reaches its place.
    It reads no evidence, so each result is the one for a request without evidence, `ATTEMPTED` and `NOT_VISIBLE` with `CONFIRMED`, and the request certainty of the request.
    """
    return tuple(
        _network_request_result_without_evidence_for(network_request)
        for network_request in network_requests
    )


def _network_request_result_without_evidence_for(
    network_request: NetworkRequest,
) -> NetworkRequestResult:
    """Give the result of a request that no evidence shows beyond `ATTEMPTED`, which is confirmed since it claims nothing more."""
    return NetworkRequestResult(
        network_request=network_request,
        request_certainty_after_evidence=network_request.certainty,
        level=NetworkRequestResultLevel.ATTEMPTED,
        stop_reason=NetworkRequestResultStopReason.NOT_VISIBLE,
        level_certainty=NetworkRequestResultCertainty.CONFIRMED,
        evidence=(),
    )
