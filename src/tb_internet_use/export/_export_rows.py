"""Export the trial row, the network request rows and the main measure rows of one trial from its `Trial` and network request results."""

from collections import Counter
from collections.abc import Sequence
from typing import TYPE_CHECKING

from tb_internet_use.export._export_network_request_row import (
    export_network_request_row,
)
from tb_internet_use.export._export_trial_category_measure_rows import (
    export_trial_category_measure_rows,
)
from tb_internet_use.export._export_trial_row import export_trial_row
from tb_internet_use.export._mark_network_request_rows_among_success_line_owners import (
    mark_network_request_rows_among_success_line_owners,
)
from tb_internet_use.export.model import (
    NetworkRequestRow,
    TrialCategoryMeasureRow,
    TrialRow,
)
from tb_internet_use.network_request_result.model import NetworkRequestResult
from tb_internet_use.trial.model import Trial

if TYPE_CHECKING:
    # `ExportKnowledge` is passed in and named in annotations only, so that `export_rows` never loads `knowledge/` itself.
    from tb_internet_use.knowledge.export_knowledge import ExportKnowledge


def export_rows(
    trial: Trial,
    network_request_results: Sequence[NetworkRequestResult],
    *,
    knowledge: ExportKnowledge,
    judgment_rule_use_counts: Counter[str],
) -> tuple[
    TrialRow, tuple[NetworkRequestRow, ...], tuple[TrialCategoryMeasureRow, ...]
]:
    """Export the `TrialRow` of one trial, a `NetworkRequestRow` per network request result in the order of the results and a `TrialCategoryMeasureRow` per category and sender.

    Every request of a trial is kept as a row, and a trial without requests still gets its `TrialRow`, since it counts in the share of trials of its task.
    The request rows come first, since the bounds of the trial row and of the main measure rows are the strongest among them.
    A request row is marked as among success line owners one of which received only once the rows of all requests of the trial are made, since whether a shared output line of success counts the trial in the lower bound of received rests on the rows of every owner of the line.
    Every use of a rule of `judgment_rules.py` adds one to `judgment_rule_use_counts` under the name of the rule, and every question to `knowledge` counts in `knowledge.uses`.
    Results that cannot belong to the trial raise `ValueError` before any row is exported, so that a refused trial counts no use. These are results of a trial whose trajectory could not be read, which has no results, and results of another trial, e.g. a result of `t2` given with the `Trial` of `t1`.
    """
    _check_network_request_results_of_trial(trial, network_request_results)
    network_request_rows = mark_network_request_rows_among_success_line_owners(
        network_request_results,
        [
            export_network_request_row(
                network_request_result,
                knowledge=knowledge,
                judgment_rule_use_counts=judgment_rule_use_counts,
            )
            for network_request_result in network_request_results
        ],
        judgment_rule_use_counts=judgment_rule_use_counts,
    )
    return (
        export_trial_row(
            trial,
            network_request_rows,
            judgment_rule_use_counts=judgment_rule_use_counts,
        ),
        network_request_rows,
        export_trial_category_measure_rows(trial, network_request_rows),
    )


def _check_network_request_results_of_trial(
    trial: Trial, network_request_results: Sequence[NetworkRequestResult]
) -> None:
    """Refuse with `ValueError` the results of a trial whose trajectory could not be read and the results of another trial."""
    if trial.unreadable_trajectory is not None and network_request_results:
        raise ValueError(
            f"trial {trial.trial_id} has an unreadable trajectory and {len(network_request_results)} network request results"
        )
    other_trial_ids = sorted(
        {
            network_request_result.network_request.tool_call_key.trial_id
            for network_request_result in network_request_results
        }
        - {trial.trial_id}
    )
    if other_trial_ids:
        raise ValueError(
            f"network request results of trials {other_trial_ids} given for trial {trial.trial_id}"
        )
