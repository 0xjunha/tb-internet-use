"""Decide the result of one network request from all the evidence of it, as its highest level, why it stopped there and how sure that is.

A request can hold evidence of several levels, e.g. `Connection reset by peer` and then `Successfully downloaded x` in the output of `pip install x`, so the pieces are combined into one level and one stop reason.
A result that a judgment rule chose, or that rests only on evidence another request may share, is assumed.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace

from tb_internet_use.network_request.model import (
    NetworkRequest,
    NetworkRequestCertainty,
)
from tb_internet_use.network_request_result.judgment_rules import (
    treat_higher_evidence_beside_failure_as_assumed_level,
    treat_stop_reasons_of_one_level_as_first_in_fixed_order,
)
from tb_internet_use.network_request_result.model import (
    EvidenceWithLevel,
    ExitCodeEvidence,
    HttpStatusEvidence,
    JudgmentRuleAssumptionReason,
    NetworkRequestResult,
    NetworkRequestResultAssumptionReason,
    NetworkRequestResultCertainty,
    NetworkRequestResultLevel,
    NetworkRequestResultStopReason,
    OutputLineEvidence,
    OutputLineKind,
)

# The levels from the lowest to the highest, so that the order does not rest on how the values of the enum are spelled.
_LEVELS_IN_ORDER = (
    NetworkRequestResultLevel.ATTEMPTED,
    NetworkRequestResultLevel.EXECUTED,
    NetworkRequestResultLevel.REACHED,
    NetworkRequestResultLevel.RECEIVED,
)
# The kinds of output line that, as evidence of `NOT_VISIBLE` at `REACHED`, show that the request may have gone on after a failure at `REACHED`, e.g. `HTTP/1.1 200 OK` after `HTTP/1.1 404 Not Found` under `curl -i -L u`.
_OUTPUT_LINE_KINDS_OF_REQUEST_GOING_ON_AT_REACHED = frozenset(
    {
        OutputLineKind.HTTP_STATUS,
        OutputLineKind.BARE_STATUS_CODE,
        OutputLineKind.SERVER_ANSWERED,
        OutputLineKind.DOWNLOAD_STARTED,
    }
)
# The kinds of output line that show that the request was sent, so that such a line of this request alone lifts an uncertain request to confirmed, e.g. `npm ERR! code E404` under `npx tsc`.
_OUTPUT_LINE_KINDS_OF_SENT_REQUEST = frozenset(
    {
        OutputLineKind.NAME_NOT_RESOLVED,
        OutputLineKind.CONNECTION_FAILED,
        OutputLineKind.HTTP_STATUS,
        OutputLineKind.BARE_STATUS_CODE,
        OutputLineKind.SERVER_ANSWERED,
        OutputLineKind.NOT_FOUND,
        OutputLineKind.DOWNLOAD_STARTED,
        OutputLineKind.DOWNLOADED,
    }
)


@dataclass(frozen=True, slots=True)
class _LevelAndStopReason:
    """Choice of the level and stop reason of one request, made while its evidence is combined and read by `_level_certainty_of` to give the result its certainty."""

    level: NetworkRequestResultLevel
    stop_reason: NetworkRequestResultStopReason | None
    # A judgment rule picked them, so the result is assumed whatever evidence shows them.
    rests_on_judgment_rule: bool
    # An output line of this request alone showed the level, so evidence that another request may share was left out of the pick and gives no assumption reason.
    leaves_out_evidence_that_may_belong_to_another_request: bool = False


def decide_one_network_request_result(
    network_request: NetworkRequest,
    evidence_with_levels: Sequence[EvidenceWithLevel],
    *,
    judgment_rule_use_counts: Counter[str],
) -> NetworkRequestResult:
    """Decide the result of `network_request` from `evidence_with_levels`, all its evidence, each with the level and stop reason it shows.

    The result takes the highest level, the stop reason at it and every piece of evidence, also those that show a lower level, e.g. the exit code 0 of `pip install x` beside `Successfully downloaded x`.
    It is `CONFIRMED` when no judgment rule picked its level and stop reason and evidence that neither another request may share nor a judgment rule gave shows them, and `ASSUMED` otherwise, with every reason of that.
    A request without evidence is `ATTEMPTED` with `NOT_VISIBLE` and `CONFIRMED`, since it claims nothing more.
    Every use of a rule of `judgment_rules.py` adds one to `judgment_rule_use_counts` under the name of the rule.
    """
    level_and_stop_reason = _highest_level_and_stop_reason_of(
        evidence_with_levels, judgment_rule_use_counts=judgment_rule_use_counts
    )
    level_certainty = _level_certainty_of(level_and_stop_reason, evidence_with_levels)
    return NetworkRequestResult(
        network_request=network_request,
        request_certainty_after_evidence=_request_certainty_after_evidence_of(
            network_request, evidence_with_levels
        ),
        level=level_and_stop_reason.level,
        stop_reason=level_and_stop_reason.stop_reason,
        level_certainty=level_certainty,
        evidence=tuple(
            evidence_with_level.evidence for evidence_with_level in evidence_with_levels
        ),
        assumption_reasons=_assumption_reasons_of(
            level_and_stop_reason, evidence_with_levels, level_certainty
        ),
    )


def _highest_level_and_stop_reason_of(
    evidence_with_levels: Sequence[EvidenceWithLevel],
    *,
    judgment_rule_use_counts: Counter[str],
) -> _LevelAndStopReason:
    """Pick the highest level that the evidence shows and the stop reason at it, asking a judgment rule when a failure sits below a higher level.

    A higher level includes the lower ones. A failure below it, e.g. `Connection reset by peer` beside `Successfully downloaded x`, may be an earlier try, so only `treat_higher_evidence_beside_failure_as_assumed_level` takes the higher level, and the result then rests on it.
    Without evidence the request is `ATTEMPTED` with `NOT_VISIBLE`.
    """
    if not evidence_with_levels:
        return _LevelAndStopReason(
            NetworkRequestResultLevel.ATTEMPTED,
            NetworkRequestResultStopReason.NOT_VISIBLE,
            rests_on_judgment_rule=False,
        )
    highest_level = max(
        (evidence_with_level.level for evidence_with_level in evidence_with_levels),
        key=_LEVELS_IN_ORDER.index,
    )
    failure_levels = [
        evidence_with_level.level
        for evidence_with_level in evidence_with_levels
        if evidence_with_level.stop_reason == NetworkRequestResultStopReason.FAILED
        and _LEVELS_IN_ORDER.index(evidence_with_level.level)
        < _LEVELS_IN_ORDER.index(highest_level)
    ]
    if not failure_levels:
        return _level_and_stop_reason_for(
            highest_level,
            evidence_with_levels,
            judgment_rule_use_counts=judgment_rule_use_counts,
        )
    if not treat_higher_evidence_beside_failure_as_assumed_level(
        use_counts=judgment_rule_use_counts
    ):
        return _LevelAndStopReason(
            max(failure_levels, key=_LEVELS_IN_ORDER.index),
            NetworkRequestResultStopReason.FAILED,
            rests_on_judgment_rule=False,
        )
    return replace(
        _level_and_stop_reason_for(
            highest_level,
            evidence_with_levels,
            judgment_rule_use_counts=judgment_rule_use_counts,
        ),
        rests_on_judgment_rule=True,
    )


def _level_and_stop_reason_for(
    level: NetworkRequestResultLevel,
    evidence_with_levels: Sequence[EvidenceWithLevel],
    *,
    judgment_rule_use_counts: Counter[str],
) -> _LevelAndStopReason:
    """Pick the stop reason at `level` from the evidence of that level, asking a judgment rule when the evidence gives several that contradict each other.

    A request is judged by its own evidence, so when an output line of this request alone shows the level, evidence that another request may share gives no stop reason there, e.g. the `200` that only `curl -s -w "%{http_code}" https://a.org/x` can have printed beside an `HTTP/1.1 405` of the same result that it shares with `curl -s https://b.org/y`.
    `NOT_VISIBLE` only says that nothing shows beyond the level, so it gives way to another stop reason without a rule, e.g. `Requirement already satisfied: x` beside exit 0 gives `NOT_NEEDED`.
    Two or more of no stop reason, `FAILED` and `NOT_NEEDED`, or `FAILED` beside evidence that the request may have gone on after the failure, e.g. `HTTP/1.1 404` and `HTTP/1.1 200` under `curl -i -L u`, are picked from by `treat_stop_reasons_of_one_level_as_first_in_fixed_order`, and the result then rests on it.
    """
    evidence_at_level = [
        evidence_with_level
        for evidence_with_level in evidence_with_levels
        if evidence_with_level.level == level
    ]
    leaves_out_evidence_that_may_belong_to_another_request = any(
        isinstance(evidence_with_level.evidence, OutputLineEvidence)
        and not evidence_with_level.may_belong_to_another_request
        for evidence_with_level in evidence_at_level
    )
    if leaves_out_evidence_that_may_belong_to_another_request:
        evidence_at_level = [
            evidence_with_level
            for evidence_with_level in evidence_at_level
            if not evidence_with_level.may_belong_to_another_request
        ]
    stop_reasons_to_pick_from = {
        evidence_with_level.stop_reason for evidence_with_level in evidence_at_level
    } - {NetworkRequestResultStopReason.NOT_VISIBLE}
    if NetworkRequestResultStopReason.FAILED in stop_reasons_to_pick_from and any(
        _may_show_request_going_on_after_failure(evidence_with_level)
        for evidence_with_level in evidence_at_level
    ):
        stop_reasons_to_pick_from.add(NetworkRequestResultStopReason.NOT_VISIBLE)
    if len(stop_reasons_to_pick_from) > 1:
        return _LevelAndStopReason(
            level,
            treat_stop_reasons_of_one_level_as_first_in_fixed_order(
                stop_reasons_to_pick_from, use_counts=judgment_rule_use_counts
            ),
            rests_on_judgment_rule=True,
            leaves_out_evidence_that_may_belong_to_another_request=leaves_out_evidence_that_may_belong_to_another_request,
        )
    if stop_reasons_to_pick_from:
        (stop_reason,) = stop_reasons_to_pick_from
    else:
        stop_reason = NetworkRequestResultStopReason.NOT_VISIBLE
    return _LevelAndStopReason(
        level,
        stop_reason,
        rests_on_judgment_rule=False,
        leaves_out_evidence_that_may_belong_to_another_request=leaves_out_evidence_that_may_belong_to_another_request,
    )


def _may_show_request_going_on_after_failure(
    evidence_with_level: EvidenceWithLevel,
) -> bool:
    """Tell whether evidence of `NOT_VISIBLE` shows that the request may have gone on after a failure at the same level, e.g. exit 0 of `pip install x` after `Connection refused`.

    At `REACHED` it is a line of a status below 400, a line of a server's answer or of a download that began, or the status of a web fetch. At `EXECUTED` it is a line that a package was installed or the exit code 0.
    An exit code that a judgment rule reads as an answer of a server is not, so `HTTP/1.1 404` and exit 0 of `curl -i u` stay a failure.
    """
    if evidence_with_level.stop_reason != NetworkRequestResultStopReason.NOT_VISIBLE:
        return False
    evidence = evidence_with_level.evidence
    match evidence_with_level.level:
        case NetworkRequestResultLevel.REACHED:
            return isinstance(evidence, HttpStatusEvidence) or (
                isinstance(evidence, OutputLineEvidence)
                and evidence.kind in _OUTPUT_LINE_KINDS_OF_REQUEST_GOING_ON_AT_REACHED
            )
        case NetworkRequestResultLevel.EXECUTED:
            return isinstance(evidence, ExitCodeEvidence) or (
                isinstance(evidence, OutputLineEvidence)
                and evidence.kind == OutputLineKind.INSTALLED
            )
        case _:
            return False


def _level_certainty_of(
    level_and_stop_reason: _LevelAndStopReason,
    evidence_with_levels: Sequence[EvidenceWithLevel],
) -> NetworkRequestResultCertainty:
    """Give `CONFIRMED` when the request has no evidence, or when no judgment rule picked the level and stop reason and evidence of this request alone that no judgment rule gave shows them, and `ASSUMED` otherwise.

    A level or stop reason that a judgment rule picked is assumed even beside clean evidence, e.g. `saved [10/10]` after `Connection refused` under `wget -O x u`, since otherwise the clean line would confirm what only the rule decided.
    """
    if level_and_stop_reason.rests_on_judgment_rule:
        return NetworkRequestResultCertainty.ASSUMED
    if not evidence_with_levels:
        return NetworkRequestResultCertainty.CONFIRMED
    if any(
        evidence_with_level.level == level_and_stop_reason.level
        and evidence_with_level.stop_reason == level_and_stop_reason.stop_reason
        and not evidence_with_level.may_belong_to_another_request
        and not evidence_with_level.rests_on_judgment_rule
        for evidence_with_level in evidence_with_levels
    ):
        return NetworkRequestResultCertainty.CONFIRMED
    return NetworkRequestResultCertainty.ASSUMED


def _assumption_reasons_of(
    level_and_stop_reason: _LevelAndStopReason,
    evidence_with_levels: Sequence[EvidenceWithLevel],
    level_certainty: NetworkRequestResultCertainty,
) -> tuple[NetworkRequestResultAssumptionReason, ...]:
    """Give every reason that an assumed result is assumed, each once, and none for a confirmed one.

    A judgment rule that picked the level or stop reason comes first. Then come the reasons of each piece of evidence that shows the picked level and stop reason and that the pick did not leave out, in the order of the evidence, unless one such piece has no reason, since then that piece alone would have confirmed the result.
    So evidence of another level gives none, e.g. a shared `Connection refused` beside `saved [10/10]` of this request alone. Nor does a shared `saved` beside a clean one when a rule took them over a failure, nor a shared `HTTP/1.1 200 OK` beside an own `* Connected to a.org` that a rule read, which the pick left out.
    """
    if level_certainty == NetworkRequestResultCertainty.CONFIRMED:
        return ()
    assumption_reasons: list[NetworkRequestResultAssumptionReason] = []
    if level_and_stop_reason.rests_on_judgment_rule:
        assumption_reasons.append(JudgmentRuleAssumptionReason())
    deciding_evidence_with_levels = [
        evidence_with_level
        for evidence_with_level in evidence_with_levels
        if (evidence_with_level.level, evidence_with_level.stop_reason)
        == (level_and_stop_reason.level, level_and_stop_reason.stop_reason)
        and not (
            level_and_stop_reason.leaves_out_evidence_that_may_belong_to_another_request
            and evidence_with_level.may_belong_to_another_request
        )
    ]
    if all(
        evidence_with_level.assumption_reasons
        for evidence_with_level in deciding_evidence_with_levels
    ):
        for evidence_with_level in deciding_evidence_with_levels:
            assumption_reasons += evidence_with_level.assumption_reasons
    return tuple(dict.fromkeys(assumption_reasons))


def _request_certainty_after_evidence_of(
    network_request: NetworkRequest,
    evidence_with_levels: Sequence[EvidenceWithLevel],
) -> NetworkRequestCertainty:
    """Give `CONFIRMED` when the request is, or when an output line of this request alone shows that it was sent, and the certainty of the request otherwise.

    A line that a judgment rule read or that another request or a run that is not read may have printed lifts nothing, e.g. `HTTP/1.1 200 OK` in the result of `mytool https://a.org/x`. Evidence that is no output line lifts nothing either, e.g. exit 0 of `sbt compile`.
    A line that several requests of one command own lifts none of them, although it may still confirm that their command ran, e.g. a `DOWNLOAD_STARTED` line that names another package under `npx a u`, owned by both the package request of `a` and the URL request of `u`.
    """
    if any(
        _is_line_of_sent_request(evidence_with_level)
        for evidence_with_level in evidence_with_levels
    ):
        return NetworkRequestCertainty.CONFIRMED
    return network_request.certainty


def _is_line_of_sent_request(evidence_with_level: EvidenceWithLevel) -> bool:
    """Tell whether the evidence is an output line of this request alone, read without a judgment rule, that shows the request was sent.

    Both marks of sharing are read. `OutputLineEvidence.is_shared_with_other_requests` is true for every line with several owners, while `may_belong_to_another_request` stays false for a line that shows only that the one command of its owners ran.
    A bare number counts only when it is read as a status code, so `000` from `curl -w "%{http_code}"`, which shows `EXECUTED` because no answer came, does not.
    """
    evidence = evidence_with_level.evidence
    if (
        not isinstance(evidence, OutputLineEvidence)
        or evidence.is_shared_with_other_requests
        or evidence_with_level.may_belong_to_another_request
        or evidence_with_level.rests_on_judgment_rule
    ):
        return False
    if evidence.kind == OutputLineKind.BARE_STATUS_CODE:
        return evidence_with_level.level == NetworkRequestResultLevel.REACHED
    return evidence.kind in _OUTPUT_LINE_KINDS_OF_SENT_REQUEST
