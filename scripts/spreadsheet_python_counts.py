"""Count the trials and rows behind the spreadsheet of `build_spreadsheet.py` in plain Python, from the row files of `run_pipeline.py`.

The counts fill the tabs `<tab> (Python)` that the formulas are checked against, and the cells whose rows the spreadsheet does not hold.
"""

import csv
import dataclasses
import re
from collections import Counter
from collections.abc import Collection, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from tb_internet_use.export.model import (
    MeasureBound,
    NetworkRequestCategory,
    NetworkRequestRow,
    NetworkRequestSender,
    TrialCategoryMeasureRow,
    TrialRow,
)
from tb_internet_use.network_request.model import (
    NetworkRequestCertainty,
    NetworkRequestTargetKind,
    NetworkRequestUncertaintyReason,
    UnknownNetworkRequestTargetReason,
)
from tb_internet_use.network_request_result.model import (
    NetworkRequestResultLevel,
    NetworkRequestResultStopReason,
)

type TaskKey = tuple[str, str]  # benchmark_version, task_name

PASSED_REWARD = 1.0


class CountedBound(StrEnum):
    """Bound of the main measure that a count is of."""

    LOWER = "lower"
    UPPER = "upper"


class MainMeasure(StrEnum):
    """Share of the main measure, valued as in `any_category_request_measure_bound`."""

    REQUEST = "request"  # trials with a request
    RECEIVED = "received"  # trials that received what a request asked for


@dataclass(frozen=True, slots=True)
class RowFiles:
    """Paths of the output files of one run of `run_pipeline.py`."""

    run_dir: Path

    @property
    def trial_rows(self) -> Path:
        return self.run_dir / "trial_rows.csv"

    @property
    def trial_category_measure_rows(self) -> Path:
        return self.run_dir / "trial_category_measure_rows.csv"

    @property
    def network_request_rows(self) -> Path:
        return self.run_dir / "network_request_rows.csv"

    @property
    def task_category_measures(self) -> Path:
        return self.run_dir / "task_category_measures.csv"

    @property
    def equations(self) -> Path:
        return self.run_dir / "equations.csv"

    @property
    def summary(self) -> Path:
        return self.run_dir / "summary.csv"


@dataclass(frozen=True, slots=True)
class RegistryOrHostServiceLineKey:
    """Category and registry or host service of a line of the tab `Requested items`, for lower-bound requests from the task environment."""

    category: str
    # The `package_registry` of a package request, the `host_service` of another, e.g. `pypi` or `code_hosting`.
    registry_or_host_service: str


@dataclass(frozen=True, slots=True)
class RequestedItemLineKey:
    """Line of the tab `Requested items`, for lower-bound requests from the task environment."""

    task: TaskKey
    registry_or_host_service_line_key: RegistryOrHostServiceLineKey
    requested_item: str  # as `requested_item_of` gives it


@dataclass(slots=True)
class BoundSets:
    """Trials and request rows of one line in each bound."""

    lower_trial_ids: set[str] = field(default_factory=set)
    upper_trial_ids: set[str] = field(default_factory=set)
    lower_row_count: int = 0
    upper_row_count: int = 0

    def add(
        self, row: dict[str, str], counted_bounds: Collection[CountedBound]
    ) -> None:
        """Add a row to the bounds it counts in."""
        if CountedBound.UPPER in counted_bounds:
            self.upper_trial_ids.add(row["trial_id"])
            self.upper_row_count += 1
        if CountedBound.LOWER in counted_bounds:
            self.lower_trial_ids.add(row["trial_id"])
            self.lower_row_count += 1


@dataclass(frozen=True, slots=True)
class WebToolLineKey:
    """Line of the tab `Web tools`, for requests from senders other than the task environment."""

    harness: str
    made_by: str
    sender: str
    category: str


