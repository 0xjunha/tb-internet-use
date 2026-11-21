"""Tests for _mark_network_request_rows_among_success_line_owners.py, through `export_rows`, from made-up results of one trial whose requests share output lines to the rows of the trial, and for its refusal of results and rows of other numbers, called directly."""

import dataclasses
from collections import Counter
from pathlib import Path

import pytest
from made_up_export_catalogs import write_made_up_export_catalogs

from tb_internet_use.expanded_tool_call.model import CallCommandText, ProgramInvocation
from tb_internet_use.export import export_rows
from tb_internet_use.export._mark_network_request_rows_among_success_line_owners import (
    mark_network_request_rows_among_success_line_owners,
)
from tb_internet_use.export.judgment_rules import (
    treat_trial_with_success_line_shared_by_confirmed_requests_as_received,
)
from tb_internet_use.export.model import (
    MeasureBound,
    NetworkRequestCategory,
    NetworkRequestSender,
)
from tb_internet_use.knowledge.export_knowledge import ExportKnowledge
from tb_internet_use.network_request.model import (
    ContentSaved,
    ContentShownInResult,
    FromCommand,
    FromWebTool,
    NetworkRequest,
    NetworkRequestCertainty,
    NetworkRequestSource,
    NetworkRequestTargetKind,
    NetworkRequestUncertaintyReason,
)
from tb_internet_use.network_request_result.model import (
    JudgmentRuleAssumptionReason,
    NetworkRequestResult,
    NetworkRequestResultAssumptionReason,
    NetworkRequestResultCertainty,
    NetworkRequestResultEvidence,
    NetworkRequestResultLevel,
    NetworkRequestResultStopReason,
    OutputLineEvidence,
    OutputLineKind,
    SharedOutputLineAssumptionReason,
)
from tb_internet_use.tool_call.model import HarnessTool, ToolCallKey
from tb_internet_use.trial.model import Trial

LOWER_AND_UPPER = MeasureBound.LOWER_AND_UPPER
UPPER_ONLY = MeasureBound.UPPER_ONLY
PACKAGE = NetworkRequestCategory.PACKAGE
PAGE_READ = NetworkRequestCategory.PAGE_READ
TASK_ENVIRONMENT = NetworkRequestSender.TASK_ENVIRONMENT
RECEIVED = NetworkRequestResultLevel.RECEIVED
CONFIRMED = NetworkRequestResultCertainty.CONFIRMED
ASSUMED = NetworkRequestResultCertainty.ASSUMED
RULE = treat_trial_with_success_line_shared_by_confirmed_requests_as_received.__name__

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
# Where `pip install` puts what it receives, a file whose name the words do not give. The curl of a file fetch below gets it too, and its row is the same as with `ContentSaved("x.tgz")`, which `curl -O` gives.
SAVED_TO_NO_NAMED_FILE = ContentSaved(None)
# The call of `pip install A B` and a later call that runs `cat pip.log` on the log it wrote.
INSTALL_CALL = ToolCallKey("t1", "main", 1, 0)
LOG_READ_CALL = ToolCallKey("t1", "main", 2, 0)


def _shared_line(
    tool_call_key: ToolCallKey,
    line_index: int,
    kind: OutputLineKind = OutputLineKind.INSTALLED,
) -> OutputLineEvidence:
    return OutputLineEvidence(tool_call_key, line_index, None, kind, True)


def _reason_of(line: OutputLineEvidence) -> SharedOutputLineAssumptionReason:
    return SharedOutputLineAssumptionReason(
        line.showing_tool_call_key, line.line_index, line.line_index_in_json_string
    )


# `Successfully installed A-1.0 B-2.0` in the result of `pip install A B`, which either request may have printed.
INSTALLED_LINE = _shared_line(INSTALL_CALL, 0)
# The same text again, shown by `cat pip.log` in a later call, which is another line.
INSTALLED_LINE_OF_LOG = _shared_line(LOG_READ_CALL, 0)


def _pip_install(
    target: str,
    index_in_tool_call: int,
    *,
    uncertainty_reason: NetworkRequestUncertaintyReason | None = None,
) -> NetworkRequest:
    """Make the request of one package of `pip install`, which names no host and so goes to `pypi.org`."""
    return _request(
        FromCommand(
            0,
            CallCommandText(),
            ProgramInvocation(
                program_name="pip",
                subcommand_words=("install",),
                options=(),
                arguments=(),
                gets_more_arguments_at_run_time=False,
                unread_words=(),
                exits_with_exit_code_of_next_program=False,
            ),
        ),
        target,
        NetworkRequestTargetKind.PACKAGE_NAME,
        (),
        index_in_tool_call,
        uncertainty_reason=uncertainty_reason,
    )


