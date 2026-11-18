"""Tests for _export_rows.py, from made-up network request results of one trial to its three kinds of row, with a made-up catalog of each kind."""

import dataclasses
from collections import Counter
from pathlib import Path

import pytest
from made_up_export_catalogs import write_made_up_export_catalogs

from tb_internet_use.expanded_tool_call.model import (
    CallCommandText,
    FileText,
    ProgramInvocation,
)
from tb_internet_use.export import export_rows
from tb_internet_use.export.judgment_rules import (
    treat_assumed_failure_as_possibly_received,
    treat_discarded_content_as_other_web,
    treat_request_of_unknown_sender_as_possibly_from_task_environment,
    treat_request_without_host_name_as_sent_to_default_registry_host,
    treat_url_query_value_and_fragment_as_credential,
)
from tb_internet_use.export.model import (
    MEASURE_BOUNDS_FROM_STRONGEST,
    MeasureBound,
    NetworkRequestCategory,
    NetworkRequestResultView,
    NetworkRequestRow,
    NetworkRequestSender,
    NetworkRequestSourceKind,
    TrialCategoryMeasureRow,
    TrialRow,
)
from tb_internet_use.knowledge.export_knowledge import (
    HARNESS_WEB_TOOLS_CSV,
    PUBLIC_HOSTS_CSV,
    ExportKnowledge,
)
from tb_internet_use.network_request.judgment_rules import (
    treat_dotted_host_name_as_public,
)
from tb_internet_use.network_request.model import (
    ContentDiscarded,
    ContentSaved,
    ContentShownInResult,
    FromCommand,
    FromWebTool,
    NetworkRequest,
    NetworkRequestCertainty,
    NetworkRequestSource,
    NetworkRequestTargetKind,
    NetworkRequestUncertaintyReason,
    ReceivedContentDestination,
)
from tb_internet_use.network_request_result.model import (
    ExitCodeEvidence,
    NetworkRequestResult,
    NetworkRequestResultCertainty,
    NetworkRequestResultEvidence,
    NetworkRequestResultLevel,
    NetworkRequestResultStopReason,
    OutputLineEvidence,
    OutputLineKind,
    ShownContentEvidence,
)
from tb_internet_use.tool_call.model import HarnessTool, ToolCallKey
from tb_internet_use.trial.model import (
    Trial,
    UnreadableTrajectory,
    UnreadableTrajectoryReason,
)

LOWER_AND_UPPER = MeasureBound.LOWER_AND_UPPER
UPPER_ONLY = MeasureBound.UPPER_ONLY
NEITHER = MeasureBound.NEITHER
PACKAGE = NetworkRequestCategory.PACKAGE
FETCHED_FILE = NetworkRequestCategory.FETCHED_FILE
SEARCH = NetworkRequestCategory.SEARCH
TASK_ENVIRONMENT = NetworkRequestSender.TASK_ENVIRONMENT
PROVIDER_SERVER = NetworkRequestSender.PROVIDER_SERVER
RECEIVED = NetworkRequestResultLevel.RECEIVED
EXECUTED = NetworkRequestResultLevel.EXECUTED
REACHED = NetworkRequestResultLevel.REACHED
ATTEMPTED = NetworkRequestResultLevel.ATTEMPTED
FAILED = NetworkRequestResultStopReason.FAILED
NOT_VISIBLE = NetworkRequestResultStopReason.NOT_VISIBLE
CONFIRMED = NetworkRequestResultCertainty.CONFIRMED
ASSUMED = NetworkRequestResultCertainty.ASSUMED
URL = NetworkRequestTargetKind.URL
PACKAGE_NAME = NetworkRequestTargetKind.PACKAGE_NAME

DOTTED_HOST_RULE = treat_dotted_host_name_as_public.__name__
DEFAULT_REGISTRY_RULE = (
    treat_request_without_host_name_as_sent_to_default_registry_host.__name__
)
ASSUMED_FAILURE_RULE = treat_assumed_failure_as_possibly_received.__name__
DISCARDED_CONTENT_RULE = treat_discarded_content_as_other_web.__name__
CREDENTIAL_RULE = treat_url_query_value_and_fragment_as_credential.__name__
UNKNOWN_SENDER_RULE = (
    treat_request_of_unknown_sender_as_possibly_from_task_environment.__name__
)


