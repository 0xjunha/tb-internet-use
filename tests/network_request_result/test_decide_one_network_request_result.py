"""Tests for _decide_one_network_request_result.py, with made-up evidence of one request built by hand as the piece that collects evidence would give it."""

import itertools
from collections import Counter

import pytest

from tb_internet_use.expanded_tool_call.model import (
    CallCommandText,
    FileUse,
    FileUseKind,
    ProgramInvocation,
)
from tb_internet_use.network_request.model import (
    ContentShownInResult,
    FromCommand,
    NetworkRequest,
    NetworkRequestCertainty,
    NetworkRequestTargetKind,
    NetworkRequestUncertaintyReason,
    NoContentRequested,
    ReceivedContentDestination,
)
from tb_internet_use.network_request_result import (
    _decide_one_network_request_result as decide_one_module,
)
from tb_internet_use.network_request_result._decide_one_network_request_result import (
    decide_one_network_request_result,
)
from tb_internet_use.network_request_result.judgment_rules import (
    treat_higher_evidence_beside_failure_as_assumed_level,
    treat_stop_reasons_of_one_level_as_first_in_fixed_order,
)
from tb_internet_use.network_request_result.model import (
    EvidenceWithLevel,
    ExecutionStatusEvidence,
    ExitCodeEvidence,
    FileUseEvidence,
    HttpStatusEvidence,
    NetworkRequestResult,
    NetworkRequestResultCertainty,
    NetworkRequestResultEvidence,
    NetworkRequestResultLevel,
    NetworkRequestResultStopReason,
    OutputLineEvidence,
    OutputLineKind,
    ShownContentEvidence,
)
from tb_internet_use.tool_call.model import ExecutionStatus, ToolCallKey

TOOL_CALL_KEY = ToolCallKey("trial", "main", 1, 0)
ATTEMPTED = NetworkRequestResultLevel.ATTEMPTED
EXECUTED = NetworkRequestResultLevel.EXECUTED
REACHED = NetworkRequestResultLevel.REACHED
RECEIVED = NetworkRequestResultLevel.RECEIVED
FAILED = NetworkRequestResultStopReason.FAILED
NOT_VISIBLE = NetworkRequestResultStopReason.NOT_VISIBLE
NOT_NEEDED = NetworkRequestResultStopReason.NOT_NEEDED
CONFIRMED = NetworkRequestResultCertainty.CONFIRMED
ASSUMED = NetworkRequestResultCertainty.ASSUMED
# The levels from the lowest to the highest.
LEVELS_IN_ORDER = (ATTEMPTED, EXECUTED, REACHED, RECEIVED)
RULE_6 = treat_higher_evidence_beside_failure_as_assumed_level.__name__
RULE_17 = treat_stop_reasons_of_one_level_as_first_in_fixed_order.__name__
PIP_INVOCATION = ProgramInvocation(
    program_name="pip",
    subcommand_words=("install",),
    options=(),
    arguments=("x",),
    gets_more_arguments_at_run_time=False,
    unread_words=(),
    exits_with_exit_code_of_next_program=False,
)


CONTENT_SHOWN_IN_RESULT = ContentShownInResult()


def build_network_request(
    *,
    certainty: NetworkRequestCertainty = NetworkRequestCertainty.CONFIRMED,
    received_content_destination: ReceivedContentDestination = CONTENT_SHOWN_IN_RESULT,
) -> NetworkRequest:
    return NetworkRequest(
        tool_call_key=TOOL_CALL_KEY,
        index_in_tool_call=0,
        source=FromCommand(0, CallCommandText(), PIP_INVOCATION),
        target="x",
        target_kind=NetworkRequestTargetKind.PACKAGE_NAME,
        host_names=(),
        received_content_destination=received_content_destination,
        certainty=certainty,
        uncertainty_reason=(
            None
            if certainty == NetworkRequestCertainty.CONFIRMED
            else NetworkRequestUncertaintyReason.FETCHES_ONLY_WHAT_IS_MISSING
        ),
    )


REQUEST_FOR_CONTENT = build_network_request()
# e.g. `curl -I https://a.org`, which succeeds at `REACHED`.
REQUEST_FOR_NO_CONTENT = build_network_request(
    received_content_destination=NoContentRequested()
)
# e.g. `npx tsc`, which fetches only what is missing.
UNCERTAIN_REQUEST = build_network_request(certainty=NetworkRequestCertainty.UNCERTAIN)