class SolvedWithoutRequestVerdict(StrEnum):
    """Answer of the column `Solved without a request?` of `Tasks`, by the passed trials of a task and their `any_category_request_measure_bound`."""

    # At least half of the passed trials are `neither`.
    YES_AT_LEAST_HALF = "yes (≥50%)"
    # At least one passed trial is `neither`, and fewer than half are, so the answer rests on few trials, e.g. on 1 of 144.
    YES_UNDER_HALF = "yes (<50%)"
    # None is `neither` and at least one is `upper_only`, which may have sent nothing.
    MAYBE = "maybe"
    # Every passed trial is `lower_and_upper`.
    NO = "no"
    NEVER_SOLVED = "never solved"


# The share of the passed trials of a task without a request from which the answer is `YES_AT_LEAST_HALF`, the user's choice of 2026-11-22.
HALF_OF_THE_PASSED_TRIALS = 0.5


@dataclass(frozen=True, slots=True)
class PassedTrialCounts:
    """Counts of the passed trials of one task by their `any_category_request_measure_bound`, as the tab `Tasks` shows them."""

    passed_trial_count: int
    without_request_trial_count: int  # `neither`
    upper_bound_only_trial_count: int  # `upper_only`

    @property
    def verdict(self) -> SolvedWithoutRequestVerdict:
        if not self.passed_trial_count:
            return SolvedWithoutRequestVerdict.NEVER_SOLVED
        if self.without_request_trial_count:
            if (
                self.without_request_trial_count / self.passed_trial_count
                >= HALF_OF_THE_PASSED_TRIALS
            ):
                return SolvedWithoutRequestVerdict.YES_AT_LEAST_HALF
            return SolvedWithoutRequestVerdict.YES_UNDER_HALF
        if self.upper_bound_only_trial_count:
            return SolvedWithoutRequestVerdict.MAYBE
        return SolvedWithoutRequestVerdict.NO


class UpperBoundOnlyCause(StrEnum):
    """Reason a trial is in the upper bound of any category and not in its lower bound, as the tab `Bounds` shows it.

    A trial takes the first cause, in the order of the members, whose rule its rows meet, so that each trial has one cause.
    """

    UNREADABLE_TRAJECTORY = "The trajectory could not be read"
    CONFIRMED_REQUEST_TO_ADDRESS_BUILT_IN_CODE = (
        "Code calls a network function, the address is built inside the code"
    )
    CONFIRMED_REQUEST_NOT_KNOWN_AS_INTERNET = "A request is certain, its words do not show whether the destination is on the internet"
    WEB_TOOL_OF_UNKNOWN_SENDER = "A web tool, not known where it runs"
    FETCHES_ONLY_WHAT_IS_MISSING = "A program that downloads only what is missing"
    URL_OUTSIDE_CODE_CALL = (
        "A public URL stands in code, outside a call known to send it"
    )
    OTHER_UNCERTAIN_REQUEST = "Other uncertain requests"


class BestRequestResult(StrEnum):
    """Furthest that any lower-bound request of a trial from the task environment got, as the tab `Bounds` shows it."""

    # The trial is in the lower bound of `any_category_received_measure_bound`.
    RECEIVED = "Received what it asked for"
    # A row of level `reached` or `received`.
    SERVER_ANSWERED = "A server answered, receipt not confirmed"
    # A row of stop reason `failed`, at level `attempted` or `executed`.
    FAILED_WITHOUT_ANSWER = "A request failed, none got an answer"
    # Every row stops at `not_visible` or `not_needed` below the level `reached`.
    NOT_VISIBLE = "Not visible whether a request ran or got an answer"