READ_TRIAL = Trial(
    "t1",
    "4-0-0",
    "terminal-bench/fix-git",
    "row-1",
    "claude-code",
    "2.1.0",
    "model-a",
    1.0,
    None,
)
UNREADABLE_TRIAL = dataclasses.replace(
    READ_TRIAL,
    unreadable_trajectory=UnreadableTrajectory(UnreadableTrajectoryReason.MISSING),
)


def _call(step_id: int, trial_id: str = "t1") -> ToolCallKey:
    """Give the first call of a step of the main trajectory, e.g. c1 of the pipeline example as step 1."""
    return ToolCallKey(trial_id, "main", step_id, 0)


def _program(program_name: str, *subcommand_words: str) -> ProgramInvocation:
    return ProgramInvocation(
        program_name=program_name,
        subcommand_words=subcommand_words,
        options=(),
        arguments=(),
        gets_more_arguments_at_run_time=False,
        unread_words=(),
        exits_with_exit_code_of_next_program=False,
    )


def _result(
    tool_call_key: ToolCallKey,
    source: NetworkRequestSource,
    target: str,
    target_kind: NetworkRequestTargetKind,
    received_content_destination: ReceivedContentDestination,
    host_names: tuple[str, ...],
    level: NetworkRequestResultLevel,
    stop_reason: NetworkRequestResultStopReason | None,
    level_certainty: NetworkRequestResultCertainty,
    evidence: tuple[NetworkRequestResultEvidence, ...],
    *,
    index_in_tool_call: int = 0,
    uncertainty_reason: NetworkRequestUncertaintyReason | None = None,
) -> NetworkRequestResult:
    """Make the result of a request, which is uncertain before and after the evidence when given a reason."""
    certainty = (
        NetworkRequestCertainty.CONFIRMED
        if uncertainty_reason is None
        else NetworkRequestCertainty.UNCERTAIN
    )
    return NetworkRequestResult(
        network_request=NetworkRequest(
            tool_call_key=tool_call_key,
            index_in_tool_call=index_in_tool_call,
            source=source,
            target=target,
            target_kind=target_kind,
            host_names=host_names,
            received_content_destination=received_content_destination,
            certainty=certainty,
            uncertainty_reason=uncertainty_reason,
        ),
        request_certainty_after_evidence=certainty,
        level=level,
        stop_reason=stop_reason,
        level_certainty=level_certainty,
        evidence=evidence,
    )


def _own_line(
    tool_call_key: ToolCallKey, line_index: int, kind: OutputLineKind
) -> OutputLineEvidence:
    return OutputLineEvidence(tool_call_key, line_index, None, kind, False)


def _received_by_curl(url: str, host_name: str) -> NetworkRequestResult:
    """Make `curl -O <url>` in the call of step 1, which saved what it received, as its own `saved` line shows."""
    return _result(
        _call(1),
        FromCommand(0, CallCommandText(), _program("curl")),
        url,
        URL,
        ContentSaved(url.rsplit("/", 1)[-1]),
        (host_name,),
        RECEIVED,
        None,
        CONFIRMED,
        (_own_line(_call(1), 0, OutputLineKind.DOWNLOADED),),
    )


def _received_by_pip(
    program_invocation: ProgramInvocation, *host_names: str
) -> NetworkRequestResult:
    """Make a `pip install` or `conda install` of `x` in the call of step 2 that installed what it received."""
    return _result(
        _call(2),
        FromCommand(0, CallCommandText(), program_invocation),
        "x",
        PACKAGE_NAME,
        ContentSaved(None),
        host_names,
        RECEIVED,
        None,
        CONFIRMED,
        (_own_line(_call(2), 0, OutputLineKind.DOWNLOADED),),
    )