def with_level(
    evidence: NetworkRequestResultEvidence,
    level: NetworkRequestResultLevel,
    stop_reason: NetworkRequestResultStopReason | None,
    *,
    may_belong_to_another_request: bool = False,
    rests_on_judgment_rule: bool = False,
) -> EvidenceWithLevel:
    return EvidenceWithLevel(
        evidence,
        level,
        stop_reason,
        may_belong_to_another_request,
        rests_on_judgment_rule,
    )


def output_line(
    kind: OutputLineKind, *, line_index: int = 0, is_shared: bool = False
) -> OutputLineEvidence:
    return OutputLineEvidence(TOOL_CALL_KEY, line_index, None, kind, is_shared)


def decide(
    network_request: NetworkRequest, evidence_with_levels: list[EvidenceWithLevel]
) -> tuple[NetworkRequestResult, Counter[str]]:
    judgment_rule_use_counts: Counter[str] = Counter()
    result = decide_one_network_request_result(
        network_request,
        evidence_with_levels,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )
    return result, judgment_rule_use_counts


EXIT_CODE_0 = ExitCodeEvidence(TOOL_CALL_KEY, 0, True)
# `wget -O x u` that prints `Connection refused` and then `saved [10/10]`.
CONNECTION_REFUSED = with_level(
    output_line(OutputLineKind.CONNECTION_FAILED), EXECUTED, FAILED
)
SAVED = with_level(output_line(OutputLineKind.DOWNLOADED, line_index=1), RECEIVED, None)
# `curl -i -L u` that prints `HTTP/1.1 404 Not Found` and then `HTTP/1.1 200 OK`.
HTTP_404 = with_level(output_line(OutputLineKind.HTTP_STATUS), REACHED, FAILED)
HTTP_200 = with_level(
    output_line(OutputLineKind.HTTP_STATUS, line_index=1), REACHED, NOT_VISIBLE
)
EXIT_CODE_0_RAN = with_level(EXIT_CODE_0, EXECUTED, NOT_VISIBLE)
# Exit 0 of `curl` that `treat_exit_code_meaning_as_assumed_level` reads as an answer of a server.
EXIT_CODE_0_READ_AS_ANSWER = with_level(
    EXIT_CODE_0, REACHED, NOT_VISIBLE, rests_on_judgment_rule=True
)
# `Successfully installed x-1.0`, which `treat_installed_line_as_no_evidence_of_download` reads as a run only.
INSTALLED = with_level(
    output_line(OutputLineKind.INSTALLED, line_index=2), EXECUTED, NOT_VISIBLE
)
USES_SAVED_FILE = with_level(
    FileUseEvidence(
        FileUse(
            TOOL_CALL_KEY, 1, FileUseKind.USES_CONTENT, fits_several_written_files=False
        )
    ),
    RECEIVED,
    None,
)
SHOWN_CONTENT = with_level(
    ShownContentEvidence(TOOL_CALL_KEY), RECEIVED, None, rests_on_judgment_rule=True
)