def _page_read_by_web_tool(
    harness_tool: HarnessTool, index_in_tool_call: int
) -> NetworkRequest:
    return _request(
        FromWebTool(None, harness_tool),
        "https://a.org/p",
        NetworkRequestTargetKind.URL,
        ("a.org",),
        index_in_tool_call,
        received_content_destination=ContentShownInResult(),
    )


def _request(
    source: NetworkRequestSource,
    target: str,
    target_kind: NetworkRequestTargetKind,
    host_names: tuple[str, ...],
    index_in_tool_call: int,
    *,
    received_content_destination: ContentSaved
    | ContentShownInResult = SAVED_TO_NO_NAMED_FILE,
    uncertainty_reason: NetworkRequestUncertaintyReason | None = None,
) -> NetworkRequest:
    return NetworkRequest(
        tool_call_key=INSTALL_CALL,
        index_in_tool_call=index_in_tool_call,
        source=source,
        target=target,
        target_kind=target_kind,
        host_names=host_names,
        received_content_destination=received_content_destination,
        certainty=NetworkRequestCertainty.CONFIRMED
        if uncertainty_reason is None
        else NetworkRequestCertainty.UNCERTAIN,
        uncertainty_reason=uncertainty_reason,
    )


def _result(
    network_request: NetworkRequest,
    evidence: tuple[NetworkRequestResultEvidence, ...] = (INSTALLED_LINE,),
    assumption_reasons: tuple[NetworkRequestResultAssumptionReason, ...] | None = None,
    *,
    level: NetworkRequestResultLevel = RECEIVED,
    stop_reason: NetworkRequestResultStopReason | None = None,
) -> NetworkRequestResult:
    """Make a result that its shared lines alone show, so assumed with a reason for each, unless given reasons, where none makes it confirmed."""
    if assumption_reasons is None:
        assumption_reasons = tuple(
            _reason_of(piece)
            for piece in evidence
            if isinstance(piece, OutputLineEvidence)
            and piece.is_shared_with_other_requests
        )
    return NetworkRequestResult(
        network_request=network_request,
        request_certainty_after_evidence=network_request.certainty,
        level=level,
        stop_reason=stop_reason,
        level_certainty=ASSUMED if assumption_reasons else CONFIRMED,
        evidence=evidence,
        assumption_reasons=assumption_reasons,
    )


PIP_INSTALL_A = _result(_pip_install("A", 0))
PIP_INSTALL_B = _result(_pip_install("B", 1))
# `curl -O https://a.org/x.tgz` in the same call, a file fetch, assumed for the line of `cat pip.log` alone, whose text its run may have printed too.
CURL_OF_FILE_FETCH = _result(
    _request(
        FromCommand(
            1,
            CallCommandText(),
            ProgramInvocation(
                program_name="curl",
                subcommand_words=(),
                options=(),
                arguments=(),
                gets_more_arguments_at_run_time=False,
                unread_words=(),
                exits_with_exit_code_of_next_program=False,
            ),
        ),
        "https://a.org/x.tgz",
        NetworkRequestTargetKind.URL,
        ("a.org",),
        2,
    ),
    (INSTALLED_LINE_OF_LOG,),
)


@pytest.fixture
def knowledge(tmp_path: Path) -> ExportKnowledge:
    return ExportKnowledge(
        catalogs_dir=write_made_up_export_catalogs(
            tmp_path / "catalogs",
            public_host_rows=("pypi.org,package_registry,pypi",),
            harness_web_tool_rows=("codex,web_search_call,provider_server",),
            program_package_registry_rows=("pip,install,pypi,pypi.org",),
        )
    )