@dataclass(slots=True)
class SpreadsheetPythonCounts:
    """Result of `count_spreadsheet_values`."""

    # Every task of `trial_rows.csv`, sorted.
    tasks: list[TaskKey]
    task_by_trial_id: dict[str, TaskKey]
    trial_ids_by_task: dict[TaskKey, set[str]]
    harness_by_trial_id: dict[str, str]
    unreadable_trial_ids: set[str]
    passed_trial_ids: set[str]
    # From `trial_rows.csv`.
    any_category_trial_ids: dict[tuple[MainMeasure, CountedBound], set[str]]
    # From `trial_category_measure_rows.csv`, by category, sender and bound.
    request_trial_ids: dict[tuple[str, str, CountedBound], set[str]]
    # The rest is from `network_request_rows.csv`.
    requested_item_trial_ids: dict[RequestedItemLineKey, set[str]] = field(
        default_factory=dict
    )
    web_tool_lines: dict[WebToolLineKey, BoundSets] = field(default_factory=dict)
    best_request_result_by_trial_id: dict[str, BestRequestResult] = field(
        default_factory=dict
    )
    upper_bound_only_cause_by_trial_id: dict[str, UpperBoundOnlyCause] = field(
        default_factory=dict
    )
    # The `made_by` values of the rows that meet the rule of each cause, and the `unreadable_trajectory_reason` values for an unreadable trajectory.
    example_counts_by_upper_bound_only_cause: dict[
        UpperBoundOnlyCause, Counter[str]
    ] = field(default_factory=dict)
    request_row_counts_by_task_category_sender: Counter[tuple[TaskKey, str, str]] = (
        field(default_factory=Counter)
    )

    def trial_ids_of_task(self, task: TaskKey) -> set[str]:
        return self.trial_ids_by_task.get(task, set())

    def tasks_of(self, trial_ids: Iterable[str]) -> set[TaskKey]:
        return {self.task_by_trial_id[trial_id] for trial_id in trial_ids}

    def task_share_of(self, task: TaskKey, trial_ids: Collection[str]) -> float:
        """Give the share of the trials of a task that are among `trial_ids`."""
        task_trial_ids = self.trial_ids_of_task(task)
        return len(task_trial_ids & set(trial_ids)) / len(task_trial_ids)

    def request_trial_ids_of(
        self,
        counted_bound: CountedBound,
        *,
        categories: Iterable[str] | None = None,
        senders: Iterable[str] | None = None,
    ) -> set[str]:
        """Give the trials with a request in the bound, of any category or sender when None."""
        category_set = None if categories is None else set(categories)
        sender_set = None if senders is None else set(senders)
        return {
            trial_id
            for (category, sender, bound), trial_ids in self.request_trial_ids.items()
            if bound == counted_bound
            and (category_set is None or category in category_set)
            and (sender_set is None or sender in sender_set)
            for trial_id in trial_ids
        }

    def passed_trial_counts_of(self, task: TaskKey) -> PassedTrialCounts:
        """Count the passed trials of a task by their `any_category_request_measure_bound`."""
        passed_ids = self.trial_ids_of_task(task) & self.passed_trial_ids
        upper_ids = self.any_category_trial_ids[MainMeasure.REQUEST, CountedBound.UPPER]
        lower_ids = self.any_category_trial_ids[MainMeasure.REQUEST, CountedBound.LOWER]
        return PassedTrialCounts(
            passed_trial_count=len(passed_ids),
            without_request_trial_count=len(passed_ids - upper_ids),
            upper_bound_only_trial_count=len((passed_ids & upper_ids) - lower_ids),
        )