# (request, evidence, expected level, stop reason and certainty, expected rule uses)
RESULT_CASES = [
    # The eight rows of the result table, one evidence each.
    pytest.param(
        REQUEST_FOR_CONTENT,
        [SAVED],
        (RECEIVED, None, CONFIRMED),
        {},
        id="received, e.g. wget `saved [1024/1024]`",
    ),
    pytest.param(
        REQUEST_FOR_CONTENT,
        [HTTP_404],
        (REACHED, FAILED, CONFIRMED),
        {},
        id="reached and failed, e.g. `HTTP/1.1 404 Not Found` of `curl -i u`",
    ),
    pytest.param(
        REQUEST_FOR_CONTENT,
        [with_level(output_line(OutputLineKind.NAME_NOT_RESOLVED), EXECUTED, FAILED)],
        (EXECUTED, FAILED, CONFIRMED),
        {},
        id="executed and failed, e.g. `curl: (6) Could not resolve host: a.org`",
    ),
    pytest.param(
        REQUEST_FOR_CONTENT,
        [with_level(output_line(OutputLineKind.PROGRAM_MISSING), ATTEMPTED, FAILED)],
        (ATTEMPTED, FAILED, CONFIRMED),
        {},
        id="attempted and failed, e.g. `bash: pip3: command not found`",
    ),
    pytest.param(
        REQUEST_FOR_CONTENT,
        [with_level(output_line(OutputLineKind.SERVER_ANSWERED), REACHED, NOT_VISIBLE)],
        (REACHED, NOT_VISIBLE, CONFIRMED),
        {},
        id="reached and content not visible, e.g. apt `Hit:1` of `apt-get update`",
    ),
    pytest.param(
        REQUEST_FOR_CONTENT,
        [EXIT_CODE_0_RAN],
        (EXECUTED, NOT_VISIBLE, CONFIRMED),
        {},
        id="executed and output not visible, e.g. `pip install -q A B` with exit 0 that both requests share",
    ),
    pytest.param(
        REQUEST_FOR_CONTENT,
        [],
        (ATTEMPTED, NOT_VISIBLE, CONFIRMED),
        {},
        id="attempted and not visible without evidence, e.g. `test -f x || curl -s u -o x`",
    ),
    pytest.param(
        REQUEST_FOR_CONTENT,
        [with_level(output_line(OutputLineKind.ALREADY_PRESENT), EXECUTED, NOT_NEEDED)],
        (EXECUTED, NOT_NEEDED, CONFIRMED),
        {},
        id="executed and not needed, e.g. `Requirement already satisfied: x`",
    ),
    # Each kind of evidence that the rows above do not use, alone.
    pytest.param(
        REQUEST_FOR_CONTENT,
        [with_level(HttpStatusEvidence(TOOL_CALL_KEY, 404), REACHED, FAILED)],
        (REACHED, FAILED, CONFIRMED),
        {},
        id="status 404 of a web fetch",
    ),
    pytest.param(
        REQUEST_FOR_CONTENT,
        [
            with_level(
                ExecutionStatusEvidence(TOOL_CALL_KEY, ExecutionStatus.NOT_RUN, True),
                ATTEMPTED,
                FAILED,
            )
        ],
        (ATTEMPTED, FAILED, CONFIRMED),
        {},
        id="call marked not run, shared by the requests of `curl u; pip install y`, stays confirmed",
    ),
    pytest.param(
        REQUEST_FOR_CONTENT,
        [EXIT_CODE_0_RAN, USES_SAVED_FILE],
        (RECEIVED, None, CONFIRMED),
        {},
        id="`tar xzf a.tgz` that surely ran after `curl -s -o a.tgz u`",
    ),
    pytest.param(
        REQUEST_FOR_CONTENT,
        [SHOWN_CONTENT],
        (RECEIVED, None, ASSUMED),
        {},
        id="text of a web search resting on a rule is assumed, also for `cat page.html` and a saved file that may not have been used",
    ),
    # A request that asks for no content succeeds at `REACHED`.
    pytest.param(
        REQUEST_FOR_NO_CONTENT,
        [with_level(output_line(OutputLineKind.HTTP_STATUS), REACHED, None)],
        (REACHED, None, CONFIRMED),
        {},
        id="`HTTP/1.1 200 OK` of `curl -I u`",
    ),
    pytest.param(
        REQUEST_FOR_NO_CONTENT,
        [with_level(output_line(OutputLineKind.DOWNLOADED), REACHED, None)],
        (REACHED, None, CONFIRMED),
        {},
        id="a downloaded line of a request that asks for no content",
    ),
    pytest.param(
        REQUEST_FOR_NO_CONTENT,
        [HTTP_404, with_level(HTTP_200.evidence, REACHED, None)],
        (REACHED, None, ASSUMED),
        {RULE_17: 1},
        id="404 and then 200 of `curl -I -L u` pick no stop reason by the rule",
    ),
    # Shared evidence and evidence that rests on a rule.
    pytest.param(
        REQUEST_FOR_CONTENT,
        [
            with_level(
                output_line(OutputLineKind.CONNECTION_FAILED, is_shared=True),
                EXECUTED,
                FAILED,
                may_belong_to_another_request=True,
            )
        ],
        (EXECUTED, FAILED, ASSUMED),
        {},
        id="one `curl: (7) Connection refused` under `curl a; curl b`",
    ),
    pytest.param(
        REQUEST_FOR_CONTENT,
        [
            with_level(
                output_line(OutputLineKind.TLS_FAILED),
                EXECUTED,
                FAILED,
                rests_on_judgment_rule=True,
            )
        ],
        (EXECUTED, FAILED, ASSUMED),
        {},
        id="`SSL certificate problem` that a rule reads as before the server",
    ),
    pytest.param(
        REQUEST_FOR_CONTENT,
        [
            with_level(
                output_line(OutputLineKind.CONNECTED),
                REACHED,
                NOT_VISIBLE,
                rests_on_judgment_rule=True,
            ),
            EXIT_CODE_0_RAN,
        ],
        (REACHED, NOT_VISIBLE, ASSUMED),
        {},
        id="`* Connected to a.org` resting on a rule beside clean exit 0 at a lower level",
    ),
    pytest.param(
        REQUEST_FOR_CONTENT,
        [EXIT_CODE_0_READ_AS_ANSWER, USES_SAVED_FILE],
        (RECEIVED, None, CONFIRMED),
        {},
        id="`curl -s -o a.tgz u && tar xzf a.tgz` with exit 0 keeps the exit code as evidence",
    ),
    pytest.param(
        REQUEST_FOR_CONTENT,
        [
            with_level(
                output_line(OutputLineKind.DOWNLOADED, is_shared=True),
                RECEIVED,
                None,
                may_belong_to_another_request=True,
            ),
            USES_SAVED_FILE,
        ],
        (RECEIVED, None, CONFIRMED),
        {},
        id="shared downloaded line beside a sure use of the saved file",
    ),
    pytest.param(
        REQUEST_FOR_CONTENT,
        [
            with_level(
                output_line(OutputLineKind.DOWNLOAD_STARTED), REACHED, NOT_VISIBLE
            ),
            INSTALLED,
        ],
        (REACHED, NOT_VISIBLE, CONFIRMED),
        {},
        id="`Downloading x.whl` and `Successfully installed x-1.0` without a downloaded line",
    ),
    pytest.param(
        REQUEST_FOR_CONTENT,
        [
            with_level(HttpStatusEvidence(TOOL_CALL_KEY, 200), REACHED, NOT_VISIBLE),
            SHOWN_CONTENT,
        ],
        (RECEIVED, None, ASSUMED),
        {},
        id="web fetch with status 200 and page text",
    ),
    # A failure beside higher evidence.
    pytest.param(
        REQUEST_FOR_CONTENT,
        [CONNECTION_REFUSED, SAVED],
        (RECEIVED, None, ASSUMED),
        {RULE_6: 1},
        id="clean `saved [10/10]` after `Connection refused` is assumed, also `Successfully downloaded x` after `Connection reset by peer`",
    ),
    pytest.param(
        REQUEST_FOR_CONTENT,
        [CONNECTION_REFUSED, HTTP_404, HTTP_200],
        (REACHED, FAILED, ASSUMED),
        {RULE_6: 1, RULE_17: 1},
        id="a failure below a level whose stop reasons the rule picks from",
    ),
    # Two stop reasons at one level.
    pytest.param(
        REQUEST_FOR_CONTENT,
        [HTTP_404, HTTP_200],
        (REACHED, FAILED, ASSUMED),
        {RULE_17: 1},
        id="`HTTP/1.1 404` and `HTTP/1.1 200` of `curl -i -L u`",
    ),
    pytest.param(
        REQUEST_FOR_CONTENT,
        [EXIT_CODE_0_RAN, CONNECTION_REFUSED],
        (EXECUTED, FAILED, ASSUMED),
        {RULE_17: 1},
        id="`Connection refused` of `pip install x` that ended with exit 0",
    ),
    pytest.param(
        REQUEST_FOR_CONTENT,
        [CONNECTION_REFUSED, INSTALLED],
        (EXECUTED, FAILED, ASSUMED),
        {RULE_17: 1},
        id="`Connection refused` and `Successfully installed x-1.0`",
    ),
    pytest.param(
        REQUEST_FOR_CONTENT,
        [
            with_level(
                output_line(OutputLineKind.ALREADY_PRESENT), EXECUTED, NOT_NEEDED
            ),
            CONNECTION_REFUSED,
        ],
        (EXECUTED, FAILED, ASSUMED),
        {RULE_17: 1},
        id="`Requirement already satisfied: x` and `Connection refused`",
    ),
    pytest.param(
        REQUEST_FOR_CONTENT,
        [
            with_level(
                output_line(OutputLineKind.ALREADY_PRESENT), EXECUTED, NOT_NEEDED
            ),
            EXIT_CODE_0_RAN,
        ],
        (EXECUTED, NOT_NEEDED, CONFIRMED),
        {},
        id="`Requirement already satisfied: x` and exit 0 need no rule",
    ),
    pytest.param(
        REQUEST_FOR_CONTENT,
        [
            EXIT_CODE_0_RAN,
            with_level(
                output_line(OutputLineKind.ALREADY_PRESENT),
                EXECUTED,
                NOT_NEEDED,
                rests_on_judgment_rule=True,
            ),
        ],
        (EXECUTED, NOT_NEEDED, ASSUMED),
        {},
        id="`Requirement already satisfied: x` under `pip install -r reqs.txt` with exit 0 rests on the rule, not on the exit code",
    ),
    pytest.param(
        REQUEST_FOR_CONTENT,
        [HTTP_404, EXIT_CODE_0_READ_AS_ANSWER],
        (REACHED, FAILED, CONFIRMED),
        {},
        id="`HTTP/1.1 404` and exit 0 of `curl -i u` need no rule",
    ),
    pytest.param(
        REQUEST_FOR_CONTENT,
        [
            with_level(
                output_line(OutputLineKind.ALREADY_PRESENT), EXECUTED, NOT_NEEDED
            ),
            with_level(
                output_line(OutputLineKind.SERVER_ANSWERED, line_index=1),
                REACHED,
                NOT_VISIBLE,
            ),
        ],
        (REACHED, NOT_VISIBLE, CONFIRMED),
        {},
        id="`NOT_NEEDED` below a server answer is no failure and needs no rule",
    ),
    # The request's own lines decide the stop reason at their level, and a line it shares with another request gives none there.
    pytest.param(
        REQUEST_FOR_CONTENT,
        [
            with_level(
                output_line(OutputLineKind.BARE_STATUS_CODE), REACHED, NOT_VISIBLE
            ),
            with_level(
                output_line(OutputLineKind.HTTP_STATUS, line_index=1, is_shared=True),
                REACHED,
                FAILED,
                may_belong_to_another_request=True,
            ),
        ],
        (REACHED, NOT_VISIBLE, CONFIRMED),
        {},
        id="own `200` of `curl -s -w %{http_code} u` beside a shared `HTTP/1.1 405` of `curl -s v`",
    ),
    pytest.param(
        REQUEST_FOR_CONTENT,
        [
            HTTP_404,
            with_level(
                output_line(OutputLineKind.HTTP_STATUS, line_index=1, is_shared=True),
                REACHED,
                NOT_VISIBLE,
                may_belong_to_another_request=True,
            ),
        ],
        (REACHED, FAILED, CONFIRMED),
        {},
        id="own `HTTP/1.1 404` beside a shared `HTTP/1.1 200` needs no rule",
    ),
    pytest.param(
        REQUEST_FOR_CONTENT,
        [
            EXIT_CODE_0_READ_AS_ANSWER,
            with_level(
                output_line(OutputLineKind.HTTP_STATUS, is_shared=True),
                REACHED,
                FAILED,
                may_belong_to_another_request=True,
            ),
        ],
        (REACHED, FAILED, ASSUMED),
        {},
        id="a shared `HTTP/1.1 404` still gives the stop reason beside exit 0 alone",
    ),
]