# (owners of the shared lines of one trial, whether the trial counts in the lower bound of received for `package` from the task environment)
CASES = [
    pytest.param(
        (PIP_INSTALL_A, PIP_INSTALL_B), True, id="two owners assumed for the line alone"
    ),
    pytest.param(
        (
            PIP_INSTALL_A,
            _result(
                _pip_install(
                    "B",
                    1,
                    uncertainty_reason=NetworkRequestUncertaintyReason.FETCHES_ONLY_WHAT_IS_MISSING,
                )
            ),
        ),
        False,
        id="one owner is an uncertain request",
    ),
    pytest.param(
        (
            PIP_INSTALL_A,
            _result(
                _pip_install("B", 1),
                assumption_reasons=(
                    _reason_of(INSTALLED_LINE),
                    JudgmentRuleAssumptionReason(),
                ),
            ),
        ),
        False,
        id="one owner is assumed by a judgment rule too",
    ),
    pytest.param(
        (
            PIP_INSTALL_A,
            _result(
                _pip_install("B", 1),
                level=NetworkRequestResultLevel.REACHED,
                stop_reason=NetworkRequestResultStopReason.NOT_VISIBLE,
            ),
        ),
        False,
        id="one owner is not a success",
    ),
    pytest.param(
        (PIP_INSTALL_A,),
        False,
        id="one owner alone holds a line marked as shared",
    ),
]


@pytest.mark.parametrize(
    ("network_request_results", "counts_trial_in_received_lower_bound"), CASES
)
def test_a_shared_line_of_success_counts_the_trial_in_the_received_lower_bound_only_when_every_owner_is_a_confirmed_request_of_the_category_that_received(
    network_request_results: tuple[NetworkRequestResult, ...],
    counts_trial_in_received_lower_bound: bool,
    knowledge: ExportKnowledge,
):
    judgment_rule_use_counts: Counter[str] = Counter()

    trial_row, network_request_rows, trial_category_measure_rows = export_rows(
        READ_TRIAL,
        network_request_results,
        knowledge=knowledge,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )

    expected_received_measure_bound = (
        LOWER_AND_UPPER if counts_trial_in_received_lower_bound else UPPER_ONLY
    )
    assert [
        (row.category, row.sender, row.received_measure_bound)
        for row in trial_category_measure_rows
    ] == [(PACKAGE, TASK_ENVIRONMENT, expected_received_measure_bound)]
    assert (
        trial_row.any_category_received_measure_bound == expected_received_measure_bound
    )
    assert [
        row.is_among_success_line_owners_one_of_which_received
        for row in network_request_rows
    ] == [counts_trial_in_received_lower_bound] * len(network_request_rows)
    assert judgment_rule_use_counts[RULE] == int(counts_trial_in_received_lower_bound)


def test_the_rows_of_a_trial_counted_by_a_shared_line_keep_their_own_bounds(
    knowledge: ExportKnowledge,
):
    _, network_request_rows, _ = export_rows(
        READ_TRIAL,
        (PIP_INSTALL_A, PIP_INSTALL_B),
        knowledge=knowledge,
        judgment_rule_use_counts=Counter(),
    )

    assert [
        (row.request_measure_bound, row.received_measure_bound, row.level_certainty)
        for row in network_request_rows
    ] == [(LOWER_AND_UPPER, UPPER_ONLY, ASSUMED)] * 2


def test_owners_of_another_category_count_the_trial_for_neither_category(
    knowledge: ExportKnowledge,
):
    curl_sharing_the_line = dataclasses.replace(
        CURL_OF_FILE_FETCH,
        evidence=(INSTALLED_LINE,),
        assumption_reasons=(_reason_of(INSTALLED_LINE),),
    )
    judgment_rule_use_counts: Counter[str] = Counter()

    _, network_request_rows, trial_category_measure_rows = export_rows(
        READ_TRIAL,
        (PIP_INSTALL_A, PIP_INSTALL_B, curl_sharing_the_line),
        knowledge=knowledge,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )

    assert {row.received_measure_bound for row in trial_category_measure_rows} == {
        UPPER_ONLY
    }
    assert not any(
        row.is_among_success_line_owners_one_of_which_received
        for row in network_request_rows
    )
    assert judgment_rule_use_counts[RULE] == 0


def test_owners_of_another_sender_do_not_count_the_trial(knowledge: ExportKnowledge):
    # Two page reads share one line, one by Codex `web_search_call` from the provider server and one by Claude Code `Fetch`, whose sender is not known.
    network_request_results = tuple(
        _result(_page_read_by_web_tool(harness_tool, index))
        for index, harness_tool in enumerate(
            (
                HarnessTool("codex", "web_search_call"),
                HarnessTool("claude-code", "Fetch"),
            )
        )
    )
    judgment_rule_use_counts: Counter[str] = Counter()

    _, _, trial_category_measure_rows = export_rows(
        READ_TRIAL,
        network_request_results,
        knowledge=knowledge,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )

    assert [
        (row.category, row.sender, row.received_measure_bound)
        for row in trial_category_measure_rows
    ] == [
        (PAGE_READ, NetworkRequestSender.PROVIDER_SERVER, UPPER_ONLY),
        (PAGE_READ, NetworkRequestSender.UNKNOWN, UPPER_ONLY),
    ]
    assert judgment_rule_use_counts[RULE] == 0


