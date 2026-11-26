"""Decide the result of every network request of one trial from the output lines, exit codes, statuses and file uses that the trajectory shows of it."""

from collections import Counter
from collections.abc import Sequence
from typing import TYPE_CHECKING

from tb_internet_use.expanded_tool_call.model import ExpandedToolCall
from tb_internet_use.network_request.model import (
    NetworkRequest,
    NetworkRequestUncertaintyReason,
)
from tb_internet_use.network_request_result._decide_network_request_result_evidence import (
    decide_network_request_result_evidence,
)
from tb_internet_use.network_request_result._decide_one_network_request_result import (
    decide_one_network_request_result,
)
from tb_internet_use.network_request_result._decide_output_line_meanings import (
    decide_output_line_meanings,
)
from tb_internet_use.network_request_result._decide_output_line_owners import (
    decide_output_line_owners,
)
from tb_internet_use.network_request_result._decide_output_place_sources import (
    decide_output_place_sources,
)
from tb_internet_use.network_request_result.judgment_rules import (
    treat_request_of_last_known_content_as_reaching_no_output_place,
)
from tb_internet_use.network_request_result.model import (
    NetworkRequestResult,
    OutputLineKind,
    OutputLineWithMeaning,
    OutputPlaceSources,
    UnusedOutputLineReason,
)

if TYPE_CHECKING:
    # `NetworkRequestResultKnowledge` is passed in and named in annotations only, so that `decide_network_request_results` never loads `knowledge/` itself.
    from tb_internet_use.knowledge.network_request_result_knowledge import (
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

    The lines of every call's result are read, also where no request reaches, so that a line that a pattern fits and that no request owns is counted, e.g. `Downloading torch-2.3.0.whl` in the result of `./setup.sh`.
    A request of the last known content of a file asks `treat_request_of_last_known_content_as_reaching_no_output_place`. On `True` it is left out of the requests that own lines and that the evidence of the others reads, and its own evidence is only the status of a call that did not run.
    Every use of a rule of `judgment_rules.py` adds one to `judgment_rule_use_counts` under the name of the rule.
    Every output line that a pattern fits and that gives no evidence adds one to `unused_output_line_counts` under its reason and kind. A line that no request owns under `NO_UNKNOWN_RUN` or `UNOWNED_LINE_IN_UNKNOWN_RUN` also adds one to `program_counts_of_unowned_output_lines` for each program name that `decide_output_line_owners` counts it under, e.g. echo and ls for `Downloading torch-2.3.0.whl` in the result of `echo Downloading torch-2.3.0.whl; ls`.
    """
    may_reach_output_place_of_requests = [
        _may_reach_output_place(
            network_request, judgment_rule_use_counts=judgment_rule_use_counts
        )
        for network_request in network_requests
    ]
    network_requests_reaching_output_places = tuple(
        network_request
        for network_request, may_reach_output_place in zip(
            network_requests, may_reach_output_place_of_requests, strict=True
        )
        if may_reach_output_place
    )
    output_place_sources = decide_output_place_sources(expanded_tool_calls)
    output_line_owners = decide_output_line_owners(
        output_place_sources,
        _output_lines_with_meaning_of(
            expanded_tool_calls, output_place_sources, knowledge=knowledge
        ),
        expanded_tool_calls,
        network_requests_reaching_output_places,
        knowledge=knowledge,
        unused_output_line_counts=unused_output_line_counts,
        program_counts_of_unowned_output_lines=program_counts_of_unowned_output_lines,
    )
    return tuple(
        decide_one_network_request_result(
            network_request,
            decide_network_request_result_evidence(
                network_request,
                network_requests_reaching_output_places,
                expanded_tool_calls,
                output_place_sources,
                output_line_owners,
                may_reach_output_place=may_reach_output_place,
                knowledge=knowledge,
                judgment_rule_use_counts=judgment_rule_use_counts,
            ),
            judgment_rule_use_counts=judgment_rule_use_counts,
        )
        for network_request, may_reach_output_place in zip(
            network_requests, may_reach_output_place_of_requests, strict=True
        )
    )


def _may_reach_output_place(
    network_request: NetworkRequest, *, judgment_rule_use_counts: Counter[str]
) -> bool:
    """Tell whether the output of a request may reach a place, asking `treat_request_of_last_known_content_as_reaching_no_output_place` for a request of the last known content of a file and giving True for any other request."""
    return not (
        network_request.uncertainty_reason
        == NetworkRequestUncertaintyReason.FILE_MAY_HOLD_OTHER_CONTENT
        and treat_request_of_last_known_content_as_reaching_no_output_place(
            use_counts=judgment_rule_use_counts
        )
    )


def _output_lines_with_meaning_of(
    expanded_tool_calls: Sequence[ExpandedToolCall],
    output_place_sources: Sequence[OutputPlaceSources],
    *,
    knowledge: NetworkRequestResultKnowledge,
) -> tuple[OutputLineWithMeaning, ...]:
    """Give the lines that a pattern fits in the result of every call, in call order, read as page text only where the call is an output place of web tool actions alone.

    A result that is no output place is read too, e.g. that of a plan tool, so that its lines are counted as lines of no output place.
    """
    is_web_tool_result_by_key = {
        output_place_sources_of_call.showing_tool_call_key: output_place_sources_of_call.is_web_tool_result
        for output_place_sources_of_call in output_place_sources
    }
    # A call of web tool actions alone whose result holds a text and is not `NOT_RUN` is always an output place, so the text of a call that is no place is read with the patterns of other output.
    return tuple(
        output_line_with_meaning
        for expanded_tool_call in expanded_tool_calls
        for output_line_with_meaning in decide_output_line_meanings(
            expanded_tool_call.tool_call,
            is_web_tool_result=is_web_tool_result_by_key.get(
                expanded_tool_call.tool_call.harness_tool_call.key, False
            ),
            knowledge=knowledge,
        )
    )
