"""Row types for the exported files, with one row per network request, one per trial and one per category and sender of a trial, from which each question gets its own view.

A trial without requests still counts in the share of trials that have one, so every trial has a row.

The module also holds the answers of `ExportKnowledge` that `export_rows` tells apart when it runs, e.g. `UnknownPublicHost`, since a step never imports its knowledge class when it runs.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from tb_internet_use.network_request.model import (
    NetworkRequestCertainty,
    NetworkRequestTargetKind,
    NetworkRequestUncertaintyReason,
    UnknownNetworkRequestTargetReason,
)
from tb_internet_use.network_request_result.model import (
    NetworkRequestResultCertainty,
    NetworkRequestResultLevel,
    NetworkRequestResultStopReason,
)
from tb_internet_use.trial.model import UnreadableTrajectoryReason


@dataclass(frozen=True, slots=True)
class NetworkRequestRow:
    """Row of one network request, with what the trajectory shows of it and the columns computed from that.

    The first five fields together name one request in the trajectories. The fields from `category` on are computed from the fields before them and from outside knowledge.
    """

    trial_id: str
    trajectory_id: str
    # The step_id of the step in the trajectory, 1-based.
    step_id: int
    # The 0-based position in the step's tool calls, or past them for a message that the harness wrote in the step, as in `ToolCallKey.call_index`.
    call_index: int
    # The 0-based index among the requests of the call.
    request_index: int
    # The kind of place within the call that `source` describes, so that rows can be grouped by it without reading the text.
    source_kind: NetworkRequestSourceKind
    # The place within the call, e.g. `command 2 in fetch.sh written by call 11.0`, `code of command 0` or `web tool`.
    source: str

    # What the trajectory shows of the request, with credentials redacted, e.g. `pip install`, `python requests.get` or `WebFetch`.
    made_by: str
    # Empty when the words name no target or the trial does not show it.
    target: str
    # None when the request has a target in `target` or names none.
    unknown_target_reason: UnknownNetworkRequestTargetReason | None
    # None when the kind is not known.
    target_kind: NetworkRequestTargetKind | None
    # The host names separated by spaces, empty when the words name none.
    host_names: str
    # The destination as a word, e.g. `saved`.
    received_content_destination: str
    # The certainty after the evidence.
    request_certainty: NetworkRequestCertainty
    # None when `request_certainty` is confirmed, also when the evidence lifted an uncertain request to confirmed.
    request_uncertainty_reason: NetworkRequestUncertaintyReason | None
    level: NetworkRequestResultLevel
    stop_reason: NetworkRequestResultStopReason | None
    level_certainty: NetworkRequestResultCertainty
    # One short text per piece of evidence, e.g. `line 0 of call 12.0, name_not_resolved`.
    evidence: str

    category: NetworkRequestCategory
    # One value per name in `host_names`, in the same order and separated by spaces, e.g. `local public` or `unknown_single_label`. Empty when `host_names` is.
    host_scope: str
    # One value per name in `host_names`. `unknown` for a public host without a row of the host catalog, `not_public` for a host whose scope is not public, e.g. `localhost` or `db`.
    host_service: str
    # The registry that a package request asks, e.g. `pypi`. `unknown` when no fact names it, empty when the category is not `PACKAGE`.
    package_registry: str
    # None when the rules cannot tell, e.g. `$HOST`.
    is_internet_use: bool | None
    sender: NetworkRequestSender
    result_view: NetworkRequestResultView
    # The bounds of the main measure in which this row makes its trial count as one that has a request of its category.
    # `LOWER_AND_UPPER` for internet use by a request that is confirmed after the evidence, whatever its level, e.g. also when nothing shows that it ran. A `NOT_NEEDED` result is the exception. It is `NEITHER` when confirmed, and when assumed it is what `treat_assumed_not_needed_result_as_upper_bound_only` decides.
    request_measure_bound: MeasureBound
    # The bounds in which this row makes its trial count as one that received something of its category, by its own result alone.
    received_measure_bound: MeasureBound
    # True when the request shares an output line of success with other confirmed requests of its category and sender that all received by their results and are each assumed for shared output lines alone, that line among them, so that whichever of them printed it certainly received, e.g. each of `apt-get install -y a b` under one `Fetched 10 kB in 1s` that both own.
    # It is set only where the line raises the bound of the trial, i.e. where no row of the category and sender is in the lower bound of received by its own result.
    # The trial then counts in the lower bound of received for the category and sender of the row, while `received_measure_bound` stays as the result of the request alone gives it.
    is_among_success_line_owners_one_of_which_received: bool

    def __post_init__(self) -> None:
        """Refuse a received bound stronger than the request bound, since what was received was requested, and a row among success line owners one of which received that is not a confirmed request in the lower bound whose result is received."""
        if _is_received_bound_stronger_than_request_bound(
            self.request_measure_bound, self.received_measure_bound
        ):
            raise ValueError(
                f"received bound {self.received_measure_bound} is stronger than request bound {self.request_measure_bound}"
            )
        if self.is_among_success_line_owners_one_of_which_received and (
            self.request_measure_bound != MeasureBound.LOWER_AND_UPPER
            or self.result_view != NetworkRequestResultView.RECEIVED
        ):
            raise ValueError(
                f"a row among success line owners one of which received with request bound {self.request_measure_bound} and result view {self.result_view}"
            )


@dataclass(frozen=True, slots=True)
class TrialRow:
    """Row of one trial, with the facts of its `Trial` in their order and the bounds computed here, joined with its request rows by `trial_id`."""

    trial_id: str
    benchmark_version: str
    task_name: str
    leaderboard_row_id: str
    harness: str
    harness_version: str
    # None when the detail file of the trial writes its model info as null.
    model_name: str | None
    # None when the trial has none.
    reward: float | None
    # None when the trajectory was read. A trial with a reason has no request rows, which does not mean that it made no requests.
    unreadable_trajectory_reason: UnreadableTrajectoryReason | None
    # The strongest bound among the request rows of the trial that the task environment sent, over all categories. A row whose sender is not known counts at most in the upper bound, since it may have left from the task environment. `UPPER_ONLY` for an unreadable trajectory.
    any_category_request_measure_bound: MeasureBound
    any_category_received_measure_bound: MeasureBound

    def __post_init__(self) -> None:
        """Refuse a received bound stronger than the request bound, and an unreadable trajectory whose bounds are not both `UPPER_ONLY`, since nothing is known of its requests."""
        if _is_received_bound_stronger_than_request_bound(
            self.any_category_request_measure_bound,
            self.any_category_received_measure_bound,
        ):
            raise ValueError(
                f"received bound {self.any_category_received_measure_bound} is stronger than request bound {self.any_category_request_measure_bound}"
            )
        if self.unreadable_trajectory_reason is not None and (
            self.any_category_request_measure_bound,
            self.any_category_received_measure_bound,
        ) != (MeasureBound.UPPER_ONLY, MeasureBound.UPPER_ONLY):
            raise ValueError(
                f"an unreadable trajectory with {self.any_category_request_measure_bound} and {self.any_category_received_measure_bound}"
            )


@dataclass(frozen=True, slots=True)
class TrialCategoryMeasureRow:
    """Row of one category and sender of one trial, saying in which bounds of the main measure the trial counts."""

    trial_id: str
    category: NetworkRequestCategory
    sender: NetworkRequestSender
    request_measure_bound: MeasureBound
    received_measure_bound: MeasureBound

    def __post_init__(self) -> None:
        """Refuse a received bound stronger than the request bound, since what was received was requested."""
        if _is_received_bound_stronger_than_request_bound(
            self.request_measure_bound, self.received_measure_bound
        ):
            raise ValueError(
                f"received bound {self.received_measure_bound} is stronger than request bound {self.request_measure_bound}"
            )


def _is_received_bound_stronger_than_request_bound(
    request_measure_bound: MeasureBound, received_measure_bound: MeasureBound
) -> bool:
    """Tell whether the received bound comes before the request bound in `MEASURE_BOUNDS_FROM_STRONGEST`."""
    return MEASURE_BOUNDS_FROM_STRONGEST.index(
        received_measure_bound
    ) < MEASURE_BOUNDS_FROM_STRONGEST.index(request_measure_bound)


class MeasureBound(StrEnum):
    """Bounds of the main measure that a row counts in, where the lower bound holds only what is confirmed, i.e. a confirmed request for the bound of requests and a confirmed result for the bound of received content."""

    LOWER_AND_UPPER = "lower_and_upper"
    UPPER_ONLY = "upper_only"  # it is uncertain, assumed or not known
    NEITHER = "neither"


# The bounds from the one that counts a trial in most bounds, so that the strongest of several rows is the first of them in this order.
MEASURE_BOUNDS_FROM_STRONGEST = (
    MeasureBound.LOWER_AND_UPPER,
    MeasureBound.UPPER_ONLY,
    MeasureBound.NEITHER,
)


def strongest_measure_bound_of(measure_bounds: Iterable[MeasureBound]) -> MeasureBound:
    """Give the first of the bounds in `MEASURE_BOUNDS_FROM_STRONGEST`, and `NEITHER` for no bound, since one row is enough for a trial to count in a bound."""
    return min(
        measure_bounds,
        key=MEASURE_BOUNDS_FROM_STRONGEST.index,
        default=MeasureBound.NEITHER,
    )


def trial_received_measure_bound_of(
    network_request_row: NetworkRequestRow,
) -> MeasureBound:
    """Give the received bound in which a request row makes its trial count, which is `LOWER_AND_UPPER` for a row among success line owners one of which received and its own `received_measure_bound` otherwise.

    Which owner of a shared line of success received is not known, but that one did is, and the measure counts trials, not requests.
    """
    if network_request_row.is_among_success_line_owners_one_of_which_received:
        return MeasureBound.LOWER_AND_UPPER
    return network_request_row.received_measure_bound


class HostService(StrEnum):
    """Service that a public host gives, read by the category rules."""

    PACKAGE_REGISTRY = "package_registry"  # e.g. pypi.org
    CODE_HOSTING = "code_hosting"  # e.g. github.com
    MODEL_HUB = "model_hub"  # e.g. huggingface.co
    SEARCH_ENGINE = "search_engine"  # e.g. html.duckduckgo.com


@dataclass(frozen=True, slots=True)
class PublicHost:
    """Answer of `ExportKnowledge` about one public host, as its row of the host catalog gives it."""

    service: HostService
    package_registry: str | None  # None when the service is no package registry


@dataclass(frozen=True, slots=True)
class UnknownPublicHost:
    """Answer of `ExportKnowledge` for a public host without a row of the host catalog.

    `ExportKnowledge` also gives it for a host whose row has a blank `service`.
    """


@dataclass(frozen=True, slots=True)
class PackageRegistry:
    """Answer of `ExportKnowledge` about the registry that a program and subcommand ask by default, as its row of the package registry catalog gives it."""

    # The registry name, e.g. `pypi`.
    name: str
    # The hosts that the program asks when no configuration names another, e.g. `pypi.org`. Several when the default differs by system, e.g. `deb.debian.org` and `archive.ubuntu.com` for `apt-get`.
    host_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UnknownPackageRegistry:
    """Answer of `ExportKnowledge` for a program and subcommand without a row of the package registry catalog.

    `ExportKnowledge` also gives it for a program and subcommand whose row has a blank `package_registry`.
    """

    def __bool__(self) -> bool:
        """Refuse to be read as True or False, so that `if package_registry` never takes a program without a row for one with a row, since a request that `ExportKnowledge` is not asked about has None."""
        raise TypeError("the package registry of the program is not known")


class NetworkRequestSourceKind(StrEnum):
    """Kind of place of a request within its call, one per member of `NetworkRequestSource`."""

    COMMAND = "command"
    CODE = "code"
    WEB_TOOL = "web_tool"


class NetworkRequestCategory(StrEnum):
    """Category of a request by what it tried to get, where a different category needs a different replacement when the internet is off."""

    PACKAGE = "package"
    # A file or a page at a fixed address, e.g. a repository, data, a model or a document.
    CONTENT_FETCH = "content_fetch"
    SEARCH = "search"
    REMOTE_API_CALL = "remote_api_call"
    CONNECTIVITY_CHECK = "connectivity_check"
    OTHER_WEB = "other_web"
    UNKNOWN = "unknown"


class NetworkRequestSender(StrEnum):
    """Place that a request is sent from, since a policy that turns the internet off may or may not cover web tools."""

    TASK_ENVIRONMENT = "task_environment"
    HARNESS_PROCESS = "harness_process"  # e.g. a fetch tool that the harness runs
    PROVIDER_SERVER = "provider_server"  # e.g. a search that the model provider runs
    UNKNOWN = "unknown"  # no fact says where the tool runs


@dataclass(frozen=True, slots=True)
class UnknownNetworkRequestSender:
    """Answer of `ExportKnowledge` for a harness tool without a row of the web tool catalog.

    `ExportKnowledge` also gives it for a harness tool whose row has a blank `sender`.
    """


class NetworkRequestResultView(StrEnum):
    """View of a result as reports show it, computed from its stop reason alone."""

    RECEIVED = "received"  # it got what it asked for
    NOT_RECEIVED = "not_received"
    UNKNOWN = "unknown"
    NOT_NEEDED = "not_needed"
