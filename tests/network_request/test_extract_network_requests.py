"""Tests for network_request/_extract_network_requests.py, with made-up tool calls run through the real `expand_tool_calls` and the real knowledge classes.

Most cases use made-up catalogs whose rows the cases name, so that they do not change when the real catalogs gain rows, and the last two tests use the real catalogs, so that a row missing there fails.

The first case follows the made-up trial of `docs/pipeline-example.md` with whole `NetworkRequest` values. The next ones take one kind of target or one answer about a means each, then the order of the requests, their indexes and the counts.
"""

import csv
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from tb_internet_use.expanded_tool_call import (
    _expand_program_invocations,
    expand_tool_calls,
)
from tb_internet_use.expanded_tool_call.judgment_rules import (
    treat_word_with_expansion_as_start_of_unread_words,
)
from tb_internet_use.expanded_tool_call.model import (
    ArgumentText,
    CallCommandText,
    FileText,
    ProgramInvocation,
    ProgramOption,
    ScriptStepText,
    UnknownExitsWithExitCodeOfNextProgram,
)
from tb_internet_use.knowledge.expanded_tool_call_knowledge import (
    CODE_RUNNERS_CSV,
    PROGRAM_BEHAVIORS_CSV,
    PROGRAM_OPTION_BEHAVIORS_CSV,
    ExpandedToolCallKnowledge,
)
from tb_internet_use.knowledge.network_request_knowledge import (
    CODE_CALLS_CSV,
    PROGRAM_NETWORK_REQUESTS_CSV,
    NetworkRequestKnowledge,
)
from tb_internet_use.network_request import extract_network_requests
from tb_internet_use.network_request.judgment_rules import (
    treat_call_name_that_ends_with_catalog_name_as_that_call,
    treat_single_label_or_templated_host_name_as_possibly_public,
    treat_web_find_as_request,
)
from tb_internet_use.network_request.model import (
    ContentSaved,
    FromCode,
    FromCommand,
    FromWebTool,
    NetworkRequest,
    NetworkRequestCertainty,
    NetworkRequestTargetKind,
    NetworkRequestUncertaintyReason,
    NoNetworkRequestReason,
    UnknownNetworkRequestTarget,
    UnknownNetworkRequestTargetReason,
)
from tb_internet_use.tool_call.model import (
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessTool,
    HarnessToolCall,
    PollAction,
    ReadFileAction,
    RunCommandAction,
    RunToolScriptAction,
    ToolCall,
    ToolCallAction,
    ToolCallKey,
    ToolCallResult,
    WebFetchAction,
    WebFindAction,
    WebSearchAction,
    WriteFileAction,
)
from tb_internet_use.tool_call.parse_shell_text import parse_shell_text

CONFIRMED = NetworkRequestCertainty.CONFIRMED
UNCERTAIN = NetworkRequestCertainty.UNCERTAIN
Reason = NetworkRequestUncertaintyReason
PACKAGE_NAME = NetworkRequestTargetKind.PACKAGE_NAME
REPOSITORY_URL = NetworkRequestTargetKind.REPOSITORY_URL
URL = NetworkRequestTargetKind.URL
NAMED_IN_FILE = UnknownNetworkRequestTarget(
    UnknownNetworkRequestTargetReason.NAMED_IN_FILE
)
VALUE_SET_AT_RUN_TIME = UnknownNetworkRequestTarget(
    UnknownNetworkRequestTargetReason.VALUE_SET_AT_RUN_TIME
)
UNREAD_WORDS = UnknownNetworkRequestTarget(
    UnknownNetworkRequestTargetReason.UNREAD_WORDS
)
FINISHED = ToolCallResult(
    tool_output_text="", execution_status=ExecutionStatus.FINISHED, exit_code=0
)
TASK_1 = ExecutionHandle(ExecutionHandleKind.COMMAND, "task-1")
TOOL = HarnessTool("harness", "tool")