def count_spreadsheet_values(row_files: RowFiles) -> SpreadsheetPythonCounts:
    """Gather the sets and counts of the spreadsheet, reading each row file once."""
    trial_rows = list(csv_dicts_of(row_files.trial_rows, TrialRow))
    task_by_trial_id = {
        row["trial_id"]: (row["benchmark_version"], row["task_name"])
        for row in trial_rows
    }
    trial_ids_by_task: dict[TaskKey, set[str]] = {}
    for trial_id, task in task_by_trial_id.items():
        trial_ids_by_task.setdefault(task, set()).add(trial_id)
    any_category_trial_ids: dict[tuple[MainMeasure, CountedBound], set[str]] = {
        (measure, counted_bound): set()
        for measure in MainMeasure
        for counted_bound in CountedBound
    }
    for row in trial_rows:
        for measure in MainMeasure:
            for counted_bound in _counted_bounds_of(
                row[f"any_category_{measure}_measure_bound"]
            ):
                any_category_trial_ids[measure, counted_bound].add(row["trial_id"])
    request_trial_ids: dict[tuple[str, str, CountedBound], set[str]] = {}
    for row in csv_dicts_of(
        row_files.trial_category_measure_rows, TrialCategoryMeasureRow
    ):
        for counted_bound in _counted_bounds_of(row["request_measure_bound"]):
            request_trial_ids.setdefault(
                (row["category"], row["sender"], counted_bound), set()
            ).add(row["trial_id"])
    counts = SpreadsheetPythonCounts(
        tasks=sorted(trial_ids_by_task),
        task_by_trial_id=task_by_trial_id,
        trial_ids_by_task=trial_ids_by_task,
        harness_by_trial_id={row["trial_id"]: row["harness"] for row in trial_rows},
        unreadable_trial_ids={
            row["trial_id"] for row in trial_rows if row["unreadable_trajectory_reason"]
        },
        passed_trial_ids={
            row["trial_id"]
            for row in trial_rows
            if row["reward"] and float(row["reward"]) == PASSED_REWARD
        },
        any_category_trial_ids=any_category_trial_ids,
        request_trial_ids=request_trial_ids,
    )
    upper_bound_only_trial_ids = (
        any_category_trial_ids[MainMeasure.REQUEST, CountedBound.UPPER]
        - any_category_trial_ids[MainMeasure.REQUEST, CountedBound.LOWER]
    )
    lower_bound_rows_by_trial_id: dict[str, list[dict[str, str]]] = {}
    upper_bound_only_rows_by_trial_id: dict[str, list[dict[str, str]]] = {}
    for row in csv_dicts_of(row_files.network_request_rows, NetworkRequestRow):
        _count_network_request_row(counts, row)
        if row["request_measure_bound"] == MeasureBound.NEITHER:
            continue
        if row["trial_id"] in upper_bound_only_trial_ids and row["sender"] in (
            NetworkRequestSender.TASK_ENVIRONMENT,
            NetworkRequestSender.UNKNOWN,
        ):
            upper_bound_only_rows_by_trial_id.setdefault(row["trial_id"], []).append(
                _row_read_by_bounds_of(row)
            )
        elif (
            row["sender"] == NetworkRequestSender.TASK_ENVIRONMENT
            and row["request_measure_bound"] == MeasureBound.LOWER_AND_UPPER
        ):
            lower_bound_rows_by_trial_id.setdefault(row["trial_id"], []).append(
                _row_read_by_bounds_of(row)
            )
    received_lower_trial_ids = any_category_trial_ids[
        MainMeasure.RECEIVED, CountedBound.LOWER
    ]
    for trial_id in any_category_trial_ids[MainMeasure.REQUEST, CountedBound.LOWER]:
        counts.best_request_result_by_trial_id[trial_id] = best_request_result_of(
            lower_bound_rows_by_trial_id.get(trial_id, []),
            is_received=trial_id in received_lower_trial_ids,
        )
    unreadable_reason_by_trial_id = {
        row["trial_id"]: row["unreadable_trajectory_reason"] for row in trial_rows
    }
    for trial_id in upper_bound_only_trial_ids:
        rows = upper_bound_only_rows_by_trial_id.get(trial_id, [])
        unreadable_reason = unreadable_reason_by_trial_id[trial_id]
        cause = upper_bound_only_cause_of(rows, is_unreadable=bool(unreadable_reason))
        counts.upper_bound_only_cause_by_trial_id[trial_id] = cause
        examples = counts.example_counts_by_upper_bound_only_cause.setdefault(
            cause, Counter()
        )
        if cause == UpperBoundOnlyCause.UNREADABLE_TRAJECTORY:
            examples[unreadable_reason] += 1
        else:
            examples.update(row["made_by"] for row in _rows_of_cause(cause, rows))
    return counts