# The example of `docs/pipeline-example.md`. Its hosts under example.org are reserved names, so these made-up names stand in for them and are read as public.
# r1 and r2 are the two curl of c1, which share one error line, so their failure is assumed.
EXAMPLE_R1 = _result(
    _call(1),
    FromCommand(0, CallCommandText(), _program("curl")),
    "https://a.files-mirror.org/x.tgz",
    URL,
    ContentSaved("x.tgz"),
    ("a.files-mirror.org",),
    EXECUTED,
    FAILED,
    ASSUMED,
    (OutputLineEvidence(_call(1), 0, None, OutputLineKind.CONNECTION_FAILED, True),),
)
EXAMPLE_R2 = dataclasses.replace(
    EXAMPLE_R1,
    network_request=dataclasses.replace(
        EXAMPLE_R1.network_request,
        index_in_tool_call=1,
        source=FromCommand(1, CallCommandText(), _program("curl")),
        target="https://b.files-mirror.org/y.tgz",
        host_names=("b.files-mirror.org",),
        received_content_destination=ContentSaved("y.tgz"),
    ),
)
# r3 is the curl of fetch.sh, which c2 wrote and c3 ran, and its own line in c5 shows that its host name did not resolve.
EXAMPLE_R3 = _result(
    _call(3),
    FromCommand(2, FileText(0, "fetch.sh", _call(2)), _program("curl")),
    "https://data.files-mirror.org/a.tgz",
    URL,
    ContentSaved("a.tgz"),
    ("data.files-mirror.org",),
    EXECUTED,
    FAILED,
    CONFIRMED,
    (_own_line(_call(5), 0, OutputLineKind.NAME_NOT_RESOLVED),),
)
# r4 is the `pip install requests` of c3, whose own lines in c4 show that a download began, so a server answered, but not that the package arrived.
EXAMPLE_R4 = _result(
    _call(3),
    FromCommand(1, CallCommandText(), _program("pip", "install")),
    "requests",
    PACKAGE_NAME,
    ContentSaved(None),
    (),
    REACHED,
    NOT_VISIBLE,
    CONFIRMED,
    (
        _own_line(_call(4), 0, OutputLineKind.DOWNLOAD_STARTED),
        _own_line(_call(4), 1, OutputLineKind.INSTALLED),
    ),
    index_in_tool_call=1,
)

# `curl -O https://a.org/x`, a fetched file received and confirmed.
FETCHED_FILE_RECEIVED = _received_by_curl("https://a.org/x", "a.org")
# `conda install x`, a package received whose internet use is not known, since `conda install` has no row of the package registry catalog.
PACKAGE_OF_UNKNOWN_INTERNET_USE = _received_by_pip(_program("conda", "install"))
# A search of Codex `web_search_call`, which the provider server sends, received and confirmed.
SEARCH_RECEIVED = _result(
    _call(3),
    FromWebTool(None, HarnessTool("codex", "web_search_call")),
    "how to x?",
    NetworkRequestTargetKind.SEARCH_QUERY,
    ContentShownInResult(),
    (),
    RECEIVED,
    None,
    CONFIRMED,
    (ShownContentEvidence(_call(3)),),
)
# `pip install x` whose program is missing, as `pip: command not found` shows.
PACKAGE_WHOSE_PROGRAM_IS_MISSING = _result(
    _call(4),
    FromCommand(0, CallCommandText(), _program("pip", "install")),
    "x",
    PACKAGE_NAME,
    ContentSaved(None),
    (),
    ATTEMPTED,
    FAILED,
    CONFIRMED,
    (_own_line(_call(4), 0, OutputLineKind.PROGRAM_MISSING),),
)
# `pip install --index-url http://localhost:8080/ x`, which is not internet use.
PACKAGE_FROM_LOCAL_HOST = _received_by_pip(_program("pip", "install"), "localhost")
# `npx tsc`, which fetches only what is missing, so the request stays uncertain although it received.
PACKAGE_OF_UNCERTAIN_REQUEST = _result(
    _call(5),
    FromCommand(0, CallCommandText(), _program("npx")),
    "tsc",
    PACKAGE_NAME,
    ContentSaved(None),
    (),
    RECEIVED,
    None,
    CONFIRMED,
    (ExitCodeEvidence(_call(5), 0, False),),
    uncertainty_reason=NetworkRequestUncertaintyReason.FETCHES_ONLY_WHAT_IS_MISSING,
)
# A page that Claude Code `Fetch` read, a tool without a row of the web tool catalog, with a token in the query of its URL.
PAGE_OF_UNKNOWN_SENDER = _result(
    _call(6),
    FromWebTool(None, HarnessTool("claude-code", "Fetch")),
    "https://a.org/p?token=abc",
    URL,
    ContentShownInResult(),
    ("a.org",),
    RECEIVED,
    None,
    CONFIRMED,
    (ShownContentEvidence(_call(6)),),
)
# `curl -s -o /dev/null https://b.org/x`, whose content is discarded.
DISCARDED_CONTENT = _result(
    _call(7),
    FromCommand(0, CallCommandText(), _program("curl")),
    "https://b.org/x",
    URL,
    ContentDiscarded(),
    ("b.org",),
    RECEIVED,
    None,
    CONFIRMED,
    (ExitCodeEvidence(_call(7), 0, False),),
)