def test_the_same_text_shown_by_two_calls_is_two_lines_that_each_count_the_trial_by_themselves(
    knowledge: ExportKnowledge,
):
    # A and B own the line in the result of `pip install A B` and the same text in `cat pip.log`, which the curl of a file fetch owns too.
    # The first line counts the trial for `package` by itself, while the second counts nothing and so does not mark the curl.
    pip_install_a, pip_install_b = (
        _result(network_request, (INSTALLED_LINE, INSTALLED_LINE_OF_LOG))
        for network_request in (
            PIP_INSTALL_A.network_request,
            PIP_INSTALL_B.network_request,
        )
    )
    judgment_rule_use_counts: Counter[str] = Counter()

    _, network_request_rows, trial_category_measure_rows = export_rows(
        READ_TRIAL,
        (pip_install_a, pip_install_b, CURL_OF_FILE_FETCH),
        knowledge=knowledge,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )

    assert [
        (row.category, row.received_measure_bound)
        for row in trial_category_measure_rows
    ] == [
        (PACKAGE, LOWER_AND_UPPER),
        (NetworkRequestCategory.FILE_FETCH, UPPER_ONLY),
    ]
    assert [
        row.is_among_success_line_owners_one_of_which_received
        for row in network_request_rows
    ] == [
        True,
        True,
        False,
    ]
    assert judgment_rule_use_counts[RULE] == 1


def test_two_lines_counting_the_trial_for_one_category_and_sender_ask_the_rule_once(
    knowledge: ExportKnowledge,
):
    pip_install_a, pip_install_b = (
        _result(network_request, (INSTALLED_LINE, INSTALLED_LINE_OF_LOG))
        for network_request in (
            PIP_INSTALL_A.network_request,
            PIP_INSTALL_B.network_request,
        )
    )
    judgment_rule_use_counts: Counter[str] = Counter()

    _, _, trial_category_measure_rows = export_rows(
        READ_TRIAL,
        (pip_install_a, pip_install_b),
        knowledge=knowledge,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )

    assert [row.received_measure_bound for row in trial_category_measure_rows] == [
        LOWER_AND_UPPER
    ]
    assert judgment_rule_use_counts[RULE] == 1


def test_a_category_that_a_row_already_counts_in_the_lower_bound_of_received_marks_no_row(
    knowledge: ExportKnowledge,
):
    # `apt-get install -y aaa bbb; ls` with an own `Get:1 ... bbb` line and a shared `Fetched 10 kB in`, made as two `pip install` requests that share `INSTALLED_LINE`. bbb is confirmed by its own line and counts the trial by itself, so the shared line raises nothing.
    apt_install_aaa = _result(_pip_install("aaa", 0))
    apt_install_bbb = _result(
        _pip_install("bbb", 1),
        (
            INSTALLED_LINE,
            OutputLineEvidence(INSTALL_CALL, 1, None, OutputLineKind.DOWNLOADED, False),
        ),
        (),
    )
    judgment_rule_use_counts: Counter[str] = Counter()

    _, network_request_rows, trial_category_measure_rows = export_rows(
        READ_TRIAL,
        (apt_install_aaa, apt_install_bbb),
        knowledge=knowledge,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )

    assert [row.received_measure_bound for row in network_request_rows] == [
        UPPER_ONLY,
        LOWER_AND_UPPER,
    ]
    assert [row.received_measure_bound for row in trial_category_measure_rows] == [
        LOWER_AND_UPPER
    ]
    assert not any(
        row.is_among_success_line_owners_one_of_which_received
        for row in network_request_rows
    )
    assert judgment_rule_use_counts[RULE] == 0


def _exported_marks_and_rule_uses(
    network_request_results: tuple[NetworkRequestResult, ...],
    knowledge: ExportKnowledge,
) -> tuple[list[bool], int]:
    """Give whether each row is among success line owners one of which received, and the uses of the rule."""
    judgment_rule_use_counts: Counter[str] = Counter()
    _, network_request_rows, _ = export_rows(
        READ_TRIAL,
        network_request_results,
        knowledge=knowledge,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )
    return [
        row.is_among_success_line_owners_one_of_which_received
        for row in network_request_rows
    ], judgment_rule_use_counts[RULE]