@pytest.mark.parametrize(
    ("network_request", "evidence_with_levels", "expected", "expected_rule_uses"),
    RESULT_CASES,
)
def test_decide_one_network_request_result_combines_the_evidence_into_one_level_stop_reason_and_certainty(
    network_request: NetworkRequest,
    evidence_with_levels: list[EvidenceWithLevel],
    expected: tuple[
        NetworkRequestResultLevel,
        NetworkRequestResultStopReason | None,
        NetworkRequestResultCertainty,
    ],
    expected_rule_uses: dict[str, int],
):
    result, judgment_rule_use_counts = decide(network_request, evidence_with_levels)

    assert (result.level, result.stop_reason, result.level_certainty) == expected
    assert result.evidence == tuple(
        evidence_with_level.evidence for evidence_with_level in evidence_with_levels
    )
    assert result.network_request == network_request
    assert judgment_rule_use_counts == Counter(expected_rule_uses)


# Evidence of `NOT_VISIBLE` beside a failure at the same level, with whether it shows that the request may have gone on after the failure.
GOING_ON_CASES = [
    pytest.param(HTTP_404, HTTP_200, True, id="status line below 400"),
    pytest.param(
        HTTP_404,
        with_level(output_line(OutputLineKind.BARE_STATUS_CODE), REACHED, NOT_VISIBLE),
        True,
        id="`200` printed by `curl -w '%{http_code}'`",
    ),
    pytest.param(
        HTTP_404,
        with_level(HttpStatusEvidence(TOOL_CALL_KEY, 200), REACHED, NOT_VISIBLE),
        True,
        id="status 200 of a web fetch",
    ),
    pytest.param(
        HTTP_404,
        with_level(output_line(OutputLineKind.SERVER_ANSWERED), REACHED, NOT_VISIBLE),
        True,
        id="apt `Hit:1`",
    ),
    pytest.param(
        HTTP_404,
        with_level(output_line(OutputLineKind.DOWNLOAD_STARTED), REACHED, NOT_VISIBLE),
        True,
        id="pip `Downloading x.whl`",
    ),
    pytest.param(
        HTTP_404,
        with_level(
            output_line(OutputLineKind.CONNECTED),
            REACHED,
            NOT_VISIBLE,
            rests_on_judgment_rule=True,
        ),
        False,
        id="`* Connected to a.org`",
    ),
    pytest.param(
        HTTP_404,
        EXIT_CODE_0_READ_AS_ANSWER,
        False,
        id="exit 0 that a rule reads as an answer",
    ),
    pytest.param(
        CONNECTION_REFUSED,
        with_level(output_line(OutputLineKind.VERSION_NOTICE), EXECUTED, NOT_VISIBLE),
        False,
        id="`[notice] A new release of pip is available`",
    ),
    pytest.param(
        CONNECTION_REFUSED,
        with_level(
            ExecutionStatusEvidence(TOOL_CALL_KEY, ExecutionStatus.FINISHED, False),
            EXECUTED,
            NOT_VISIBLE,
        ),
        False,
        id="finished call of a web tool",
    ),
    pytest.param(
        CONNECTION_REFUSED,
        with_level(
            output_line(OutputLineKind.DOWNLOAD_STARTED),
            EXECUTED,
            NOT_VISIBLE,
        ),
        False,
        id="`Downloading B.whl` under `pip install A`, read as a run only",
    ),
]