# The columns of a request row that `best_request_result_of` and `upper_bound_only_cause_of` read.
_COLUMNS_READ_BY_BOUNDS = (
    "made_by",
    "sender",
    "request_certainty",
    "request_uncertainty_reason",
    "unknown_target_reason",
    "level",
    "stop_reason",
    "is_internet_use",
)


def _row_read_by_bounds_of(row: dict[str, str]) -> dict[str, str]:
    """Keep only the columns that the tab `Bounds` reads, since a run holds hundreds of thousands of rows."""
    return {column: row[column] for column in _COLUMNS_READ_BY_BOUNDS}


def best_request_result_of(
    rows: Sequence[dict[str, str]], *, is_received: bool
) -> BestRequestResult:
    """Give how far the lower-bound requests of a trial from the task environment got, the furthest of any row."""
    if is_received:
        return BestRequestResult.RECEIVED
    if any(
        row["level"]
        in (NetworkRequestResultLevel.REACHED, NetworkRequestResultLevel.RECEIVED)
        for row in rows
    ):
        return BestRequestResult.SERVER_ANSWERED
    if any(row["stop_reason"] == NetworkRequestResultStopReason.FAILED for row in rows):
        return BestRequestResult.FAILED_WITHOUT_ANSWER
    return BestRequestResult.NOT_VISIBLE


def upper_bound_only_cause_of(
    rows: Sequence[dict[str, str]], *, is_unreadable: bool
) -> UpperBoundOnlyCause:
    """Give the first cause whose rule the rows of a trial only in the upper bound meet.

    The rows are those of the trial from the task environment or of sender `unknown` in either bound.
    """
    if is_unreadable:
        return UpperBoundOnlyCause.UNREADABLE_TRAJECTORY
    return next(
        cause
        for cause in UpperBoundOnlyCause
        if cause != UpperBoundOnlyCause.UNREADABLE_TRAJECTORY
        and (
            _rows_of_cause(cause, rows)
            or cause == UpperBoundOnlyCause.OTHER_UNCERTAIN_REQUEST
        )
    )


_UNCERTAINTY_REASON_BY_CAUSE = {
    UpperBoundOnlyCause.FETCHES_ONLY_WHAT_IS_MISSING: NetworkRequestUncertaintyReason.FETCHES_ONLY_WHAT_IS_MISSING,
    UpperBoundOnlyCause.URL_OUTSIDE_CODE_CALL: NetworkRequestUncertaintyReason.URL_OUTSIDE_CODE_CALL,
}


def _rows_of_cause(
    cause: UpperBoundOnlyCause, rows: Sequence[dict[str, str]]
) -> list[dict[str, str]]:
    """Give the rows of a trial that meet the rule of a cause, none when the trial does not meet it."""
    task_environment_rows = [
        row for row in rows if row["sender"] == NetworkRequestSender.TASK_ENVIRONMENT
    ]
    match cause:
        case UpperBoundOnlyCause.UNREADABLE_TRAJECTORY:
            return []
        case UpperBoundOnlyCause.CONFIRMED_REQUEST_TO_ADDRESS_BUILT_IN_CODE:
            return [
                row
                for row in task_environment_rows
                if row["request_certainty"] == NetworkRequestCertainty.CONFIRMED
                and row["unknown_target_reason"]
                == UnknownNetworkRequestTargetReason.BUILT_IN_CODE
            ]
        case UpperBoundOnlyCause.CONFIRMED_REQUEST_NOT_KNOWN_AS_INTERNET:
            # A confirmed request that is internet use, e.g. with a result `not_needed` that is assumed, falls through to the later causes.
            return [
                row
                for row in task_environment_rows
                if row["request_certainty"] == NetworkRequestCertainty.CONFIRMED
                and not row["is_internet_use"]
            ]
        case UpperBoundOnlyCause.WEB_TOOL_OF_UNKNOWN_SENDER:
            return [] if task_environment_rows else list(rows)
        case (
            UpperBoundOnlyCause.FETCHES_ONLY_WHAT_IS_MISSING
            | UpperBoundOnlyCause.URL_OUTSIDE_CODE_CALL
        ):
            return [
                row
                for row in task_environment_rows
                if row["request_uncertainty_reason"]
                == _UNCERTAINTY_REASON_BY_CAUSE[cause]
            ]
        case UpperBoundOnlyCause.OTHER_UNCERTAIN_REQUEST:
            return task_environment_rows


