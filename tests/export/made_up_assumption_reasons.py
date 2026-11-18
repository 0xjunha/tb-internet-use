"""Give the assumption reasons of made-up network request results for the tests of the export package, since `NetworkRequestResult` refuses an assumed result without them."""

from collections.abc import Sequence

from tb_internet_use.network_request_result.model import (
    JudgmentRuleAssumptionReason,
    NetworkRequestResultAssumptionReason,
    NetworkRequestResultCertainty,
    NetworkRequestResultEvidence,
    OutputLineEvidence,
    SharedOutputLineAssumptionReason,
)


def assumption_reasons_for(
    level_certainty: NetworkRequestResultCertainty,
    evidence: Sequence[NetworkRequestResultEvidence],
) -> tuple[NetworkRequestResultAssumptionReason, ...]:
    """Give no reason for a confirmed result, and for an assumed one a `SharedOutputLineAssumptionReason` per shared output line of its evidence, or a `JudgmentRuleAssumptionReason` when it has none, e.g. for an exit code 0 read as `REACHED`."""
    if level_certainty == NetworkRequestResultCertainty.CONFIRMED:
        return ()
    shared_output_line_reasons = tuple(
        SharedOutputLineAssumptionReason(
            piece.showing_tool_call_key,
            piece.line_index,
            piece.line_index_in_json_string,
        )
        for piece in evidence
        if isinstance(piece, OutputLineEvidence) and piece.is_shared_with_other_requests
    )
    return shared_output_line_reasons or (JudgmentRuleAssumptionReason(),)