@pytest.mark.parametrize(("failure", "not_visible", "may_have_gone_on"), GOING_ON_CASES)
def test_decide_one_network_request_result_asks_the_rule_only_when_evidence_shows_the_request_may_have_gone_on_after_a_failure(
    failure: EvidenceWithLevel,
    not_visible: EvidenceWithLevel,
    may_have_gone_on: bool,
):
    result, judgment_rule_use_counts = decide(
        REQUEST_FOR_CONTENT, [failure, not_visible]
    )

    assert (result.level, result.stop_reason) == (failure.level, FAILED)
    if may_have_gone_on:
        assert result.level_certainty == ASSUMED
        assert judgment_rule_use_counts == Counter({RULE_17: 1})
    else:
        assert result.level_certainty == CONFIRMED
        assert judgment_rule_use_counts == Counter()


@pytest.mark.parametrize(
    ("evidence_with_levels", "expected"),
    [
        pytest.param(
            [CONNECTION_REFUSED, SAVED],
            (EXECUTED, FAILED, CONFIRMED),
            id="clean failure",
        ),
        pytest.param(
            [
                with_level(
                    output_line(OutputLineKind.PROGRAM_MISSING), ATTEMPTED, FAILED
                ),
                with_level(
                    CONNECTION_REFUSED.evidence,
                    EXECUTED,
                    FAILED,
                    may_belong_to_another_request=True,
                ),
                SAVED,
            ],
            (EXECUTED, FAILED, ASSUMED),
            id="the highest failure, shared",
        ),
    ],
)
def test_decide_one_network_request_result_takes_the_highest_failure_when_the_rule_on_higher_evidence_beside_a_failure_says_no(
    monkeypatch: pytest.MonkeyPatch,
    evidence_with_levels: list[EvidenceWithLevel],
    expected: tuple[
        NetworkRequestResultLevel,
        NetworkRequestResultStopReason | None,
        NetworkRequestResultCertainty,
    ],
):
    rule_uses: list[None] = []

    def answer_no(*, use_counts: Counter[str]) -> bool:
        rule_uses.append(None)
        return False

    monkeypatch.setattr(
        decide_one_module,
        treat_higher_evidence_beside_failure_as_assumed_level.__name__,
        answer_no,
    )

    result, _ = decide(REQUEST_FOR_CONTENT, evidence_with_levels)

    assert (result.level, result.stop_reason, result.level_certainty) == expected
    assert len(rule_uses) == 1