def share_band_of(share: float) -> int:
    """Give the 0-based 10-point band of a share, e.g. 2 for 25%, with 100% in the last band 9.

    It compares with `k / 10` as the formulas of the band compare with `0.k`, which is the same number.
    """
    return next(band for band in range(9, -1, -1) if share >= band / 10)


def requested_item_of(row: dict[str, str]) -> str | None:
    """Give what a request row asked for, as a line of the tab `Requested items` shows it, or None for a row that gets no line.

    A package gives its name as `package_name_of` shows it. Another request gives its host name. So does a package whose target is a URL, e.g. `https://pypi.org/pypi/x/json` gives `pypi.org`, since the URL names no package that `package_name_of` can read. A URL of a wheel file of pip still gives the name of the wheel, e.g. `numpy` of `https://files.pythonhosted.org/.../numpy-2.1.0-py3-none-any.whl`.
    A package request without a target gives a text in parentheses that says where the names are, as `_item_of_package_request_without_target` gives it.
    """
    if row["category"] != NetworkRequestCategory.PACKAGE:
        return _host_names_of(row)
    if row["target_kind"] == NetworkRequestTargetKind.URL and not _is_pip_wheel_file(
        row["target"], row["package_registry"]
    ):
        return _host_names_of(row)
    if row["target"]:
        return package_name_of(row["target"], row["package_registry"])
    return _item_of_package_request_without_target(row)


PACKAGE_INDEX_UPDATE_ITEM = "(package index update)"
PACKAGE_REGISTRY_PING_ITEM = "(package registry ping)"
PACKAGES_FROM_DEPENDENCY_FILE_ITEM = "(packages from dependency file)"
PACKAGE_NAME_IN_VARIABLE_ITEM = "(package name in variable)"
# The commands that ask a registry for no package, by what the request row shows in `made_by`.
_ITEM_OF_COMMAND_THAT_ASKS_FOR_NO_PACKAGE = {
    "apt-get update": PACKAGE_INDEX_UPDATE_ITEM,
    "apt update": PACKAGE_INDEX_UPDATE_ITEM,
    "npm ping": PACKAGE_REGISTRY_PING_ITEM,
}


def _item_of_package_request_without_target(row: dict[str, str]) -> str | None:
    """Give the text in parentheses of a package request whose row shows no target, by where the package names are.

    A command that asks for no package gives its own text, e.g. `apt-get update`, which reads the index of the registry.
    A name that is set when the command runs gives one text, e.g. `pip install $PKG`.
    A target that is a path on the machine gives no line, e.g. `pip install ./dist/x.whl`, since the file is not asked of a registry and its dependencies are not in the command.
    A request whose words were not read keeps the reason of its row, e.g. `(unread_words)`.
    Every other request takes its names from outside the command, from a file of the project, e.g. `npm ci` or `pip install -r reqs.txt`, or from a list that the program holds, e.g. `playwright install-deps`.
    """
    match row["unknown_target_reason"]:
        case UnknownNetworkRequestTargetReason.LOCAL_PATH:
            return None
        case UnknownNetworkRequestTargetReason.VALUE_SET_AT_RUN_TIME:
            return PACKAGE_NAME_IN_VARIABLE_ITEM
        case UnknownNetworkRequestTargetReason.NAMED_IN_FILE | "":
            return _ITEM_OF_COMMAND_THAT_ASKS_FOR_NO_PACKAGE.get(
                row["made_by"], PACKAGES_FROM_DEPENDENCY_FILE_ITEM
            )
        case unknown_target_reason:
            # Words that were not read, e.g. `pip install --foo x`, keep the reason of the row.
            return f"({unknown_target_reason})"


