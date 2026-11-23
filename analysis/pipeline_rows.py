"""Read the trial rows and request rows of a pipeline run into the columns that the trajectory analysis uses, and tell which request rows are confirmed.

The request rows file of a full run is over 100 MB, so each script reads it once and keeps only these columns.
"""

import csv
import sys
from collections import defaultdict
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from pathlib import Path

# A cell of `evidence` or `source` can be longer than the default limit of the csv module.
csv.field_size_limit(sys.maxsize)

TASK_NAME_PREFIX = "terminal-bench/"
SOLVED_REWARD = 1.0
# The categories of a request that gets a file, a page, a search or an answer of an API, i.e. none that a package cache replaces.
NON_PACKAGE_CATEGORIES = frozenset({"content_fetch", "search", "remote_api_call"})

# The columns of the `requests.csv` of one trial that a reader gets, i.e. those of `RequestRow` but `trial_id`.
TRIAL_REQUEST_COLUMNS = (
    "trajectory_id",
    "step_id",
    "made_by",
    "target",
    "host_names",
    "category",
    "is_internet_use",
    "sender",
    "result_view",
    "request_measure_bound",
)


@dataclass(frozen=True, slots=True)
class TrialFacts:
    """Facts of one trial from its row of `trial_rows.csv`, read by the rules that pick trials and by the prompt of its reader."""

    trial_id: str
    # The task name without the prefix `terminal-bench/`, e.g. `formal-crypto`.
    task: str
    harness: str
    # Empty when the detail file of the trial gives no model.
    model: str
    # None when the trial has no reward.
    reward: float | None
    # False when the pipeline could not read the trajectory, so the trial has no request rows.
    is_readable: bool

    @property
    def pair(self) -> tuple[str, str]:
        """Give the harness and model of the trial, which together name its pair."""
        return (self.harness, self.model)

    @property
    def is_solved(self) -> bool:
        return self.reward == SOLVED_REWARD


@dataclass(frozen=True, slots=True)
class RequestRow:
    """Columns of one row of `network_request_rows.csv` that the trajectory analysis reads, each as the text of its cell except `step_id`."""

    trial_id: str
    # `main` for the trajectory of the agent, or the id of a subagent trajectory inside it.
    trajectory_id: str
    # The 1-based step_id of the step in that trajectory.
    step_id: int
    made_by: str
    target: str
    # The host names separated by spaces.
    host_names: str
    category: str
    # `true`, `false` or empty when the rules cannot tell.
    is_internet_use: str
    sender: str
    result_view: str
    request_measure_bound: str


def read_trial_facts(trial_rows_path: Path) -> list[TrialFacts]:
    """Read every row of `trial_rows.csv` in file order."""
    with trial_rows_path.open(newline="") as csv_file:
        return [
            TrialFacts(
                trial_id=row["trial_id"],
                task=row["task_name"].removeprefix(TASK_NAME_PREFIX),
                harness=row["harness"],
                model=row["model_name"],
                reward=float(row["reward"]) if row["reward"] else None,
                is_readable=not row["unreadable_trajectory_reason"],
            )
            for row in csv.DictReader(csv_file)
        ]


def read_request_rows_by_trial(
    network_request_rows_path: Path, *, trial_ids: Collection[str] | None = None
) -> dict[str, list[RequestRow]]:
    """Read the rows of `network_request_rows.csv` grouped by trial in file order, only those of `trial_ids` when it is given."""
    rows_by_trial: dict[str, list[RequestRow]] = defaultdict(list)
    with network_request_rows_path.open(newline="") as csv_file:
        for cells in csv.DictReader(csv_file):
            if trial_ids is not None and cells["trial_id"] not in trial_ids:
                continue
            rows_by_trial[cells["trial_id"]].append(
                _request_row_of(cells, cells["trial_id"])
            )
    return dict(rows_by_trial)


def read_trial_request_rows(requests_path: Path, trial_id: str) -> list[RequestRow]:
    """Read the `requests.csv` of one trial, whose columns are `TRIAL_REQUEST_COLUMNS`."""
    with requests_path.open(newline="") as csv_file:
        return [_request_row_of(cells, trial_id) for cells in csv.DictReader(csv_file)]


def is_confirmed_request(request_row: RequestRow) -> bool:
    """Tell whether a request certainly went to the internet, i.e. it is internet use and counts in the lower bound."""
    return (
        request_row.is_internet_use == "true"
        and request_row.request_measure_bound == "lower_and_upper"
    )


def is_confirmed_non_package_request(request_row: RequestRow) -> bool:
    return (
        is_confirmed_request(request_row)
        and request_row.category in NON_PACKAGE_CATEGORIES
    )


def is_unconfirmed_request(request_row: RequestRow) -> bool:
    """Tell whether a request may have gone to the internet, i.e. it counts in the upper bound alone, e.g. `lake build`, which downloads only when its cache is empty."""
    return request_row.request_measure_bound == "upper_only"


def _request_row_of(cells: dict[str, str], trial_id: str) -> RequestRow:
    return RequestRow(
        trial_id=trial_id,
        trajectory_id=cells["trajectory_id"],
        step_id=int(cells["step_id"]),
        made_by=cells["made_by"],
        target=cells["target"],
        host_names=cells["host_names"],
        category=cells["category"],
        is_internet_use=cells["is_internet_use"],
        sender=cells["sender"],
        result_view=cells["result_view"],
        request_measure_bound=cells["request_measure_bound"],
    )


def host_names_of(request_rows: Iterable[RequestRow]) -> set[str]:
    return {name for row in request_rows for name in row.host_names.split()}