# A second line of success in the result of `pip install A B`, and lines 0 and 1 of the output string of a JSON object on its line 0, all 0-based.
SECOND_LINE = _shared_line(INSTALL_CALL, 1)
FIRST_LINE_OF_JSON_STRING = OutputLineEvidence(
    INSTALL_CALL, 0, 0, OutputLineKind.INSTALLED, True
)
SECOND_LINE_OF_JSON_STRING = OutputLineEvidence(
    INSTALL_CALL, 0, 1, OutputLineKind.INSTALLED, True
)


def _curl_owning(line: OutputLineEvidence) -> NetworkRequestResult:
    """Make the curl of a file fetch in the same call, assumed for the given shared line alone."""
    return _result(CURL_OF_FILE_FETCH.network_request, (line,))


def test_an_owner_assumed_for_another_line_alone_keeps_the_line_from_counting_the_trial(
    knowledge: ExportKnowledge,
):
    # A is received by line 0. X holds line 0 too, but is assumed only for line 1, which the curl of a file fetch shares, so X may have printed line 0 without receiving by it.
    pip_install_x = _result(
        _pip_install("X", 1), (INSTALLED_LINE, SECOND_LINE), (_reason_of(SECOND_LINE),)
    )

    assert _exported_marks_and_rule_uses(
        (PIP_INSTALL_A, pip_install_x, _curl_owning(SECOND_LINE)), knowledge
    ) == ([False] * 3, 0)


def test_a_line_that_no_owner_is_assumed_for_counts_nothing(knowledge: ExportKnowledge):
    # A and B hold lines 0 and 1, but are assumed only for line 1, which the curl of a file fetch shares too.
    pip_install_a, pip_install_b = (
        _result(
            network_request, (INSTALLED_LINE, SECOND_LINE), (_reason_of(SECOND_LINE),)
        )
        for network_request in (
            PIP_INSTALL_A.network_request,
            PIP_INSTALL_B.network_request,
        )
    )

    assert _exported_marks_and_rule_uses(
        (pip_install_a, pip_install_b, _curl_owning(SECOND_LINE)), knowledge
    ) == ([False] * 3, 0)


@pytest.mark.parametrize(
    ("line_counting_the_trial", "other_line"),
    [
        pytest.param(
            INSTALLED_LINE, SECOND_LINE, id="lines that differ in their index"
        ),
        pytest.param(
            FIRST_LINE_OF_JSON_STRING,
            SECOND_LINE_OF_JSON_STRING,
            id="lines that differ in their index in a JSON string",
        ),
    ],
)
def test_two_lines_of_one_call_are_told_apart_by_both_indexes(
    line_counting_the_trial: OutputLineEvidence,
    other_line: OutputLineEvidence,
    knowledge: ExportKnowledge,
):
    # A and B are assumed for the line that counts the trial, and the curl of a file fetch for the other line alone.
    pip_install_a, pip_install_b = (
        _result(network_request, (line_counting_the_trial,))
        for network_request in (
            PIP_INSTALL_A.network_request,
            PIP_INSTALL_B.network_request,
        )
    )

    assert _exported_marks_and_rule_uses(
        (pip_install_a, pip_install_b, _curl_owning(other_line)), knowledge
    ) == ([True, True, False], 1)


def test_every_owner_of_every_line_counting_the_trial_for_a_category_is_marked(
    knowledge: ExportKnowledge,
):
    # A and B own line 0, and C and D own line 1.
    network_request_results = tuple(
        _result(_pip_install(target, index), (line,))
        for index, (target, line) in enumerate(
            (
                ("A", INSTALLED_LINE),
                ("B", INSTALLED_LINE),
                ("C", SECOND_LINE),
                ("D", SECOND_LINE),
            )
        )
    )

    assert _exported_marks_and_rule_uses(network_request_results, knowledge) == (
        [True] * 4,
        1,
    )


def test_results_and_rows_of_other_numbers_are_refused(knowledge: ExportKnowledge):
    _, network_request_rows, _ = export_rows(
        READ_TRIAL,
        (PIP_INSTALL_A, PIP_INSTALL_B),
        knowledge=knowledge,
        judgment_rule_use_counts=Counter(),
    )

    with pytest.raises(
        ValueError, match="2 network request results and 1 request rows"
    ):
        mark_network_request_rows_among_success_line_owners(
            (PIP_INSTALL_A, PIP_INSTALL_B),
            network_request_rows[:1],
            judgment_rule_use_counts=Counter(),
        )