# Made-up rows of `program_behaviors.csv`, each with the cells that differ from `_PROGRAM_BEHAVIOR_DEFAULTS`. mytool and tsc have no row.
PROGRAM_BEHAVIOR_ROWS: list[dict[str, str]] = [
    {
        "program_name": "bash",
        "first_argument_role": "run_file",
        "stdin_role": "run_text",
        "options_end_at_first_argument": "yes",
    },
    {
        "program_name": "python",
        "first_argument_role": "run_file",
        "stdin_role": "run_text",
        "options_end_at_first_argument": "yes",
    },
    {
        "program_name": "npx",
        "argument_role": "program",
        "options_end_at_first_argument": "yes",
    },
    {
        "program_name": "curl",
        "argument_role": "",
        "exits_with_exit_code_of_next_program": "",
    },
    {"program_name": "pip", "subcommand": "install", "argument_role": ""},
    {"program_name": "apt-get", "subcommand": "update"},
    {"program_name": "echo"},
    {"program_name": "cat", "argument_role": "read_file", "stdin_role": "read_file"},
]
# Made-up rows of `program_option_behaviors.csv`, each with the cells that differ from `_PROGRAM_OPTION_BEHAVIOR_DEFAULTS`.
PROGRAM_OPTION_BEHAVIOR_ROWS: list[dict[str, str]] = [
    {
        "program_name": "bash",
        "option_name": "-c",
        "first_argument_role_with_option": "run_text",
    },
    {
        "program_name": "python",
        "option_name": "-c",
        "first_argument_role_with_option": "run_text",
    },
    {"program_name": "curl", "option_name": "-s"},
    {"program_name": "curl", "option_name": "-S"},
    {"program_name": "curl", "option_name": "-L"},
    {
        "program_name": "curl",
        "option_name": "-O",
        "argument_role_with_option": "written_file_source",
    },
    {
        "program_name": "curl",
        "option_name": "-o",
        "takes_value": "yes",
        "value_role": "written_file",
    },
    {
        "program_name": "curl",
        "option_name": "--connect-timeout",
        "takes_value": "yes",
        "value_role": "other",
    },
    {
        "program_name": "pip",
        "subcommand": "install",
        "option_name": "-r",
        "takes_value": "yes",
        "value_role": "other",
    },
]
CODE_RUNNER_ROWS: list[dict[str, str]] = [
    {"runner_kind": "program_name", "runner": "bash", "ran_text_language": "shell"},
    {"runner_kind": "program_name", "runner": "python", "ran_text_language": "python"},
]
# Made-up rows of `program_network_requests.csv`, each with the cells that differ from `_PROGRAM_NETWORK_REQUEST_DEFAULTS`. curl has no row for -L.
PROGRAM_NETWORK_REQUEST_ROWS: list[dict[str, str]] = [
    {
        "program_name": "curl",
        "fetches": "yes",
        "target_arguments": "all",
        "target_kind": "url",
        "target_notation": "url_or_schemeless_url",
        "target_without_target_arguments": "no_request",
        "content_route": "stdout",
    },
    *(
        {"program_name": "curl", "option_name": option_name, "option_effect": "none"}
        for option_name in ("-s", "-S", "--connect-timeout")
    ),
    *(
        {
            "program_name": "curl",
            "option_name": option_name,
            "option_effect": "sends_content_to_file",
        }
        for option_name in ("-O", "-o")
    ),
    {
        "program_name": "pip",
        "subcommand": "install",
        "fetches": "yes",
        "target_arguments": "all",
        "target_kind": "package_name",
        "target_notation": "pip_requirement",
        "target_without_target_arguments": "no_target",
        "content_route": "own_file",
    },
    {
        "program_name": "pip",
        "option_name": "-r",
        "option_effect": "names_targets_in_file",
    },
    {
        "program_name": "apt-get",
        "subcommand": "update",
        "fetches": "yes",
        "target_arguments": "none",
        "target_kind": "package_name",
        "target_notation": "name",
        "target_without_target_arguments": "no_target",
        "content_route": "own_file",
    },
    {
        "program_name": "npx",
        "fetches": "only_what_is_missing",
        "target_arguments": "next_program",
        "target_kind": "package_name",
        "target_notation": "name",
        "target_without_target_arguments": "no_request",
    },
    {"program_name": "echo", "fetches": "no"},
    {"program_name": "cat", "fetches": "no"},
]
# Made-up rows of `code_calls.csv`, each with the cells that differ from `_CODE_CALL_DEFAULTS`. mylib.fetch has no row.
CODE_CALL_ROWS: list[dict[str, str]] = [
    {
        "call_name": "requests.get",
        "effect": "sends_network_request",
        "target_notation": "url",
        "target_kind": "url",
    },
    {"call_name": "print", "effect": "sends_no_network_request"},
]