ALL_RESULTS_OF_ONE_TRIAL = (
    EXAMPLE_R1,
    EXAMPLE_R2,
    EXAMPLE_R3,
    EXAMPLE_R4,
    FETCHED_FILE_RECEIVED,
    PACKAGE_OF_UNKNOWN_INTERNET_USE,
    SEARCH_RECEIVED,
    PACKAGE_WHOSE_PROGRAM_IS_MISSING,
    PACKAGE_FROM_LOCAL_HOST,
    PACKAGE_OF_UNCERTAIN_REQUEST,
    PAGE_OF_UNKNOWN_SENDER,
    DISCARDED_CONTENT,
)


def _trial_row(
    trial: Trial,
    request_measure_bound: MeasureBound,
    received_measure_bound: MeasureBound,
) -> TrialRow:
    return TrialRow(
        trial_id=trial.trial_id,
        benchmark_version=trial.benchmark_version,
        task_name=trial.task_name,
        leaderboard_row_id=trial.leaderboard_row_id,
        harness=trial.harness,
        harness_version=trial.harness_version,
        model_name=trial.model_name,
        reward=trial.reward,
        unreadable_trajectory_reason=None
        if trial.unreadable_trajectory is None
        else trial.unreadable_trajectory.reason,
        any_category_request_measure_bound=request_measure_bound,
        any_category_received_measure_bound=received_measure_bound,
    )


@pytest.fixture(scope="module")
def catalogs_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    # Hosts such as `a.org` have no row, nor do Claude Code `Fetch` and `conda install`.
    return write_made_up_export_catalogs(
        tmp_path_factory.mktemp("export") / "catalogs",
        public_host_rows=("pypi.org,package_registry,pypi",),
        harness_web_tool_rows=("codex,web_search_call,provider_server",),
        program_package_registry_rows=(
            "pip,install,pypi,pypi.org",
            "npx,,npm,registry.npmjs.org",
        ),
    )


@pytest.fixture
def knowledge(catalogs_dir: Path) -> ExportKnowledge:
    return ExportKnowledge(catalogs_dir=catalogs_dir)