def test_decide_one_network_request_result_takes_the_stop_reason_that_the_rule_on_stop_reasons_of_one_level_picks(
    monkeypatch: pytest.MonkeyPatch,
):
    asked_stop_reasons: list[set[NetworkRequestResultStopReason | None]] = []

    def pick_not_visible(
        stop_reasons: set[NetworkRequestResultStopReason | None],
        *,
        use_counts: Counter[str],
    ) -> NetworkRequestResultStopReason | None:
        asked_stop_reasons.append(set(stop_reasons))
        return NOT_VISIBLE

    monkeypatch.setattr(
        decide_one_module,
        treat_stop_reasons_of_one_level_as_first_in_fixed_order.__name__,
        pick_not_visible,
    )

    result, _ = decide(REQUEST_FOR_CONTENT, [HTTP_404, HTTP_200])

    assert (result.level, result.stop_reason, result.level_certainty) == (
        REACHED,
        NOT_VISIBLE,
        ASSUMED,
    )
    assert asked_stop_reasons == [{FAILED, NOT_VISIBLE}]


# A clean output line of each kind at a level it can show, with whether it shows that the request was sent.
SENT_REQUEST_LINE_CASES = [
    (OutputLineKind.NAME_NOT_RESOLVED, EXECUTED, FAILED, True),
    (OutputLineKind.CONNECTION_FAILED, EXECUTED, FAILED, True),
    (OutputLineKind.CONNECTION_LOST, EXECUTED, FAILED, False),
    (OutputLineKind.PROXY_REFUSED, EXECUTED, FAILED, False),
    (OutputLineKind.TLS_FAILED, EXECUTED, FAILED, False),
    (OutputLineKind.CONNECTED, EXECUTED, NOT_VISIBLE, False),
    (OutputLineKind.HTTP_STATUS, REACHED, NOT_VISIBLE, True),
    (OutputLineKind.SERVER_ANSWERED, REACHED, NOT_VISIBLE, True),
    (OutputLineKind.NOT_FOUND, REACHED, FAILED, True),
    (OutputLineKind.ALREADY_PRESENT, EXECUTED, NOT_NEEDED, False),
    (OutputLineKind.PROGRAM_MISSING, ATTEMPTED, FAILED, False),
    (OutputLineKind.REFUSED_LOCALLY, EXECUTED, FAILED, False),
    (OutputLineKind.VERSION_NOTICE, EXECUTED, NOT_VISIBLE, False),
    (OutputLineKind.DOWNLOAD_STARTED, REACHED, NOT_VISIBLE, True),
    (OutputLineKind.DOWNLOADED, RECEIVED, None, True),
    (OutputLineKind.INSTALLED, EXECUTED, NOT_VISIBLE, False),
    # A bare `200` read as a status code, and `000`, which shows that no answer came.
    (OutputLineKind.BARE_STATUS_CODE, REACHED, NOT_VISIBLE, True),
    (OutputLineKind.BARE_STATUS_CODE, EXECUTED, FAILED, False),
]