_PROGRAM_BEHAVIOR_DEFAULTS = {
    "subcommand": "",
    "argument_role": "other",
    "first_argument_role": "same",
    "last_argument_role": "same",
    "stdin_role": "none",
    "visibility_of_piped_input": "",
    "gives_arguments_at_run_time": "no",
    "skips_assignment_words": "no",
    "options_end_at_first_argument": "no",
    "takes_one_letter_options_joined": "yes",
    "takes_non_option_dash_words_as_arguments": "",
    "runs_text_in_calling_shell": "no",
    "exits_with_exit_code_of_next_program": "no",
    "name_may_end_with_version": "no",
    "default_run_file": "none",
}
_PROGRAM_OPTION_BEHAVIOR_DEFAULTS = {
    "subcommand": "",
    "takes_value": "no",
    "value_role": "none",
    "argument_role_with_option": "unchanged",
    "first_argument_role_with_option": "unchanged",
    "last_argument_role_with_option": "unchanged",
    "changed_option_name": "none",
    "changed_option_value_role": "none",
    "gives_arguments_at_run_time": "no",
    "exits_with_exit_code_of_next_program_with_option": "unchanged",
    "next_program_end_words": "none",
}
_PROGRAM_NETWORK_REQUEST_DEFAULTS = {
    "subcommand": "",
    "option_name": "",
    "option_value": "",
    "fetches": "",
    "target_arguments": "",
    "target_kind": "",
    "target_notation": "",
    "target_without_target_arguments": "",
    "content_route": "",
    "option_effect": "",
}
_CODE_CALL_DEFAULTS = {
    "code_language": "python",
    "target_notation": "",
    "target_kind": "",
    "module_name": "",
}
# The cells that every made-up row shares.
_REVIEW_DEFAULTS = {"checked_against": "made up", "reviewed": "", "note": ""}