def test_example_of_the_pipeline_example_reaches_its_last_table(
    knowledge: ExportKnowledge,
):
    judgment_rule_use_counts: Counter[str] = Counter()

    trial_row, network_request_rows, trial_category_measure_rows = export_rows(
        READ_TRIAL,
        (EXAMPLE_R1, EXAMPLE_R2, EXAMPLE_R3, EXAMPLE_R4),
        knowledge=knowledge,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )

    fetched_file_row_of_r1 = NetworkRequestRow(
        trial_id="t1",
        trajectory_id="main",
        step_id=1,
        call_index=0,
        request_index=0,
        source_kind=NetworkRequestSourceKind.COMMAND,
        source="command 0",
        made_by="curl",
        target="https://a.files-mirror.org/x.tgz",
        unknown_target_reason=None,
        target_kind=URL,
        host_names="a.files-mirror.org",
        received_content_destination="saved",
        request_certainty=NetworkRequestCertainty.CONFIRMED,
        request_uncertainty_reason=None,
        level=EXECUTED,
        stop_reason=FAILED,
        level_certainty=ASSUMED,
        evidence="line 0 of call 1.0, connection_failed, shared",
        category=FETCHED_FILE,
        host_scope="public",
        host_service="unknown",
        package_registry="",
        is_internet_use=True,
        sender=TASK_ENVIRONMENT,
        result_view=NetworkRequestResultView.NOT_RECEIVED,
        request_measure_bound=LOWER_AND_UPPER,
        received_measure_bound=UPPER_ONLY,
    )
    assert network_request_rows == (
        fetched_file_row_of_r1,
        dataclasses.replace(
            fetched_file_row_of_r1,
            request_index=1,
            source="command 1",
            target="https://b.files-mirror.org/y.tgz",
            host_names="b.files-mirror.org",
        ),
        dataclasses.replace(
            fetched_file_row_of_r1,
            step_id=3,
            source="command 2 in fetch.sh written by call 2.0",
            target="https://data.files-mirror.org/a.tgz",
            host_names="data.files-mirror.org",
            level_certainty=CONFIRMED,
            evidence="line 0 of call 5.0, name_not_resolved",
            received_measure_bound=NEITHER,
        ),
        dataclasses.replace(
            fetched_file_row_of_r1,
            step_id=3,
            request_index=1,
            source="command 1",
            made_by="pip install",
            target="requests",
            target_kind=PACKAGE_NAME,
            host_names="",
            level=REACHED,
            stop_reason=NOT_VISIBLE,
            level_certainty=CONFIRMED,
            evidence="line 0 of call 4.0, download_started; line 1 of call 4.0, installed",
            category=PACKAGE,
            host_scope="",
            host_service="",
            package_registry="pypi",
            result_view=NetworkRequestResultView.UNKNOWN,
            received_measure_bound=UPPER_ONLY,
        ),
    )
    # The last table of the example. Both categories have a request in both bounds and are received only in the upper bound.
    assert trial_category_measure_rows == (
        TrialCategoryMeasureRow(
            "t1", PACKAGE, TASK_ENVIRONMENT, LOWER_AND_UPPER, UPPER_ONLY
        ),
        TrialCategoryMeasureRow(
            "t1", FETCHED_FILE, TASK_ENVIRONMENT, LOWER_AND_UPPER, UPPER_ONLY
        ),
    )
    assert trial_row == _trial_row(READ_TRIAL, LOWER_AND_UPPER, UPPER_ONLY)
    # Three named hosts and `pypi.org`, the default host of `pip install`, are dotted names read as public.
    assert judgment_rule_use_counts == Counter(
        {DOTTED_HOST_RULE: 4, ASSUMED_FAILURE_RULE: 2, DEFAULT_REGISTRY_RULE: 1}
    )


@pytest.mark.parametrize(
    ("network_request_results", "trial_category_measure_rows", "trial_row_bounds"),
    [
        # One row per category and sender, and the trial row reads only the rows that the task environment sent.
        (
            (FETCHED_FILE_RECEIVED, PACKAGE_OF_UNKNOWN_INTERNET_USE, SEARCH_RECEIVED),
            (
                TrialCategoryMeasureRow(
                    "t1", PACKAGE, TASK_ENVIRONMENT, UPPER_ONLY, UPPER_ONLY
                ),
                TrialCategoryMeasureRow(
                    "t1",
                    FETCHED_FILE,
                    TASK_ENVIRONMENT,
                    LOWER_AND_UPPER,
                    LOWER_AND_UPPER,
                ),
                TrialCategoryMeasureRow(
                    "t1", SEARCH, PROVIDER_SERVER, LOWER_AND_UPPER, LOWER_AND_UPPER
                ),
            ),
            (LOWER_AND_UPPER, LOWER_AND_UPPER),
        ),
        # A confirmed request whose program is missing has a request in both bounds and received nothing, and a request to a local host counts in no bound.
        (
            (PACKAGE_WHOSE_PROGRAM_IS_MISSING, PACKAGE_FROM_LOCAL_HOST),
            (
                TrialCategoryMeasureRow(
                    "t1", PACKAGE, TASK_ENVIRONMENT, LOWER_AND_UPPER, NEITHER
                ),
            ),
            (LOWER_AND_UPPER, NEITHER),
        ),
        # An uncertain request counts only in the upper bounds.
        (
            (PACKAGE_OF_UNCERTAIN_REQUEST, PACKAGE_FROM_LOCAL_HOST),
            (
                TrialCategoryMeasureRow(
                    "t1", PACKAGE, TASK_ENVIRONMENT, UPPER_ONLY, UPPER_ONLY
                ),
            ),
            (UPPER_ONLY, UPPER_ONLY),
        ),
    ],
)
def test_main_measure_rows_and_trial_row_take_the_strongest_request_row(
    network_request_results: tuple[NetworkRequestResult, ...],
    trial_category_measure_rows: tuple[TrialCategoryMeasureRow, ...],
    trial_row_bounds: tuple[MeasureBound, MeasureBound],
    knowledge: ExportKnowledge,
):
    trial_row, _, exported_trial_category_measure_rows = export_rows(
        READ_TRIAL,
        network_request_results,
        knowledge=knowledge,
        judgment_rule_use_counts=Counter(),
    )

    assert exported_trial_category_measure_rows == trial_category_measure_rows
    assert trial_row == _trial_row(READ_TRIAL, *trial_row_bounds)