def test_sent_request_line_cases_cover_every_output_line_kind():
    assert {kind for kind, _, _, _ in SENT_REQUEST_LINE_CASES} == set(OutputLineKind)


@pytest.mark.parametrize(
    ("kind", "level", "stop_reason", "shows_sent_request"), SENT_REQUEST_LINE_CASES
)
def test_decide_one_network_request_result_lifts_an_uncertain_request_by_a_line_that_shows_it_was_sent(
    kind: OutputLineKind,
    level: NetworkRequestResultLevel,
    stop_reason: NetworkRequestResultStopReason | None,
    shows_sent_request: bool,
):
    result, _ = decide(
        UNCERTAIN_REQUEST, [with_level(output_line(kind), level, stop_reason)]
    )

    assert result.request_certainty_after_evidence == (
        NetworkRequestCertainty.CONFIRMED
        if shows_sent_request
        else NetworkRequestCertainty.UNCERTAIN
    )


@pytest.mark.parametrize(
    "evidence_with_level",
    [
        pytest.param(
            with_level(
                output_line(OutputLineKind.HTTP_STATUS),
                REACHED,
                NOT_VISIBLE,
                may_belong_to_another_request=True,
            ),
            id="`HTTP/1.1 200 OK` of `mytool https://a.org/x`, whose lines are not known",
        ),
        pytest.param(
            with_level(
                output_line(OutputLineKind.HTTP_STATUS),
                REACHED,
                NOT_VISIBLE,
                rests_on_judgment_rule=True,
            ),
            id="`HTTP/1.1 200 OK` beside the text of a file that no call wrote",
        ),
        pytest.param(EXIT_CODE_0_RAN, id="exit 0 of `sbt compile`"),
        pytest.param(
            with_level(HttpStatusEvidence(TOOL_CALL_KEY, 200), REACHED, NOT_VISIBLE),
            id="status 200 of a web fetch",
        ),
    ],
)
def test_decide_one_network_request_result_keeps_an_uncertain_request_without_a_clean_line_that_shows_it_was_sent(
    evidence_with_level: EvidenceWithLevel,
):
    result, _ = decide(UNCERTAIN_REQUEST, [evidence_with_level])

    assert result.request_certainty_after_evidence == NetworkRequestCertainty.UNCERTAIN