@pytest.fixture(scope="module")
def catalogs_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Write the made-up catalogs of `ExpandedToolCallKnowledge` and `NetworkRequestKnowledge` into one new folder, whose file names differ between the two."""
    catalogs_dir = tmp_path_factory.mktemp("catalogs")
    for file_name, key_columns, defaults, rows in (
        (
            PROGRAM_BEHAVIORS_CSV,
            ["program_name"],
            _PROGRAM_BEHAVIOR_DEFAULTS,
            PROGRAM_BEHAVIOR_ROWS,
        ),
        (
            PROGRAM_OPTION_BEHAVIORS_CSV,
            ["program_name", "option_name"],
            _PROGRAM_OPTION_BEHAVIOR_DEFAULTS,
            PROGRAM_OPTION_BEHAVIOR_ROWS,
        ),
        (
            CODE_RUNNERS_CSV,
            ["runner_kind", "runner", "ran_text_language"],
            {},
            CODE_RUNNER_ROWS,
        ),
        (
            PROGRAM_NETWORK_REQUESTS_CSV,
            ["program_name"],
            _PROGRAM_NETWORK_REQUEST_DEFAULTS,
            PROGRAM_NETWORK_REQUEST_ROWS,
        ),
        (CODE_CALLS_CSV, ["call_name", "effect"], _CODE_CALL_DEFAULTS, CODE_CALL_ROWS),
    ):
        _write_rows(catalogs_dir / file_name, [*key_columns, *defaults], defaults, rows)
    return catalogs_dir


def _write_rows(
    csv_path: Path,
    columns: list[str],
    defaults: Mapping[str, str],
    rows: Sequence[Mapping[str, str]],
) -> None:
    with csv_path.open("w", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, [*columns, *_REVIEW_DEFAULTS])
        writer.writeheader()
        writer.writerows({**defaults, **_REVIEW_DEFAULTS, **row} for row in rows)


def _key(step_id: int) -> ToolCallKey:
    return ToolCallKey("t1", "main", step_id, 0)


K1, K2, K3, K4, K5, K6 = (_key(step_id) for step_id in range(1, 7))


def _command(text: str, *, first_command_id: int = 0) -> RunCommandAction:
    return RunCommandAction(
        text,
        parse_shell_text(
            text, judgment_rule_use_counts=Counter(), first_command_id=first_command_id
        ),
    )


def _call(
    step_id: int,
    action: ToolCallAction | str,
    result: ToolCallResult | None = FINISHED,
) -> ToolCall:
    """Make a call at a step of the main trajectory, taking a string as the command of a `RunCommandAction`."""
    return ToolCall(
        HarnessToolCall(_key(step_id), TOOL, "", {}, None),
        _command(action) if isinstance(action, str) else action,
        result,
    )


@dataclass(frozen=True, slots=True)
class _Extraction:
    """Output of `extract_network_requests` on made-up calls, with the counts it added."""

    network_requests: tuple[NetworkRequest, ...]
    judgment_rule_use_counts: Counter[str]
    no_network_request_counts: Counter[NoNetworkRequestReason]


def _extract(
    catalogs_dir: Path,
    *tool_calls: ToolCall,
    judgment_rule_use_counts: Counter[str] | None = None,
    no_network_request_counts: Counter[NoNetworkRequestReason] | None = None,
) -> _Extraction:
    """Expand the calls with `expand_tool_calls` and extract their requests, both with new knowledge classes on the made-up catalogs."""
    judgment_rule_use_counts = (
        Counter() if judgment_rule_use_counts is None else judgment_rule_use_counts
    )
    no_network_request_counts = (
        Counter() if no_network_request_counts is None else no_network_request_counts
    )
    expanded_tool_calls = expand_tool_calls(
        tool_calls,
        knowledge=ExpandedToolCallKnowledge(catalogs_dir=catalogs_dir),
        judgment_rule_use_counts=Counter(),
    )
    network_requests = extract_network_requests(
        expanded_tool_calls,
        knowledge=NetworkRequestKnowledge(catalogs_dir=catalogs_dir),
        judgment_rule_use_counts=judgment_rule_use_counts,
        no_network_request_counts=no_network_request_counts,
    )
    return _Extraction(
        network_requests, judgment_rule_use_counts, no_network_request_counts
    )


def _requests(
    catalogs_dir: Path, *actions: ToolCallAction | str
) -> tuple[NetworkRequest, ...]:
    """Extract the requests of one call per action, at steps 1, 2 and so on."""
    return _extract(
        catalogs_dir,
        *(_call(step_id, action) for step_id, action in enumerate(actions, start=1)),
    ).network_requests


def _curl(url: str, *options: tuple[str, str | None]) -> ProgramInvocation:
    """Give the reading of `curl` with the options and the URL as its one argument."""
    return ProgramInvocation(
        "curl",
        (),
        tuple(ProgramOption(name, value) for name, value in options),
        (url,),
        False,
        (),
        UnknownExitsWithExitCodeOfNextProgram(),
    )


# The made-up trial of `docs/pipeline-example.md`, with the result texts shortened.
C1_TEXT = "curl -sS --connect-timeout 30 -O https://a.example.org/x.tgz; curl -sS --connect-timeout 30 -O https://b.example.org/y.tgz; echo done"
FETCH_SH_CONTENT = "curl -sS -O https://data.example.org/a.tgz"
C3_TEXT = "bash fetch.sh > fetch.log 2>&1 || pip install requests"


def _example_trial() -> tuple[ToolCall, ...]:
    return (
        _call(1, C1_TEXT),
        _call(2, WriteFileAction("fetch.sh", FETCH_SH_CONTENT)),
        _call(
            3,
            C3_TEXT,
            ToolCallResult(
                tool_output_text="",
                execution_status=ExecutionStatus.RUNNING,
                handles=(TASK_1,),
            ),
        ),
        _call(
            4,
            PollAction((TASK_1,)),
            ToolCallResult(
                tool_output_text="Successfully installed requests-2.32.3",
                execution_status=ExecutionStatus.FINISHED,
                exit_code=0,
                handles=(TASK_1,),
            ),
        ),
        _call(
            5,
            ReadFileAction("fetch.log"),
            ToolCallResult(
                tool_output_text="curl: (6) Could not resolve host",
                execution_status=ExecutionStatus.FINISHED,
            ),
        ),
        _call(6, "bash setup.sh"),
    )


def test_the_example_trial_gives_one_request_per_downloaded_url_and_package_and_counts_the_rest(
    catalogs_dir,
):
    c1_curl_options = (
        ("-s", None),
        ("-S", None),
        ("--connect-timeout", "30"),
        ("-O", None),
    )

    extraction = _extract(catalogs_dir, *_example_trial())

    assert extraction.network_requests == (
        NetworkRequest(
            tool_call_key=K1,
            index_in_tool_call=0,
            source=FromCommand(
                0,
                CallCommandText(),
                _curl("https://a.example.org/x.tgz", *c1_curl_options),
            ),
            target="https://a.example.org/x.tgz",
            target_kind=URL,
            host_names=("a.example.org",),
            received_content_destination=ContentSaved("x.tgz"),
            certainty=CONFIRMED,
            uncertainty_reason=None,
        ),
        NetworkRequest(
            tool_call_key=K1,
            index_in_tool_call=1,
            source=FromCommand(
                1,
                CallCommandText(),
                _curl("https://b.example.org/y.tgz", *c1_curl_options),
            ),
            target="https://b.example.org/y.tgz",
            target_kind=URL,
            host_names=("b.example.org",),
            received_content_destination=ContentSaved("y.tgz"),
            certainty=CONFIRMED,
            uncertainty_reason=None,
        ),
        # pip install of c3's own text has id 1, so it comes before the curl of fetch.sh, which gets the next id 2 of the call.
        NetworkRequest(
            tool_call_key=K3,
            index_in_tool_call=0,
            source=FromCommand(
                1,
                CallCommandText(),
                ProgramInvocation(
                    "pip", ("install",), (), ("requests",), False, (), False
                ),
            ),
            target="requests",
            target_kind=PACKAGE_NAME,
            host_names=(),
            received_content_destination=ContentSaved(None),
            certainty=CONFIRMED,
            uncertainty_reason=None,
        ),
        NetworkRequest(
            tool_call_key=K3,
            index_in_tool_call=1,
            source=FromCommand(
                2,
                FileText(0, "fetch.sh", K2),
                _curl(
                    "https://data.example.org/a.tgz",
                    ("-s", None),
                    ("-S", None),
                    ("-O", None),
                ),
            ),
            target="https://data.example.org/a.tgz",
            target_kind=URL,
            host_names=("data.example.org",),
            received_content_destination=ContentSaved("a.tgz"),
            certainty=CONFIRMED,
            uncertainty_reason=None,
        ),
    )
    # echo of c1 does not fetch, bash of c3 runs fetch.sh, whose curl gives the request, and bash of c6 runs a setup.sh that the trial does not hold, with no URL in its words.
    assert extraction.no_network_request_counts == Counter(
        {
            NoNetworkRequestReason.NON_FETCHING_PROGRAM: 1,
            NoNetworkRequestReason.PROGRAM_RUNS_SOMETHING_ELSE: 1,
            NoNetworkRequestReason.NO_URL_THAT_MAY_BE_PUBLIC: 1,
        }
    )
    assert extraction.judgment_rule_use_counts == Counter()


@pytest.mark.parametrize(
    ("command_text", "expected_targets"),
    [
        pytest.param(
            "pip install A B C",
            [("A", PACKAGE_NAME), ("B", PACKAGE_NAME), ("C", PACKAGE_NAME)],
            id="one per package",
        ),
        pytest.param(
            "pip install requests git+https://github.com/a/b",
            [
                ("requests", PACKAGE_NAME),
                ("git+https://github.com/a/b", REPOSITORY_URL),
            ],
            id="a package and a repository",
        ),
        pytest.param("apt-get update", [(None, PACKAGE_NAME)], id="no target written"),
        pytest.param(
            "pip install -r reqs.txt",
            [(NAMED_IN_FILE, PACKAGE_NAME)],
            id="targets in a file",
        ),
        # A word with an expansion starts the unread words by a rule, so the loop gives one request whose target is unread.
        pytest.param(
            "for p in A B C; do pip install $p; done",
            [(UNREAD_WORDS, PACKAGE_NAME)],
            id="loop values shown",
        ),
    ],
)
def test_a_command_gives_one_request_per_target_it_shows_and_one_when_it_shows_none(
    catalogs_dir, command_text, expected_targets
):
    network_requests = _requests(catalogs_dir, command_text)

    assert [
        (network_request.target, network_request.target_kind)
        for network_request in network_requests
    ] == expected_targets


@pytest.mark.parametrize(
    ("command_text", "expected_targets"),
    [
        pytest.param(
            "for p in A B C; do pip install $p; done",
            [("A", PACKAGE_NAME), ("B", PACKAGE_NAME), ("C", PACKAGE_NAME)],
            id="loop values shown",
        ),
        pytest.param(
            "for p in $(cat list.txt); do pip install $p; done",
            [(VALUE_SET_AT_RUN_TIME, PACKAGE_NAME)],
            id="loop values not shown",
        ),
    ],
)
def test_a_loop_gives_one_request_per_value_when_a_word_with_an_expansion_is_one_word(
    catalogs_dir, monkeypatch, command_text, expected_targets
):
    monkeypatch.setattr(
        _expand_program_invocations,
        treat_word_with_expansion_as_start_of_unread_words.__name__,
        lambda word, *, use_counts: False,
    )
    network_requests = _requests(catalogs_dir, command_text)

    assert [
        (network_request.target, network_request.target_kind)
        for network_request in network_requests
    ] == expected_targets
    assert [
        network_request.index_in_tool_call for network_request in network_requests
    ] == list(range(len(expected_targets)))


def test_the_same_command_in_three_calls_gives_one_request_in_each(catalogs_dir):
    curl_text = "curl https://a.org/x"

    network_requests = _requests(catalogs_dir, curl_text, curl_text, curl_text)

    assert [
        (network_request.tool_call_key, network_request.index_in_tool_call)
        for network_request in network_requests
    ] == [(K1, 0), (K2, 0), (K3, 0)]


def _python_code(code: str) -> str:
    """Give a command that runs Python code given as its argument."""
    return f"python -c '{code}'"


# One case for each answer about a means, i.e. fetches, unknown or does not fetch, with a visible URL and without one, for a command and for code, and one web tool case that fetches. Then two uncertain commands. The requests are (source type, certainty, reason).
@pytest.mark.parametrize(
    ("action", "expected_requests"),
    [
        pytest.param(
            "curl https://a.org/x",
            [(FromCommand, CONFIRMED, None)],
            id="fetches, URL, command",
        ),
        pytest.param(
            _python_code('import requests; requests.get("https://a.org/x")'),
            [(FromCode, CONFIRMED, None)],
            id="fetches, URL, code",
        ),
        pytest.param(
            WebSearchAction(("a query",)),
            [(FromWebTool, CONFIRMED, None)],
            id="fetches, web tool",
        ),
        pytest.param(
            "apt-get update",
            [(FromCommand, CONFIRMED, None)],
            id="fetches, no URL, command",
        ),
        pytest.param(
            _python_code("requests.get(base + path)"),
            [(FromCode, CONFIRMED, None)],
            id="fetches, no URL, code",
        ),
        pytest.param(
            "mytool https://a.org/x",
            [(FromCommand, UNCERTAIN, Reason.UNKNOWN_PROGRAM)],
            id="unknown, URL, command",
        ),
        pytest.param(
            _python_code('mylib.fetch("https://a.org/x")'),
            [(FromCode, UNCERTAIN, Reason.UNKNOWN_CODE_CALL)],
            id="unknown, URL, code",
        ),
        pytest.param("mytool sync", [], id="unknown, no URL, command"),
        pytest.param(_python_code("x = compute()"), [], id="unknown, no URL, code"),
        pytest.param("echo https://a.org", [], id="does not fetch, URL, command"),
        pytest.param(
            _python_code('print("https://a.org")'), [], id="does not fetch, URL, code"
        ),
        pytest.param("cat a.txt", [], id="does not fetch, no URL, command"),
        pytest.param(
            _python_code('print("hi")'), [], id="does not fetch, no URL, code"
        ),
        pytest.param(
            "npx tsc --noEmit",
            [(FromCommand, UNCERTAIN, Reason.FETCHES_ONLY_WHAT_IS_MISSING)],
            id="fetches only what is missing",
        ),
        pytest.param(
            "curl -L https://a.org/x",
            [(FromCommand, UNCERTAIN, Reason.UNKNOWN_OPTION_EFFECT)],
            id="option without a row",
        ),
    ],
)
def test_what_is_known_of_the_means_decides_whether_it_gives_a_request_and_how_sure(
    catalogs_dir, action, expected_requests
):
    network_requests = _requests(catalogs_dir, action)

    assert [
        (
            type(network_request.source),
            network_request.certainty,
            network_request.uncertainty_reason,
        )
        for network_request in network_requests
    ] == expected_requests


def test_a_trial_without_calls_gives_no_request_and_counts_nothing(catalogs_dir):
    extraction = _extract(catalogs_dir)

    assert extraction == _Extraction((), Counter(), Counter())


def test_a_call_that_did_not_run_gives_the_requests_its_text_shows(catalogs_dir):
    not_run = ToolCallResult(
        tool_output_text="denied", execution_status=ExecutionStatus.NOT_RUN
    )

    network_requests = _extract(
        catalogs_dir,
        _call(1, "pip install x; curl -o a.tgz https://a.org/x", not_run),
    ).network_requests

    assert [
        (
            network_request.target,
            network_request.received_content_destination,
            network_request.certainty,
        )
        for network_request in network_requests
    ] == [
        ("x", ContentSaved(None), CONFIRMED),
        ("https://a.org/x", ContentSaved("a.tgz"), CONFIRMED),
    ]


def test_a_call_gives_its_commands_by_id_then_its_code_then_its_web_steps_numbered_in_the_call(
    catalogs_dir,
):
    # The script runs fetch.sh in step 0, whose curl gets id 3 after the three commands of the steps, and runs code and pip in step 2.
    script = RunToolScriptAction(
        "...",
        (
            _command("bash fetch.sh"),
            WebFetchAction(("https://w.org/doc",)),
            _command(
                _python_code('import requests; requests.get("https://c.org/x")')
                + "; pip install x",
                first_command_id=1,
            ),
        ),
    )

    network_requests = _extract(
        catalogs_dir,
        _call(1, WriteFileAction("fetch.sh", "curl https://a.org/x")),
        _call(2, script),
    ).network_requests

    assert [
        (
            network_request.tool_call_key,
            network_request.index_in_tool_call,
            _place_in_call_of(network_request),
            network_request.target,
        )
        for network_request in network_requests
    ] == [
        (K2, 0, ("command", 2, ScriptStepText(2)), "x"),
        (K2, 1, ("command", 3, FileText(0, "fetch.sh", K1)), "https://a.org/x"),
        (K2, 2, ("code", 1, ArgumentText(1)), "https://c.org/x"),
        (K2, 3, ("web tool step", 1, None), "https://w.org/doc"),
    ]


def _place_in_call_of(
    network_request: NetworkRequest,
) -> tuple[str, int | None, object]:
    """Give where in its call a request comes from, as the means, the command id or step index and the source of its text."""
    match network_request.source:
        case FromCommand(command_id=command_id, ran_text_source=ran_text_source):
            return ("command", command_id, ran_text_source)
        case FromCode(
            runner_command_id=runner_command_id, code_text_source=code_text_source
        ):
            return ("code", runner_command_id, code_text_source)
        case FromWebTool(step_index=step_index):
            return ("web tool step", step_index, None)


def test_every_use_of_a_judgment_rule_and_every_run_without_request_adds_to_the_counts_it_is_given(
    catalogs_dir,
):
    judgment_rule_use_counts = Counter({"rule of an earlier trial": 1})
    no_network_request_counts = Counter(
        {NoNetworkRequestReason.NON_FETCHING_PROGRAM: 1}
    )

    _extract(
        catalogs_dir,
        _call(1, "mytool http://db:5432; echo hi"),
        _call(2, WebFindAction(("https://a.org/guide",))),
        # python runs the code text, which reads `x.print` as the call `print`, known not to fetch.
        _call(3, _python_code('x.print("hi")')),
        judgment_rule_use_counts=judgment_rule_use_counts,
        no_network_request_counts=no_network_request_counts,
    )

    assert judgment_rule_use_counts == Counter(
        {
            "rule of an earlier trial": 1,
            treat_single_label_or_templated_host_name_as_possibly_public.__name__: 1,
            treat_web_find_as_request.__name__: 1,
            treat_call_name_that_ends_with_catalog_name_as_that_call.__name__: 1,
        }
    )
    assert no_network_request_counts == Counter(
        {
            NoNetworkRequestReason.NON_FETCHING_PROGRAM: 2,
            NoNetworkRequestReason.PROGRAM_RUNS_SOMETHING_ELSE: 1,
            NoNetworkRequestReason.NON_FETCHING_CODE_CALL: 1,
        }
    )


# Commands whose fetching program has an option before its subcommand, or is a git subcommand that may run hooks of the repository, as (text, targets) of the requests that the real catalogs give.
_REAL_CATALOG_CASES = [
    ("apt-get -y install curl", ["curl"]),
    ("pip -q install x", ["x"]),
    ("python -m pip -q install x", ["x"]),
    (
        "npm --prefix /app install",
        [UnknownNetworkRequestTarget(UnknownNetworkRequestTargetReason.NAMED_IN_FILE)],
    ),
    # Without a repository word git fetch asks the remote that the configuration of the repository names.
    (
        "git -C /app fetch",
        [UnknownNetworkRequestTarget(UnknownNetworkRequestTargetReason.NAMED_IN_FILE)],
    ),
    ("git pull https://github.com/a/b", ["https://github.com/a/b"]),
    # An option without a row of pip stops the reading before the subcommand, so no request is made from words that were not read.
    ("pip --foo install x", []),
]


@pytest.mark.parametrize(("text", "targets"), _REAL_CATALOG_CASES)
def test_commands_give_their_requests_on_the_real_catalogs(text, targets):
    """Run on the real catalog folders, so that a missing program, subcommand or option row there fails here."""
    expanded_tool_calls = expand_tool_calls(
        (_call(1, text),),
        knowledge=ExpandedToolCallKnowledge(),
        judgment_rule_use_counts=Counter(),
    )
    network_requests = extract_network_requests(
        expanded_tool_calls,
        knowledge=NetworkRequestKnowledge(),
        judgment_rule_use_counts=Counter(),
        no_network_request_counts=Counter(),
    )

    assert [
        (network_request.target, network_request.certainty)
        for network_request in network_requests
    ] == [(target, NetworkRequestCertainty.CONFIRMED) for target in targets]


CONFIRMED = NetworkRequestCertainty.CONFIRMED
UNCERTAIN = NetworkRequestCertainty.UNCERTAIN
HOST = NetworkRequestTargetKind.HOST
PACKAGE_NAME = NetworkRequestTargetKind.PACKAGE_NAME
URL_KIND = NetworkRequestTargetKind.URL
NAMED_IN_FILE = UnknownNetworkRequestTarget(
    UnknownNetworkRequestTargetReason.NAMED_IN_FILE
)
# Commands of rows that a review of the catalogs checked against their pages, as (text, requests as (target, target kind, hosts, certainty), unknown inputs as (catalog, key)) on the real catalogs. A case may also use a row that the review left as `not checked, from the old table`, e.g. the row of host in `program_network_requests.csv`.
_REVIEWED_REAL_CATALOG_CASES = [
    # dig has no row, since its first argument can be the server or a query option, e.g. @1.1.1.1 or +short, so no word of it is taken for the name and a host without a URL gives no request.
    ("dig a.org", [], {(PROGRAM_BEHAVIORS_CSV, ("dig", ""))}),
    ("dig +short a.org", [], {(PROGRAM_BEHAVIORS_CSV, ("dig", ""))}),
    ("dig @1.1.1.1 a.org", [], {(PROGRAM_BEHAVIORS_CSV, ("dig", ""))}),
    ("dig -x 8.8.8.8", [], {(PROGRAM_BEHAVIORS_CSV, ("dig", ""))}),
    # The query type is the value of -t, and the server comes after the name.
    ("host -t A a.org", [("a.org", HOST, ("a.org",), CONFIRMED)], set()),
    ("host a.org 8.8.8.8", [("a.org", HOST, ("a.org",), CONFIRMED)], set()),
    ("nslookup a.org 8.8.8.8", [("a.org", HOST, ("a.org",), CONFIRMED)], set()),
    # The arguments of the install of browsers are browser names and no targets.
    ("playwright install chromium", [(None, URL_KIND, (), CONFIRMED)], set()),
    # --with-deps also installs system packages, a request to other hosts that no option effect can state, so the option has no row and the request is uncertain.
    (
        "playwright install --with-deps chromium",
        [(None, URL_KIND, (), UNCERTAIN)],
        {(PROGRAM_NETWORK_REQUESTS_CSV, ("playwright", "install", "--with-deps", ""))},
    ),
    ("agent-browser install", [(None, URL_KIND, (), CONFIRMED)], set()),
    ("dnf install -y curl", [("curl", PACKAGE_NAME, (), CONFIRMED)], set()),
    ("bun add -d x", [("x", PACKAGE_NAME, (), CONFIRMED)], set()),
    ("sbt -batch compile", [(NAMED_IN_FILE, PACKAGE_NAME, (), UNCERTAIN)], set()),
    # git submodule update fetches only the commits that are not there yet, from the addresses that .gitmodules names.
    (
        "git submodule update",
        [(NAMED_IN_FILE, REPOSITORY_URL, (), UNCERTAIN)],
        set(),
    ),
    # The wrappers have no row of their own in the request catalog, and the request is that of curl.
    (
        "strace -f -o t.txt -e trace=network curl https://a.org",
        [("https://a.org", URL_KIND, ("a.org",), CONFIRMED)],
        {(PROGRAM_NETWORK_REQUESTS_CSV, ("strace", "", "", ""))},
    ),
    (
        "unshare -n curl https://a.org",
        [("https://a.org", URL_KIND, ("a.org",), CONFIRMED)],
        {(PROGRAM_NETWORK_REQUESTS_CSV, ("unshare", "", "", ""))},
    ),
    # git log fetches missing objects in a partial clone, which no row can state, so it stays an unknown input.
    ("git log", [], {(PROGRAM_NETWORK_REQUESTS_CSV, ("git", "log", "", ""))}),
    # pip list sends a request only with --outdated or --uptodate, which no option effect can state for a program that does not fetch otherwise.
    (
        "pip list --outdated",
        [],
        {
            (PROGRAM_OPTION_BEHAVIORS_CSV, ("pip", "list", "--outdated")),
            (PROGRAM_NETWORK_REQUESTS_CSV, ("pip", "list", "", "")),
        },
    ),
]


@pytest.mark.parametrize(
    ("text", "requests", "unknown_inputs"), _REVIEWED_REAL_CATALOG_CASES
)
def test_reviewed_rows_give_their_requests_and_unknown_inputs_on_the_real_catalogs(
    text, requests, unknown_inputs
):
    expanded_tool_call_knowledge = ExpandedToolCallKnowledge()
    network_request_knowledge = NetworkRequestKnowledge()
    expanded_tool_calls = expand_tool_calls(
        (_call(1, text),),
        knowledge=expanded_tool_call_knowledge,
        judgment_rule_use_counts=Counter(),
    )
    network_requests = extract_network_requests(
        expanded_tool_calls,
        knowledge=network_request_knowledge,
        judgment_rule_use_counts=Counter(),
        no_network_request_counts=Counter(),
    )

    assert [
        (
            network_request.target,
            network_request.target_kind,
            network_request.host_names,
            network_request.certainty,
        )
        for network_request in network_requests
    ] == requests
    assert (
        set(expanded_tool_call_knowledge.uses.unknown_input_counts)
        | set(network_request_knowledge.uses.unknown_input_counts)
    ) == unknown_inputs