def test_request_rows_follow_the_order_of_the_results_and_keep_two_requests_of_one_call(
    knowledge: ExportKnowledge,
):
    # `curl -O u1 -O u2` in one call makes two requests that differ only by their index in the call. They are given in reverse.
    second_request = dataclasses.replace(
        FETCHED_FILE_RECEIVED,
        network_request=dataclasses.replace(
            FETCHED_FILE_RECEIVED.network_request, index_in_tool_call=1
        ),
    )

    _, network_request_rows, _ = export_rows(
        READ_TRIAL,
        (second_request, FETCHED_FILE_RECEIVED, SEARCH_RECEIVED),
        knowledge=knowledge,
        judgment_rule_use_counts=Counter(),
    )

    assert [
        (row.step_id, row.call_index, row.request_index) for row in network_request_rows
    ] == [(1, 0, 1), (1, 0, 0), (3, 0, 0)]
    assert (
        dataclasses.replace(network_request_rows[0], request_index=0)
        == (network_request_rows[1])
    )


def test_every_piece_counts_its_rule_uses_in_the_one_counter_and_the_door_counts_its_questions(
    knowledge: ExportKnowledge,
):
    judgment_rule_use_counts: Counter[str] = Counter()

    trial_row, network_request_rows, _ = export_rows(
        READ_TRIAL,
        (PAGE_OF_UNKNOWN_SENDER, DISCARDED_CONTENT),
        knowledge=knowledge,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )

    # The rule of the sender counts in `export_trial_row`, the rule of discarded content in `export_network_request_category` and the credential rule in `redact_credentials`.
    assert judgment_rule_use_counts == Counter(
        {
            DOTTED_HOST_RULE: 2,
            CREDENTIAL_RULE: 1,
            UNKNOWN_SENDER_RULE: 1,
            DISCARDED_CONTENT_RULE: 1,
        }
    )
    assert network_request_rows[0].target == "https://a.org/p?token=REDACTED"
    # The page whose sender is not known counts in the upper bound of the trial row, as possibly from the task environment.
    assert (
        trial_row.any_category_request_measure_bound,
        trial_row.any_category_received_measure_bound,
    ) == (LOWER_AND_UPPER, LOWER_AND_UPPER)
    assert knowledge.uses.unknown_input_counts == Counter(
        {
            (PUBLIC_HOSTS_CSV, ("a.org",)): 1,
            (PUBLIC_HOSTS_CSV, ("b.org",)): 1,
            (HARNESS_WEB_TOOLS_CSV, ("claude-code", "Fetch")): 1,
        }
    )


def test_read_trial_without_results_keeps_its_trial_row_alone(
    knowledge: ExportKnowledge,
):
    judgment_rule_use_counts: Counter[str] = Counter()

    exported_rows = export_rows(
        READ_TRIAL,
        (),
        knowledge=knowledge,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )

    assert exported_rows == (_trial_row(READ_TRIAL, NEITHER, NEITHER), (), ())
    assert judgment_rule_use_counts == Counter()


