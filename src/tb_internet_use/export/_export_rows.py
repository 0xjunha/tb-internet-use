"""Export the trial row, the network request rows and the main measure rows of one trial from its `Trial` and network request results."""

from collections import Counter
from collections.abc import Sequence
from typing import TYPE_CHECKING

from tb_internet_use.export._export_trial_row import export_trial_row
from tb_internet_use.export.model import (
    NetworkRequestRow,
    TrialCategoryMeasureRow,
    TrialRow,
)
from tb_internet_use.network_request_result.model import NetworkRequestResult
from tb_internet_use.trial.model import Trial

if TYPE_CHECKING:
    # The door is passed in and named in annotations only, so that `export_rows` never loads `knowledge/` itself.
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
    """Export the `TrialRow` of one trial, a `NetworkRequestRow` per network request result and a `TrialCategoryMeasureRow` per category and sender.

    Every use of a rule of `judgment_rules.py` adds one to `judgment_rule_use_counts` under the name of the rule.
    A trial whose trajectory could not be read has no network request results, so results for one raise `ValueError`.
    It exports only the `TrialRow` of a read trial without results. A trial with results, or with an unreadable trajectory, raises `NotImplementedError` instead of getting rows without its request rows and main measure rows.
    """
    if trial.unreadable_trajectory is not None and network_request_results:
        raise ValueError(
            f"trial {trial.trial_id} has an unreadable trajectory and {len(network_request_results)} network request results"
        )
    if network_request_results or trial.unreadable_trajectory is not None:
        raise NotImplementedError(
            "export_rows exports no request rows and no main measure rows"
        )
    return (
        export_trial_row(trial, (), judgment_rule_use_counts=judgment_rule_use_counts),
        (),
        (),
    )