def _host_names_of(row: dict[str, str]) -> str:
    """Give the host names of a request row as `Requested items` shows them, or `(no host name)` when it names none."""
    return row["host_names"] or "(no host name)"


# The name at the start of a requirement of pip, before extras and version specifiers, e.g. `uvicorn` of `uvicorn[standard]>=0.30`.
_PIP_PACKAGE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
# A scoped or plain name of npm before `@` and its version, e.g. `@vitejs/plugin-react` of `@vitejs/plugin-react@4.3.4`.
_NPM_PACKAGE_NAME = re.compile(r"(?:@[^/@]+/)?[^/@]+")
# Registries whose packages pip installs, so their names follow pip's rules.
_PIP_REGISTRIES = ("pypi", "pytorch")


def package_name_of(target: str, package_registry: str) -> str:
    """Give the name of a package without its version specifier and extras, for display in `Requested items`.

    It joins the lines of one package across versions, e.g. `orjson==3.10.12` and `orjson==3.10.15` both give `orjson`. pip names are written as pip compares them, in lower case with `-` for runs of `_`, `.` and `-`, e.g. `Typing_Extensions` gives `typing-extensions`. npm keeps a leading `@scope/`, e.g. `@babel/core@7` gives `@babel/core`. apt drops `=version` and `/release`, e.g. `ovmf/trixie` gives `ovmf`. A wheel file of pip gives the name it carries, e.g. `dist/numpy-2.1.0-py3-none-any.whl` gives `numpy`. A URL or path of pip, e.g. `git+https://github.com/a/b.git`, a target of another registry, or a path of apt such as `/app/x.deb` stays as it is, since it names no package of a registry.
    """
    if package_registry in _PIP_REGISTRIES:
        if _is_pip_wheel_file(target, package_registry):
            # A wheel file is named `<name>-<version>-<tags>.whl`, e.g. `numpy-2.1.0-cp312-cp312-linux_x86_64.whl`.
            target = target.rsplit("/", 1)[-1].split("-", 1)[0]
        elif "/" in target or ":" in target:
            return target
        match = _PIP_PACKAGE_NAME.match(target)
        return re.sub(r"[-_.]+", "-", match.group().lower()) if match else target
    if package_registry == "npm":
        match = _NPM_PACKAGE_NAME.match(target)
        return match.group() if match else target
    if package_registry == "apt" and not target.startswith(("/", ".")):
        return re.split(r"[=/]", target, maxsplit=1)[0]
    return target


def _is_pip_wheel_file(target: str, package_registry: str) -> bool:
    """Tell whether a target is a wheel file that pip installs, by path or URL, e.g. `dist/numpy-2.1.0-py3-none-any.whl`."""
    return package_registry in _PIP_REGISTRIES and target.endswith(".whl")


def _count_network_request_row(
    counts: SpreadsheetPythonCounts, row: dict[str, str]
) -> None:
    """Add a request row to each line it falls in."""
    counts.request_row_counts_by_task_category_sender[
        counts.task_by_trial_id[row["trial_id"]], row["category"], row["sender"]
    ] += 1
    counted_bounds = _counted_bounds_of(row["request_measure_bound"])
    if not counted_bounds:
        return
    if row["sender"] != NetworkRequestSender.TASK_ENVIRONMENT:
        counts.web_tool_lines.setdefault(
            WebToolLineKey(
                counts.harness_by_trial_id[row["trial_id"]],
                row["made_by"],
                row["sender"],
                row["category"],
            ),
            BoundSets(),
        ).add(row, counted_bounds)
        return
    if CountedBound.LOWER not in counted_bounds:
        return
    line_key = RegistryOrHostServiceLineKey(
        row["category"], row[registry_or_host_service_column_of(row["category"])]
    )
    requested_item = requested_item_of(row)
    if requested_item is None:
        return
    counts.requested_item_trial_ids.setdefault(
        RequestedItemLineKey(
            counts.task_by_trial_id[row["trial_id"]], line_key, requested_item
        ),
        set(),
    ).add(row["trial_id"])