# One example of each kind of evidence at each level and stop reason it can show for a request that asks for content.
EVIDENCE_EXAMPLES_OF_REQUEST_FOR_CONTENT = [
    SAVED,
    SHOWN_CONTENT,
    USES_SAVED_FILE,
    with_level(EXIT_CODE_0, RECEIVED, None, rests_on_judgment_rule=True),
    HTTP_404,
    HTTP_200,
    with_level(
        HTTP_200.evidence, REACHED, NOT_VISIBLE, may_belong_to_another_request=True
    ),
    with_level(HttpStatusEvidence(TOOL_CALL_KEY, 200), REACHED, NOT_VISIBLE),
    with_level(
        output_line(OutputLineKind.CONNECTED),
        REACHED,
        NOT_VISIBLE,
        rests_on_judgment_rule=True,
    ),
    EXIT_CODE_0_READ_AS_ANSWER,
    with_level(
        output_line(OutputLineKind.CONNECTION_LOST),
        REACHED,
        FAILED,
        rests_on_judgment_rule=True,
    ),
    CONNECTION_REFUSED,
    INSTALLED,
    EXIT_CODE_0_RAN,
    with_level(
        ExecutionStatusEvidence(TOOL_CALL_KEY, ExecutionStatus.FINISHED, False),
        EXECUTED,
        NOT_VISIBLE,
    ),
    with_level(output_line(OutputLineKind.ALREADY_PRESENT), EXECUTED, NOT_NEEDED),
    with_level(
        output_line(OutputLineKind.ALREADY_PRESENT),
        EXECUTED,
        NOT_NEEDED,
        rests_on_judgment_rule=True,
    ),
    with_level(output_line(OutputLineKind.PROGRAM_MISSING), ATTEMPTED, FAILED),
    with_level(
        ExecutionStatusEvidence(TOOL_CALL_KEY, ExecutionStatus.NOT_RUN, True),
        ATTEMPTED,
        FAILED,
    ),
]
# The same for a request that asks for no content, which succeeds at `REACHED`.
EVIDENCE_EXAMPLES_OF_REQUEST_FOR_NO_CONTENT = [
    with_level(evidence_with_level.evidence, REACHED, None)
    if evidence_with_level.level == RECEIVED
    else evidence_with_level
    for evidence_with_level in EVIDENCE_EXAMPLES_OF_REQUEST_FOR_CONTENT
]


@pytest.mark.parametrize(
    ("network_request", "evidence_examples"),
    [
        (REQUEST_FOR_CONTENT, EVIDENCE_EXAMPLES_OF_REQUEST_FOR_CONTENT),
        (UNCERTAIN_REQUEST, EVIDENCE_EXAMPLES_OF_REQUEST_FOR_CONTENT),
        (REQUEST_FOR_NO_CONTENT, EVIDENCE_EXAMPLES_OF_REQUEST_FOR_NO_CONTENT),
    ],
)
def test_decide_one_network_request_result_gives_a_result_the_model_accepts_for_every_two_pieces_of_evidence(
    network_request: NetworkRequest,
    evidence_examples: list[EvidenceWithLevel],
):
    for first, second in itertools.product(evidence_examples, repeat=2):
        result, judgment_rule_use_counts = decide(network_request, [first, second])

        assert result.level == max(first.level, second.level, key=LEVELS_IN_ORDER.index)
        assert result.stop_reason in {
            evidence_with_level.stop_reason
            for evidence_with_level in (first, second)
            if evidence_with_level.level == result.level
        } | {NOT_VISIBLE}
        if judgment_rule_use_counts:
            assert result.level_certainty == ASSUMED