def test_unreadable_trial_counts_in_the_upper_bounds_of_every_category_and_known_sender(
    knowledge: ExportKnowledge,
):
    trial_row, network_request_rows, trial_category_measure_rows = export_rows(
        UNREADABLE_TRIAL,
        (),
        knowledge=knowledge,
        judgment_rule_use_counts=Counter(),
    )

    assert trial_row == _trial_row(UNREADABLE_TRIAL, UPPER_ONLY, UPPER_ONLY)
    assert network_request_rows == ()
    assert len(trial_category_measure_rows) == 24
    assert {
        (
            row.category,
            row.sender,
            row.request_measure_bound,
            row.received_measure_bound,
        )
        for row in trial_category_measure_rows
    } == {
        (category, sender, UPPER_ONLY, UPPER_ONLY)
        for category in NetworkRequestCategory
        for sender in (
            TASK_ENVIRONMENT,
            NetworkRequestSender.HARNESS_PROCESS,
            PROVIDER_SERVER,
        )
    }


def _of_trial(
    network_request_result: NetworkRequestResult, trial_id: str
) -> NetworkRequestResult:
    tool_call_key = network_request_result.network_request.tool_call_key
    return dataclasses.replace(
        network_request_result,
        network_request=dataclasses.replace(
            network_request_result.network_request,
            tool_call_key=dataclasses.replace(tool_call_key, trial_id=trial_id),
        ),
    )


@pytest.mark.parametrize(
    ("trial", "network_request_results"),
    [
        # An unreadable trajectory has no results.
        (UNREADABLE_TRIAL, (FETCHED_FILE_RECEIVED,)),
        # A result of `t2` given with the `Trial` of `t1`, alone and after a result of `t1`.
        (READ_TRIAL, (_of_trial(FETCHED_FILE_RECEIVED, "t2"),)),
        (READ_TRIAL, (PAGE_OF_UNKNOWN_SENDER, _of_trial(DISCARDED_CONTENT, "t2"))),
    ],
)
def test_results_that_cannot_belong_to_the_trial_are_refused_before_any_use_is_counted(
    trial: Trial,
    network_request_results: tuple[NetworkRequestResult, ...],
    knowledge: ExportKnowledge,
):
    judgment_rule_use_counts: Counter[str] = Counter()

    with pytest.raises(ValueError):
        export_rows(
            trial,
            network_request_results,
            knowledge=knowledge,
            judgment_rule_use_counts=judgment_rule_use_counts,
        )

    assert judgment_rule_use_counts == Counter()
    assert knowledge.uses.row_use_counts == Counter()
    assert knowledge.uses.unknown_input_counts == Counter()


def _strength_of(measure_bound: MeasureBound) -> int:
    """Give 0 for the strongest bound, so that a smaller number is a stronger bound."""
    return MEASURE_BOUNDS_FROM_STRONGEST.index(measure_bound)


def test_bounds_of_all_rows_of_a_trial_agree(knowledge: ExportKnowledge):
    trial_row, network_request_rows, trial_category_measure_rows = export_rows(
        READ_TRIAL,
        ALL_RESULTS_OF_ONE_TRIAL,
        knowledge=knowledge,
        judgment_rule_use_counts=Counter(),
    )

    # The received bound of a request row is never stronger than its request bound.
    assert all(
        _strength_of(row.received_measure_bound)
        >= _strength_of(row.request_measure_bound)
        for row in network_request_rows
    )
    # Each category and sender of the request rows has one main measure row, whose bounds are the strongest of those request rows.
    request_rows_by_category_and_sender: dict[
        tuple[NetworkRequestCategory, NetworkRequestSender], list[NetworkRequestRow]
    ] = {}
    for row in network_request_rows:
        request_rows_by_category_and_sender.setdefault(
            (row.category, row.sender), []
        ).append(row)
    assert {
        (row.category, row.sender): (
            row.request_measure_bound,
            row.received_measure_bound,
        )
        for row in trial_category_measure_rows
    } == {
        category_and_sender: (
            min((row.request_measure_bound for row in rows), key=_strength_of),
            min((row.received_measure_bound for row in rows), key=_strength_of),
        )
        for category_and_sender, rows in request_rows_by_category_and_sender.items()
    }
    assert len(trial_category_measure_rows) == len(request_rows_by_category_and_sender)
    # The trial row is no stronger than the strongest request row, and its received bound no stronger than its request bound.
    assert _strength_of(trial_row.any_category_request_measure_bound) >= min(
        _strength_of(row.request_measure_bound) for row in network_request_rows
    )
    assert _strength_of(trial_row.any_category_received_measure_bound) >= _strength_of(
        trial_row.any_category_request_measure_bound
    )
