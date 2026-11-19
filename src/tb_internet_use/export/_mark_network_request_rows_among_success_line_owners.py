"""Mark the request rows of one trial whose requests share an output line of success that shows that one of them received, so that the trial counts in the lower bound of received for their category and sender.

When one output line of success has several owners, e.g. one `Fetched 10 kB in 1s` under `apt-get install -y a b`, `decide_network_request_results` gives each owner an assumed result, since any of them may have printed it. Whichever printed it received, so the trial received something of their category, while no row alone is confirmed.
"""

import dataclasses
from collections import Counter
from collections.abc import Sequence

from tb_internet_use.export.judgment_rules import (
    treat_trial_with_success_line_shared_by_confirmed_requests_as_received,
)
from tb_internet_use.export.model import (
    MeasureBound,
    NetworkRequestCategory,
    NetworkRequestResultView,
    NetworkRequestRow,
    NetworkRequestSender,
)
from tb_internet_use.network_request_result.model import (
    NetworkRequestResult,
    OutputLineEvidence,
    SharedOutputLineAssumptionReason,
)
from tb_internet_use.tool_call.model import ToolCallKey

# The place of one output line in a trial, as `OutputLineEvidence` and `SharedOutputLineAssumptionReason` name it, i.e. the showing call, the line index and the line index in the JSON string.
type _OutputLinePlace = tuple[ToolCallKey, int, int | None]


def mark_network_request_rows_among_success_line_owners(
    network_request_results: Sequence[NetworkRequestResult],
    network_request_rows: Sequence[NetworkRequestRow],
    *,
    judgment_rule_use_counts: Counter[str],
) -> tuple[NetworkRequestRow, ...]:
    """Mark the owners of each shared output line of success that counts the trial in the lower bound of received, giving the request rows of one trial in their order with `is_among_success_line_owners_one_of_which_received` set on those owners.

    The owners of a line are the results that hold it as an `OutputLineEvidence` shared with other requests.
    A line counts the trial in the lower bound of received when it has several owners, all of one category and sender, all in the lower bound of requests with the result view `RECEIVED`, and each with only `SharedOutputLineAssumptionReason`s, one of which names this very line. A confirmed owner, having no reason, keeps a line from counting the trial, since it is then in the lower bound of received by itself and its category and sender are left as they are. An assumed owner without a reason for this line may have printed it without receiving, e.g. `pip install X` that holds the line but whose level another shared line shows.
    The same text that two calls show, e.g. once in the result and once in a later `cat log`, is two lines, each of which must count the trial by itself.
    A line held by one result alone counts nothing, since its mark says that other requests own it too and those are not among the results.
    A category and sender in which a row is in the lower bound of received by its own result is left alone, since its bound cannot rise, so its rows stay unmarked and the rule is not asked. So the marked rows are exactly those that raise the bound of their trial, e.g. not those of `apt-get install -y a b` with its own `Get:1 ... b` beside a shared `Fetched 10 kB in`.
    `treat_trial_with_success_line_shared_by_confirmed_requests_as_received` is asked once for each other category and sender with such a line, and the owners of all those lines are marked on `True`.
    `network_request_results` and `network_request_rows` are of the same requests in the same order, and lists of other lengths raise `ValueError`.
    """
    if len(network_request_results) != len(network_request_rows):
        raise ValueError(
            f"{len(network_request_results)} network request results and {len(network_request_rows)} request rows"
        )
    owner_indexes_by_line_place = _owner_indexes_by_shared_output_line_place_of(
        network_request_results
    )
    categories_and_senders_received_by_a_row_alone = {
        (row.category, row.sender)
        for row in network_request_rows
        if row.received_measure_bound == MeasureBound.LOWER_AND_UPPER
    }
    line_places_counting_the_trial_by_category_and_sender: dict[
        tuple[NetworkRequestCategory, NetworkRequestSender], list[_OutputLinePlace]
    ] = {}
    for line_place, owner_indexes in owner_indexes_by_line_place.items():
        owner_rows = [network_request_rows[index] for index in owner_indexes]
        if (
            _is_line_showing_that_one_of_its_owners_received(
                line_place,
                [network_request_results[index] for index in owner_indexes],
                owner_rows,
            )
            and (owner_rows[0].category, owner_rows[0].sender)
            not in categories_and_senders_received_by_a_row_alone
        ):
            line_places_counting_the_trial_by_category_and_sender.setdefault(
                (owner_rows[0].category, owner_rows[0].sender), []
            ).append(line_place)
    marked_indexes: set[int] = set()
    for line_places in line_places_counting_the_trial_by_category_and_sender.values():
        owner_indexes = sorted(
            {
                index
                for line_place in line_places
                for index in owner_indexes_by_line_place[line_place]
            }
        )
        if treat_trial_with_success_line_shared_by_confirmed_requests_as_received(
            [network_request_rows[index] for index in owner_indexes],
            use_counts=judgment_rule_use_counts,
        ):
            marked_indexes.update(owner_indexes)
    return tuple(
        dataclasses.replace(
            row, is_among_success_line_owners_one_of_which_received=True
        )
        if index in marked_indexes
        else row
        for index, row in enumerate(network_request_rows)
    )


def _owner_indexes_by_shared_output_line_place_of(
    network_request_results: Sequence[NetworkRequestResult],
) -> dict[_OutputLinePlace, list[int]]:
    """Give for each output line that a result holds as shared with other requests the 0-based indexes of the results that hold it, each once and in order."""
    owner_indexes_by_line_place: dict[_OutputLinePlace, list[int]] = {}
    for index, network_request_result in enumerate(network_request_results):
        line_places = dict.fromkeys(
            (
                piece.showing_tool_call_key,
                piece.line_index,
                piece.line_index_in_json_string,
            )
            for piece in network_request_result.evidence
            if isinstance(piece, OutputLineEvidence)
            and piece.is_shared_with_other_requests
        )
        for line_place in line_places:
            owner_indexes_by_line_place.setdefault(line_place, []).append(index)
    return owner_indexes_by_line_place


def _is_line_showing_that_one_of_its_owners_received(
    line_place: _OutputLinePlace,
    owner_results: Sequence[NetworkRequestResult],
    owner_rows: Sequence[NetworkRequestRow],
) -> bool:
    """Tell whether a shared output line shows that one of its owners, all confirmed requests of one category and sender whose results are received, certainly received, so that it counts the trial in the lower bound of received."""
    return (
        len(owner_rows) > 1
        and len({(row.category, row.sender) for row in owner_rows}) == 1
        and all(
            row.request_measure_bound == MeasureBound.LOWER_AND_UPPER
            and row.result_view == NetworkRequestResultView.RECEIVED
            for row in owner_rows
        )
        and all(
            _has_only_shared_output_line_reasons_naming_line(result, line_place)
            for result in owner_results
        )
    )


def _has_only_shared_output_line_reasons_naming_line(
    network_request_result: NetworkRequestResult, line_place: _OutputLinePlace
) -> bool:
    """Tell whether every assumption reason of a result is a `SharedOutputLineAssumptionReason` and one of them names this line, which a confirmed result, having no reason, does not meet."""
    shared_line_places = [
        (
            assumption_reason.showing_tool_call_key,
            assumption_reason.line_index,
            assumption_reason.line_index_in_json_string,
        )
        for assumption_reason in network_request_result.assumption_reasons
        if isinstance(assumption_reason, SharedOutputLineAssumptionReason)
    ]
    return (
        len(shared_line_places) == len(network_request_result.assumption_reasons)
        and line_place in shared_line_places
    )