def registry_or_host_service_column_of(category: str) -> str:
    """Give the column that splits a category in `Requested items`, the registry for packages, since a package is asked of a registry, and the host service for the rest."""
    if category == NetworkRequestCategory.PACKAGE:
        return "package_registry"
    return "host_service"


def _counted_bounds_of(measure_bound: str) -> tuple[CountedBound, ...]:
    """Give the bounds that a row with this measure bound counts in."""
    match MeasureBound(measure_bound):
        case MeasureBound.LOWER_AND_UPPER:
            return (CountedBound.LOWER, CountedBound.UPPER)
        case MeasureBound.UPPER_ONLY:
            return (CountedBound.UPPER,)
        case MeasureBound.NEITHER:
            return ()


def csv_dicts_of(
    csv_path: Path,
    row_type: type[TrialRow | TrialCategoryMeasureRow | NetworkRequestRow],
) -> Iterator[dict[str, str]]:
    """Yield the rows of a row file as dicts, refusing a stale header that does not match its row type."""
    expected_columns = [row_field.name for row_field in dataclasses.fields(row_type)]
    with csv_path.open(newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if reader.fieldnames != expected_columns:
            raise ValueError(
                f"{csv_path.name} has the columns {reader.fieldnames}, not the fields of {row_type.__name__}"
            )
        yield from reader


def differing_task_category_measure_line_count_of(
    row_files: RowFiles, counts: SpreadsheetPythonCounts
) -> int:
    """Count the lines of `task_category_measures.csv` that differ from a recount of `trial_category_measure_rows.csv` or are on one side only.

    The file has no line for a task without rows, so the recount has none either.
    """
    bound_counts: Counter[tuple[TaskKey, str, str, str]] = Counter()
    groups: set[tuple[TaskKey, str, str]] = set()
    for row in csv_dicts_of(
        row_files.trial_category_measure_rows, TrialCategoryMeasureRow
    ):
        group = (
            counts.task_by_trial_id[row["trial_id"]],
            row["category"],
            row["sender"],
        )
        groups.add(group)
        for measure in MainMeasure:
            for counted_bound in _counted_bounds_of(row[f"{measure}_measure_bound"]):
                bound_counts[(*group, f"{measure}_{counted_bound}")] += 1
    expected_lines = {
        group: (
            len(counts.trial_ids_of_task(group[0])),
            bound_counts[(*group, "request_lower")],
            bound_counts[(*group, "request_upper")],
            bound_counts[(*group, "received_lower")],
            bound_counts[(*group, "received_upper")],
            counts.request_row_counts_by_task_category_sender[group],
        )
        for group in groups
    }
    written_lines: dict[tuple[TaskKey, str, str], tuple[int, ...]] = {}
    with row_files.task_category_measures.open(newline="") as csv_file:
        for line in csv.DictReader(csv_file):
            written_lines[
                (line["benchmark_version"], line["task_name"]),
                line["category"],
                line["sender"],
            ] = tuple(
                int(line[column])
                for column in (
                    "trial_count",
                    "request_lower_trial_count",
                    "request_upper_trial_count",
                    "received_lower_trial_count",
                    "received_upper_trial_count",
                    "request_row_count",
                )
            )
    return sum(
        1
        for group in expected_lines.keys() | written_lines.keys()
        if expected_lines.get(group) != written_lines.get(group)
    )
