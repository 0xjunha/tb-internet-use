"""Tests for _decide_network_request_results.py, with made-up mini-swe-agent, Claude Code and Copilot CLI calls run through `convert_tool_calls`, `expand_tool_calls` and `extract_network_requests` on the knowledge classes made from the catalogs of the repo.

The cases use programs and options whose rows the catalogs hold, e.g. `pip install` and `wget` without options, so that the results rest on the rows and not on a missing one.
"""

import json
from collections import Counter
from dataclasses import dataclass

import pytest
from made_up_harness_tool_calls import build_copilot_cli_bash_call_not_executed

from tb_internet_use.expanded_tool_call.model import ExpandedToolCall, FileUseKind
from tb_internet_use.knowledge.network_request_result_knowledge import (
    NetworkRequestResultKnowledge,
)
from tb_internet_use.network_request import extract_network_requests
from tb_internet_use.network_request.model import (
    ContentSaved,
    NetworkRequest,
    NetworkRequestCertainty,
    NetworkRequestUncertaintyReason,
)
from tb_internet_use.network_request_result import (
    _decide_network_request_results as decide_network_request_results_module,
)
from tb_internet_use.network_request_result import decide_network_request_results
from tb_internet_use.network_request_result.judgment_rules import (
    treat_request_of_last_known_content_as_reaching_no_output_place,
)
from tb_internet_use.network_request_result.model import (
    ExecutionStatusEvidence,
    ExitCodeEvidence,
    FileUseEvidence,
    JudgmentRuleAssumptionReason,
    NetworkRequestResult,
    NetworkRequestResultCertainty,
    NetworkRequestResultLevel,
    NetworkRequestResultStopReason,
    OutputLineEvidence,
    OutputLineKind,
    SharedOutputLineAssumptionReason,
    ShownContentEvidence,
    UnusedOutputLineReason,
)
from tb_internet_use.pipeline import PipelineKnowledge, run_steps_to_expanded_tool_calls
from tb_internet_use.tool_call.model import (
    ExecutionStatus,
    HarnessTool,
    HarnessToolCall,
    ToolCallKey,
)

_ATTEMPTED = NetworkRequestResultLevel.ATTEMPTED
_EXECUTED = NetworkRequestResultLevel.EXECUTED
_REACHED = NetworkRequestResultLevel.REACHED
_RECEIVED = NetworkRequestResultLevel.RECEIVED
_FAILED = NetworkRequestResultStopReason.FAILED
_NOT_VISIBLE = NetworkRequestResultStopReason.NOT_VISIBLE
_NOT_NEEDED = NetworkRequestResultStopReason.NOT_NEEDED
_CONFIRMED = NetworkRequestResultCertainty.CONFIRMED
_ASSUMED = NetworkRequestResultCertainty.ASSUMED


def _key(step_id: int, trajectory_id: str = "main") -> ToolCallKey:
    return ToolCallKey("t1", trajectory_id, step_id, 0)


def _bash_call(
    step_id: int,
    command: str,
    output: str,
    *,
    returncode: int = 0,
    trajectory_id: str = "main",
) -> HarnessToolCall:
    """Make a mini-swe-agent `bash` call whose result gives its exit code and output."""
    return HarnessToolCall(
        _key(step_id, trajectory_id),
        HarnessTool("mini-swe-agent", "bash"),
        f"{trajectory_id}-{step_id}",
        {"command": command},
        {"content": json.dumps({"returncode": returncode, "output": output})},
    )


def _claude_code_call(
    step_id: int, tool_name: str, args: dict[str, str], content: str
) -> HarnessToolCall:
    return HarnessToolCall(
        _key(step_id),
        HarnessTool("claude-code", tool_name),
        str(step_id),
        args,
        {"content": content},
    )


@dataclass(frozen=True, slots=True)
class _Steps:
    """Output of the earlier steps on made-up calls, which `decide_network_request_results` reads."""

    expanded_tool_calls: tuple[ExpandedToolCall, ...]
    network_requests: tuple[NetworkRequest, ...]


def _steps(*harness_tool_calls: HarnessToolCall) -> _Steps:
    pipeline_knowledge = PipelineKnowledge()
    expanded_tool_calls = run_steps_to_expanded_tool_calls(
        harness_tool_calls,
        pipeline_knowledge=pipeline_knowledge,
        tool_call_judgment_rule_use_counts=Counter(),
        expanded_tool_call_judgment_rule_use_counts=Counter(),
    )
    network_requests = extract_network_requests(
        expanded_tool_calls,
        knowledge=pipeline_knowledge.network_request_knowledge,
        judgment_rule_use_counts=Counter(),
        no_network_request_counts=Counter(),
    )
    return _Steps(expanded_tool_calls, network_requests)


@dataclass(slots=True)
class _Decided:
    """Results of `decide_network_request_results` with the counters it filled."""

    results: tuple[NetworkRequestResult, ...]
    judgment_rule_use_counts: Counter[str]
    unused_output_line_counts: Counter[tuple[UnusedOutputLineReason, OutputLineKind]]
    program_counts_of_unowned_output_lines: Counter[
        tuple[UnusedOutputLineReason, OutputLineKind, str]
    ]


def _decided(
    steps: _Steps, network_requests: tuple[NetworkRequest, ...] | None = None
) -> _Decided:
    """Decide the results of the requests of the steps, or of `network_requests` when given, on a new `NetworkRequestResultKnowledge`."""
    decided = _Decided((), Counter(), Counter(), Counter())
    decided.results = decide_network_request_results(
        steps.expanded_tool_calls,
        steps.network_requests if network_requests is None else network_requests,
        knowledge=NetworkRequestResultKnowledge(),
        judgment_rule_use_counts=decided.judgment_rule_use_counts,
        unused_output_line_counts=decided.unused_output_line_counts,
        program_counts_of_unowned_output_lines=decided.program_counts_of_unowned_output_lines,
    )
    return decided


def _line(
    step_id: int, kind: OutputLineKind, *, line_index: int = 0, is_shared: bool = False
) -> OutputLineEvidence:
    return OutputLineEvidence(_key(step_id), line_index, None, kind, is_shared)


def _exit_zero(step_id: int, *, is_shared: bool = False) -> ExitCodeEvidence:
    return ExitCodeEvidence(_key(step_id), 0, is_shared)


# Made-up inputs, each with the whole result of every request, without the request itself, which the test takes from `extract_network_requests`.
# Each gives the calls and, per request in order, the request certainty after the evidence, level, stop reason, level certainty, evidence and, for an assumed result, the assumption reasons, and then the rule uses of the trial.
WHOLE_RESULT_CASES = [
    pytest.param(
        (
            _bash_call(
                1,
                "getent hosts a.org; curl -s -o /dev/null -w '%{http_code}' https://b.org/x; curl -s -i -X POST https://c.org/y",
                "200\nHTTP/1.1 405 Method Not Allowed",
            ),
        ),
        [
            (
                NetworkRequestCertainty.CONFIRMED,
                _ATTEMPTED,
                _NOT_VISIBLE,
                _CONFIRMED,
                (),
                (),
            ),
            (
                NetworkRequestCertainty.CONFIRMED,
                _REACHED,
                _NOT_VISIBLE,
                _CONFIRMED,
                (
                    _line(1, OutputLineKind.BARE_STATUS_CODE),
                    _line(1, OutputLineKind.HTTP_STATUS, line_index=1, is_shared=True),
                ),
                (),
            ),
            (
                NetworkRequestCertainty.CONFIRMED,
                _REACHED,
                _FAILED,
                _ASSUMED,
                (
                    _line(1, OutputLineKind.HTTP_STATUS, line_index=1, is_shared=True),
                    _exit_zero(1, is_shared=True),
                ),
                # The shared 405 decides the stop reason, not the exit code that a rule reads.
                (SharedOutputLineAssumptionReason(_key(1), 1, None),),
            ),
        ],
        Counter(
            {
                "treat_command_without_own_evidence_as_no_evidence_of_run": 2,
                "treat_exit_code_meaning_as_assumed_level": 1,
            }
        ),
        id="getent prints no status line and the own 200 of curl -w decides beside a shared 405",
    ),
    pytest.param(
        (_bash_call(1, "wget https://a.org/x.tgz", "'x.tgz' saved [1024/1024]"),),
        [
            (
                NetworkRequestCertainty.CONFIRMED,
                _RECEIVED,
                None,
                _CONFIRMED,
                (_line(1, OutputLineKind.DOWNLOADED), _exit_zero(1)),
                (),
            )
        ],
        Counter({"treat_exit_code_meaning_as_assumed_level": 1}),
        id="wget saved line is received",
    ),
    pytest.param(
        (
            _bash_call(
                1,
                "curl https://a.org/x; curl https://b.org/y",
                "curl: (6) Could not resolve host: a.org",
                returncode=6,
            ),
        ),
        [
            (
                NetworkRequestCertainty.CONFIRMED,
                _EXECUTED,
                _FAILED,
                _CONFIRMED,
                (_line(1, OutputLineKind.NAME_NOT_RESOLVED),),
                (),
            ),
            (
                NetworkRequestCertainty.CONFIRMED,
                _ATTEMPTED,
                _NOT_VISIBLE,
                _CONFIRMED,
                (),
                (),
            ),
        ],
        Counter({"treat_command_without_own_evidence_as_no_evidence_of_run": 2}),
        id="a line that names a host belongs to the request of that host alone",
    ),
    pytest.param(
        (
            _bash_call(1, "pip install x > log 2>&1", "", returncode=1),
            _bash_call(2, "cat log", "ERROR: No matching distribution found for x"),
        ),
        [
            (
                NetworkRequestCertainty.CONFIRMED,
                _EXECUTED,
                _FAILED,
                _CONFIRMED,
                (_line(2, OutputLineKind.NOT_FOUND),),
                (),
            )
        ],
        Counter({"treat_command_without_own_evidence_as_no_evidence_of_run": 1}),
        id="a line in a later read of the log is evidence of the command that wrote it",
    ),
    pytest.param(
        (_bash_call(1, "pip install A", "Downloading B-1.0.whl"),),
        [
            (
                NetworkRequestCertainty.CONFIRMED,
                _EXECUTED,
                _NOT_VISIBLE,
                _CONFIRMED,
                (_line(1, OutputLineKind.DOWNLOAD_STARTED), _exit_zero(1)),
                (),
            )
        ],
        Counter({"treat_line_naming_another_target_as_no_evidence_of_answer": 1}),
        id="a line naming another package shows only the run",
    ),
    pytest.param(
        (
            _bash_call(
                1,
                "pip install x",
                "ConnectionResetError: [Errno 104] Connection reset by peer\nDownloading x-1.0-py3-none-any.whl (10 kB)\nSuccessfully installed x-1.0",
            ),
        ),
        [
            (
                NetworkRequestCertainty.CONFIRMED,
                _RECEIVED,
                None,
                _ASSUMED,
                (
                    _line(1, OutputLineKind.CONNECTION_LOST),
                    _line(1, OutputLineKind.DOWNLOAD_STARTED, line_index=1),
                    _line(1, OutputLineKind.INSTALLED, line_index=2),
                    _exit_zero(1),
                ),
                (JudgmentRuleAssumptionReason(),),
            )
        ],
        Counter(
            {
                "treat_lost_connection_as_after_server_answer": 1,
                "treat_higher_evidence_beside_failure_as_assumed_level": 1,
            }
        ),
        id="a failure line beside a later download is assumed",
    ),
    pytest.param(
        (
            _bash_call(
                1,
                "curl https://a.org/x; pip install y",
                "",
                returncode=0,
            ),
            build_copilot_cli_bash_call_not_executed(
                _key(2), "curl https://c.org/z; pip install w"
            ),
        ),
        [
            (
                NetworkRequestCertainty.CONFIRMED,
                _ATTEMPTED,
                _NOT_VISIBLE,
                _CONFIRMED,
                (),
                (),
            ),
            (
                NetworkRequestCertainty.CONFIRMED,
                _EXECUTED,
                _NOT_VISIBLE,
                _CONFIRMED,
                # The code is about both requests of the call, which does not make the result assumed.
                (_exit_zero(1, is_shared=True),),
                (),
            ),
            (
                NetworkRequestCertainty.CONFIRMED,
                _ATTEMPTED,
                _FAILED,
                _CONFIRMED,
                (ExecutionStatusEvidence(_key(2), ExecutionStatus.NOT_RUN, True),),
                (),
            ),
            (
                NetworkRequestCertainty.CONFIRMED,
                _ATTEMPTED,
                _FAILED,
                _CONFIRMED,
                (ExecutionStatusEvidence(_key(2), ExecutionStatus.NOT_RUN, True),),
                (),
            ),
        ],
        Counter({"treat_command_without_own_evidence_as_no_evidence_of_run": 1}),
        id="exit 0 of a ; b shows the last command, and a call not run fails all its requests",
    ),
    # mini-swe-agent writes that the action was not executed also for the action that submitted, which ran, so its request gets no evidence instead of a failure.
    pytest.param(
        (
            HarnessToolCall(
                _key(1),
                HarnessTool("mini-swe-agent", "bash"),
                "1",
                {
                    "command": "curl -s -o z https://c.org/z && echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
                },
                {
                    "content": json.dumps(
                        {
                            "output": "",
                            "returncode": -1,
                            "exception_info": "action was not executed",
                        }
                    )
                },
            ),
        ),
        [
            (
                NetworkRequestCertainty.CONFIRMED,
                _ATTEMPTED,
                _NOT_VISIBLE,
                _CONFIRMED,
                (),
                (),
            ),
        ],
        Counter({"treat_command_without_own_evidence_as_no_evidence_of_run": 1}),
        id="a request of the action that submitted, whose result says it was not executed, is not visible",
    ),
    pytest.param(
        (
            _claude_code_call(
                1,
                "WebFetch",
                {"url": "https://a.org/x", "prompt": "summary"},
                "Please verify you are not a robot",
            ),
            _claude_code_call(
                2,
                "WebFetch",
                {"url": "https://b.org/y", "prompt": "summary"},
                "Some page text",
            ),
        ),
        [
            (
                NetworkRequestCertainty.CONFIRMED,
                _REACHED,
                _NOT_VISIBLE,
                _CONFIRMED,
                (
                    _line(1, OutputLineKind.SERVER_ANSWERED),
                    ExecutionStatusEvidence(_key(1), ExecutionStatus.FINISHED, False),
                ),
                (),
            ),
            (
                NetworkRequestCertainty.CONFIRMED,
                _RECEIVED,
                None,
                _ASSUMED,
                (
                    ExecutionStatusEvidence(_key(2), ExecutionStatus.FINISHED, False),
                    ShownContentEvidence(_key(2)),
                ),
                (JudgmentRuleAssumptionReason(),),
            ),
        ],
        Counter({"treat_shown_result_text_as_assumed_content": 1}),
        id="a web fetch result is read with the web tool result patterns",
    ),
    pytest.param(
        (
            _bash_call(
                1,
                "apt-get install -y a b",
                "Fetched 10 kB in 1s (10 kB/s)",
            ),
        ),
        [
            (
                NetworkRequestCertainty.CONFIRMED,
                _RECEIVED,
                None,
                _ASSUMED,
                (
                    _line(1, OutputLineKind.DOWNLOADED, is_shared=True),
                    _exit_zero(1, is_shared=True),
                ),
                (SharedOutputLineAssumptionReason(_key(1), 0, None),),
            ),
        ]
        * 2,
        Counter(),
        id="one downloaded line that both requests of `apt-get install -y a b` own names the same line as the reason of both",
    ),
    pytest.param(
        (
            _bash_call(
                1,
                "apt-get install -y a b",
                'start\n{"output": "Reading package lists...\\nFetched 10 kB in 1s (10 kB/s)"}',
            ),
        ),
        [
            (
                NetworkRequestCertainty.CONFIRMED,
                _RECEIVED,
                None,
                _ASSUMED,
                (
                    OutputLineEvidence(_key(1), 1, 1, OutputLineKind.DOWNLOADED, True),
                    _exit_zero(1, is_shared=True),
                ),
                (SharedOutputLineAssumptionReason(_key(1), 1, 1),),
            ),
        ]
        * 2,
        Counter(),
        id="a shared line inside the output string of a JSON object is named with its index in that string",
    ),
    pytest.param(
        (
            _bash_call(1, "apt-get install -y a b > log 2>&1", ""),
            _bash_call(2, "cat log", "Fetched 10 kB in 1s (10 kB/s)"),
        ),
        [
            (
                NetworkRequestCertainty.CONFIRMED,
                _RECEIVED,
                None,
                _ASSUMED,
                (
                    _line(2, OutputLineKind.DOWNLOADED, is_shared=True),
                    _exit_zero(1, is_shared=True),
                ),
                (SharedOutputLineAssumptionReason(_key(2), 0, None),),
            ),
        ]
        * 2,
        Counter(),
        id="a shared line that a later read of the log shows is named by the call that shows it",
    ),
    pytest.param(
        (
            _bash_call(
                1,
                "apt-get update && apt-get install -y curl",
                "Get:1 http://deb.debian.org/debian bookworm/main amd64 curl amd64 7.88.1-10 [10 kB]\nSetting up curl (7.88.1-10) ...",
            ),
        ),
        [
            (
                NetworkRequestCertainty.CONFIRMED,
                _RECEIVED,
                None,
                _ASSUMED,
                (
                    _line(1, OutputLineKind.DOWNLOAD_STARTED, is_shared=True),
                    _line(1, OutputLineKind.INSTALLED, line_index=1, is_shared=True),
                    _exit_zero(1, is_shared=True),
                ),
                (
                    SharedOutputLineAssumptionReason(_key(1), 0, None),
                    SharedOutputLineAssumptionReason(_key(1), 1, None),
                ),
            ),
        ]
        * 2,
        Counter(
            {
                "treat_apt_download_and_install_lines_shared_by_requests_of_several_commands_as_received": 2
            }
        ),
        id="apt download and install lines that the update and the install own leave each request assumed",
    ),
    pytest.param(
        (
            _bash_call(
                1,
                "pip download typing-extensions -d dl 2>&1 | tail -2",
                "Saved ./dl/typing_extensions-4.12.2-py3-none-any.whl\nSuccessfully downloaded typing-extensions",
            ),
        ),
        [
            (
                NetworkRequestCertainty.CONFIRMED,
                _RECEIVED,
                None,
                _CONFIRMED,
                (
                    _line(1, OutputLineKind.PACKAGE_FILE_ADDED_TO_FOLDER),
                    _line(1, OutputLineKind.PACKAGE_FILE_IN_FOLDER, line_index=1),
                ),
                (),
            ),
        ],
        Counter(
            {
                "treat_pip_saved_line_of_named_package_as_received": 1,
                "treat_command_without_own_evidence_as_no_evidence_of_run": 1,
            }
        ),
        id="the pip line of a file of the target new to the folder is received beside a cut output",
    ),
    pytest.param(
        (
            _bash_call(
                1,
                "pip download requests -d dl 2>&1 | tail -2",
                "Saved ./dl/idna-3.7-py3-none-any.whl\nSuccessfully downloaded idna requests",
            ),
        ),
        [
            (
                NetworkRequestCertainty.CONFIRMED,
                _EXECUTED,
                _NOT_VISIBLE,
                _CONFIRMED,
                (
                    _line(1, OutputLineKind.PACKAGE_FILE_ADDED_TO_FOLDER),
                    _line(1, OutputLineKind.PACKAGE_FILE_IN_FOLDER, line_index=1),
                ),
                (),
            ),
        ],
        Counter(
            {
                "treat_line_naming_another_target_as_no_evidence_of_answer": 1,
                "treat_command_without_own_evidence_as_no_evidence_of_run": 1,
            }
        ),
        id="the pip line of a file of a dependency new to the folder shows only the run",
    ),
]


@pytest.mark.parametrize(
    ("harness_tool_calls", "expected_results", "expected_rule_uses"),
    WHOLE_RESULT_CASES,
)
def test_decides_whole_results_of_made_up_inputs(
    harness_tool_calls, expected_results, expected_rule_uses
):
    steps = _steps(*harness_tool_calls)

    decided = _decided(steps)

    assert decided.results == tuple(
        NetworkRequestResult(network_request, *expected_result)
        for network_request, expected_result in zip(
            steps.network_requests, expected_results, strict=True
        )
    )
    assert decided.judgment_rule_use_counts == expected_rule_uses


# One case for each of the eight rows of the table of results in the criteria and one for a request that asks for no content, each with the input of such a request and the level, stop reason and level certainty it gets.
RESULT_TABLE_CASES = [
    pytest.param(
        _bash_call(1, "wget https://a.org/x.tgz", "'x.tgz' saved [1024/1024]"),
        (_RECEIVED, None, _CONFIRMED),
        id="content received",
    ),
    pytest.param(
        _bash_call(1, "curl -i https://a.org/x", "HTTP/1.1 404 Not Found"),
        (_REACHED, _FAILED, _CONFIRMED),
        id="server refused",
    ),
    pytest.param(
        _bash_call(
            1,
            "curl https://a.org/x",
            "curl: (6) Could not resolve host: a.org",
            returncode=6,
        ),
        (_EXECUTED, _FAILED, _CONFIRMED),
        id="server not reached",
    ),
    pytest.param(
        _bash_call(
            1, "pip3 install requests", "bash: pip3: command not found", returncode=127
        ),
        (_ATTEMPTED, _FAILED, _CONFIRMED),
        id="not run",
    ),
    pytest.param(
        _bash_call(
            1,
            "apt-get update",
            "Hit:1 http://archive.ubuntu.com/ubuntu jammy InRelease",
        ),
        (_REACHED, _NOT_VISIBLE, _CONFIRMED),
        id="server answered and the content does not show",
    ),
    pytest.param(
        _bash_call(1, "pip install A", ""),
        (_EXECUTED, _NOT_VISIBLE, _CONFIRMED),
        id="ran and its output does not show",
    ),
    pytest.param(
        _bash_call(1, "test -f x || curl https://a.org/x -o x", ""),
        (_ATTEMPTED, _NOT_VISIBLE, _CONFIRMED),
        id="not known whether it ran",
    ),
    pytest.param(
        _bash_call(
            1,
            "pip install requests",
            "Requirement already satisfied: requests in /usr/lib",
        ),
        (_EXECUTED, _NOT_NEEDED, _CONFIRMED),
        id="nothing had to be sent",
    ),
    pytest.param(
        _bash_call(1, "curl -I https://a.org", "HTTP/1.1 200 OK"),
        (_REACHED, None, _CONFIRMED),
        id="a request for no content succeeds at reached",
    ),
]


@pytest.mark.parametrize(("harness_tool_call", "expected"), RESULT_TABLE_CASES)
def test_each_row_of_the_result_table_comes_out_of_its_case(
    harness_tool_call, expected
):
    decided = _decided(_steps(harness_tool_call))

    assert [
        (result.level, result.stop_reason, result.level_certainty)
        for result in decided.results
    ] == [expected]


# Made-up runs of programs that fetch only what is missing, each with an output line that shows a download and the level and stop reason that the line gives.
DOWNLOAD_LINE_OF_PROGRAM_THAT_FETCHES_ONLY_WHAT_IS_MISSING_CASES = [
    pytest.param(
        "npx tsc --version",
        "npm warn exec The following package was not found and will be installed: tsc@2.0.4",
        id="npx prints that it installs a missing package",
    ),
    pytest.param(
        "sbt compile",
        "[info] downloading https://repo1.maven.org/maven2/a/b/1.0/b-1.0.jar ...",
        id="sbt prints that Ivy downloads a file",
    ),
]


def test_line_that_shows_only_the_run_of_a_program_that_fetches_only_what_is_missing_leaves_its_request_uncertain():
    # lake prints that it clones a dependency before the clone connects.
    steps = _steps(
        _bash_call(
            1,
            "lake build",
            "info: mathlib: cloning https://github.com/leanprover-community/mathlib4",
        )
    )

    (result,) = _decided(steps).results

    assert (
        result.network_request.certainty,
        result.request_certainty_after_evidence,
        result.level,
        result.stop_reason,
        result.evidence[0],
    ) == (
        NetworkRequestCertainty.UNCERTAIN,
        NetworkRequestCertainty.UNCERTAIN,
        _EXECUTED,
        _NOT_VISIBLE,
        _line(1, OutputLineKind.PROGRAM_RAN),
    )


@pytest.mark.parametrize(
    ("command", "output"),
    DOWNLOAD_LINE_OF_PROGRAM_THAT_FETCHES_ONLY_WHAT_IS_MISSING_CASES,
)
def test_download_line_of_a_program_that_fetches_only_what_is_missing_confirms_its_request(
    command, output
):
    steps = _steps(_bash_call(1, command, output))
    steps_without_line = _steps(_bash_call(1, command, ""))

    (result,) = _decided(steps).results
    (result_without_line,) = _decided(steps_without_line).results

    assert result.network_request.certainty == NetworkRequestCertainty.UNCERTAIN
    assert (
        result.request_certainty_after_evidence,
        result.level,
        result.stop_reason,
    ) == (NetworkRequestCertainty.CONFIRMED, _REACHED, _NOT_VISIBLE)
    assert (
        result_without_line.request_certainty_after_evidence
        == NetworkRequestCertainty.UNCERTAIN
    )


# Made-up inputs where a request saves a file and a command uses it, each with where the request saved its content, its level, stop reason and level certainty, the kinds of its file use evidence and the rule uses of the trial.
# The kinds of use come from the rows of `program_behaviors.csv` and `program_option_behaviors.csv`, e.g. those of tar and gunzip.
SAVED_FILE_USE_CASES = [
    pytest.param(
        (_bash_call(1, "curl -sL -o a.tgz https://a.org/a.tgz && tar xzf a.tgz", ""),),
        (ContentSaved("a.tgz"), _RECEIVED, None, _CONFIRMED),
        (FileUseKind.USES_CONTENT,),
        Counter({"treat_exit_code_meaning_as_assumed_level": 1}),
        id="tar xzf after && with exit 0 surely used the content",
    ),
    pytest.param(
        (_bash_call(1, "curl -o a.tgz https://a.org/a.tgz; tar xzf a.tgz", ""),),
        (ContentSaved("a.tgz"), _RECEIVED, None, _CONFIRMED),
        (FileUseKind.USES_CONTENT,),
        Counter({"treat_command_without_own_evidence_as_no_evidence_of_run": 1}),
        id="tar xzf as the last command of a ; b owns the exit 0",
    ),
    pytest.param(
        (_bash_call(1, "curl -o a.tgz https://a.org/a.tgz; tar xzf a.tgz; ls", ""),),
        (ContentSaved("a.tgz"), _RECEIVED, None, _ASSUMED),
        (FileUseKind.USES_CONTENT,),
        Counter(
            {
                "treat_command_without_own_evidence_as_no_evidence_of_run": 1,
                "treat_file_use_that_may_not_have_happened_as_assumed_evidence": 1,
            }
        ),
        id="tar xzf before ; ls may not have run",
    ),
    pytest.param(
        (
            _bash_call(1, "curl -sL -o /tmp/a.tgz https://a.org/a.tgz", ""),
            _bash_call(2, "tar xzf /tmp/a.tgz -C /opt", ""),
        ),
        (ContentSaved("/tmp/a.tgz"), _RECEIVED, None, _CONFIRMED),
        (FileUseKind.USES_CONTENT,),
        Counter({"treat_exit_code_meaning_as_assumed_level": 1}),
        id="a later tar with the cluster xzf and -C after the archive",
    ),
    pytest.param(
        (
            _bash_call(1, "curl -sL -o /tmp/a.tgz https://a.org/a.tgz", ""),
            _bash_call(2, "tar -C /opt -xzf /tmp/a.tgz", ""),
        ),
        (ContentSaved("/tmp/a.tgz"), _RECEIVED, None, _CONFIRMED),
        (FileUseKind.USES_CONTENT,),
        Counter({"treat_exit_code_meaning_as_assumed_level": 1}),
        id="a later tar with -C before -xzf after one dash",
    ),
    pytest.param(
        (
            _bash_call(1, "curl -sL -o a.tgz https://a.org/a.tgz", ""),
            _bash_call(2, "tar tzf a.tgz", "a/\na/b"),
        ),
        (ContentSaved("a.tgz"), _RECEIVED, None, _ASSUMED),
        (FileUseKind.SHOWS_CONTENT,),
        Counter(
            {
                "treat_exit_code_meaning_as_assumed_level": 1,
                "treat_shown_content_of_saved_file_as_assumed_content": 1,
            }
        ),
        id="tar tzf lists the content of the archive",
    ),
    pytest.param(
        (
            _bash_call(1, "curl -sL -o a.gz https://a.org/a.gz", ""),
            _bash_call(2, "gunzip -k a.gz", ""),
        ),
        (ContentSaved("a.gz"), _RECEIVED, None, _CONFIRMED),
        (FileUseKind.USES_CONTENT,),
        Counter({"treat_exit_code_meaning_as_assumed_level": 1}),
        id="gunzip -k uses the file and keeps it",
    ),
    pytest.param(
        (
            _bash_call(1, "curl -O https://a.org/x.tgz", ""),
            _bash_call(2, "tar xzf x.tgz", ""),
        ),
        (ContentSaved("x.tgz"), _RECEIVED, None, _CONFIRMED),
        (FileUseKind.USES_CONTENT,),
        Counter({"treat_exit_code_meaning_as_assumed_level": 1}),
        id="curl -O saves under the last part of the URL path",
    ),
    pytest.param(
        (
            _bash_call(1, "wget https://a.org/x.tgz", ""),
            _bash_call(2, "tar xzf x.tgz", ""),
        ),
        (ContentSaved(None), _RECEIVED, None, _ASSUMED),
        (),
        Counter({"treat_exit_code_meaning_as_assumed_level": 1}),
        id="wget without -O names no file, so the later tar is not linked",
    ),
    pytest.param(
        (
            _bash_call(1, "curl -o page.html https://a.org/p", ""),
            _bash_call(2, "cat page.html", "<html>"),
        ),
        (ContentSaved("page.html"), _RECEIVED, None, _ASSUMED),
        (FileUseKind.SHOWS_CONTENT,),
        Counter(
            {
                "treat_exit_code_meaning_as_assumed_level": 1,
                "treat_shown_content_of_saved_file_as_assumed_content": 1,
            }
        ),
        id="cat of a saved page is assumed content",
    ),
    pytest.param(
        (
            _bash_call(1, "curl -o f https://a.org/f", ""),
            _bash_call(2, "ls -la f", "-rw-r--r-- 1 root root 10 f"),
        ),
        (ContentSaved("f"), _REACHED, _NOT_VISIBLE, _ASSUMED),
        (),
        Counter(
            {
                "treat_exit_code_meaning_as_assumed_level": 1,
                "treat_size_or_type_of_saved_file_as_no_evidence_of_content": 1,
            }
        ),
        id="ls -la shows only the size, which the rule takes as no evidence",
    ),
    pytest.param(
        (_bash_call(1, "curl -o f.sh https://a.org/f.sh && bash f.sh", ""),),
        (ContentSaved("f.sh"), _RECEIVED, None, _CONFIRMED),
        (FileUseKind.USES_CONTENT,),
        Counter({"treat_exit_code_meaning_as_assumed_level": 1}),
        id="bash runs the saved script after && with exit 0",
    ),
]


@pytest.mark.parametrize(
    (
        "harness_tool_calls",
        "expected_result",
        "expected_file_use_kinds",
        "expected_rule_uses",
    ),
    SAVED_FILE_USE_CASES,
)
def test_a_later_use_of_a_saved_file_gives_the_evidence_of_its_kind(
    harness_tool_calls, expected_result, expected_file_use_kinds, expected_rule_uses
):
    decided = _decided(_steps(*harness_tool_calls))

    (result,) = decided.results
    assert (
        result.network_request.received_content_destination,
        result.level,
        result.stop_reason,
        result.level_certainty,
    ) == expected_result
    assert (
        tuple(
            evidence.file_use.kind
            for evidence in result.evidence
            if isinstance(evidence, FileUseEvidence)
        )
        == expected_file_use_kinds
    )
    assert decided.judgment_rule_use_counts == expected_rule_uses


def test_a_trial_without_requests_still_reads_every_result_and_counts_its_lines():
    steps = _steps(
        _bash_call(
            1, "./setup.sh", "Downloading torch-2.3.0.whl\nDownloading numpy-1.26.whl"
        ),
        _bash_call(2, "ls -la", "HTTP/1.1 200 OK"),
        _bash_call(3, "rg foo", "bash: rg: command not found", returncode=127),
        _bash_call(4, "cat README.md", "Downloading torch-2.3.0"),
        # A plan tool's result is no output place, and its line is counted as such.
        _claude_code_call(5, "TaskList", {}, "HTTP/1.1 503 Service Unavailable"),
    )

    decided = _decided(steps)

    assert steps.network_requests == ()
    assert decided.results == ()
    assert decided.unused_output_line_counts == Counter(
        {
            (
                UnusedOutputLineReason.UNOWNED_LINE_IN_UNKNOWN_RUN,
                OutputLineKind.DOWNLOAD_STARTED,
            ): 2,
            (UnusedOutputLineReason.NO_UNKNOWN_RUN, OutputLineKind.HTTP_STATUS): 1,
            (
                UnusedOutputLineReason.MISSING_PROGRAM_OF_COMMAND_WITHOUT_REQUEST,
                OutputLineKind.PROGRAM_MISSING,
            ): 1,
            (UnusedOutputLineReason.FILE_CONTENT, OutputLineKind.DOWNLOAD_STARTED): 1,
            (
                UnusedOutputLineReason.NOT_AN_OUTPUT_PLACE,
                OutputLineKind.HTTP_STATUS,
            ): 1,
        }
    )
    assert decided.program_counts_of_unowned_output_lines == Counter(
        {
            (
                UnusedOutputLineReason.UNOWNED_LINE_IN_UNKNOWN_RUN,
                OutputLineKind.DOWNLOAD_STARTED,
                "setup.sh",
            ): 2,
            (
                UnusedOutputLineReason.NO_UNKNOWN_RUN,
                OutputLineKind.HTTP_STATUS,
                "ls",
            ): 1,
        }
    )
    assert decided.judgment_rule_use_counts == Counter()


def test_results_follow_the_order_of_the_requests_given():
    steps = _steps(
        _bash_call(1, "pip install A", "Successfully installed A-1.0"),
        _bash_call(2, "pip install B", ""),
    )
    reversed_network_requests = steps.network_requests[::-1]

    decided = _decided(steps, reversed_network_requests)

    assert [result.network_request for result in decided.results] == list(
        reversed_network_requests
    )
    assert [result.level for result in decided.results] == [_EXECUTED, _RECEIVED]


def test_adds_to_the_counters_it_is_given_without_clearing_them():
    steps = _steps(
        _bash_call(1, "pip install A", "Successfully installed A-1.0"),
        _bash_call(2, "./setup.sh", "Downloading torch-2.3.0.whl"),
    )
    judgment_rule_use_counts = Counter(
        {"treat_pip_or_apt_installed_line_of_named_package_as_received": 5}
    )
    unused_output_line_reason_and_kind: tuple[
        UnusedOutputLineReason, OutputLineKind
    ] = (
        UnusedOutputLineReason.UNOWNED_LINE_IN_UNKNOWN_RUN,
        OutputLineKind.DOWNLOAD_STARTED,
    )
    unused_output_line_counts: Counter[
        tuple[UnusedOutputLineReason, OutputLineKind]
    ] = Counter({unused_output_line_reason_and_kind: 5})
    program_counts_of_unowned_output_lines: Counter[
        tuple[UnusedOutputLineReason, OutputLineKind, str]
    ] = Counter({(*unused_output_line_reason_and_kind, "setup.sh"): 5})

    decide_network_request_results(
        steps.expanded_tool_calls,
        steps.network_requests,
        knowledge=NetworkRequestResultKnowledge(),
        judgment_rule_use_counts=judgment_rule_use_counts,
        unused_output_line_counts=unused_output_line_counts,
        program_counts_of_unowned_output_lines=program_counts_of_unowned_output_lines,
    )

    assert judgment_rule_use_counts == Counter(
        {"treat_pip_or_apt_installed_line_of_named_package_as_received": 6}
    )
    assert unused_output_line_counts == Counter({unused_output_line_reason_and_kind: 6})
    assert program_counts_of_unowned_output_lines == Counter(
        {(*unused_output_line_reason_and_kind, "setup.sh"): 6}
    )


def test_counts_the_uses_of_the_knowledge_class_on_the_knowledge_class_it_is_given():
    steps = _steps(_bash_call(1, "pip install A", "Successfully installed A-1.0"))
    knowledge = NetworkRequestResultKnowledge()

    decide_network_request_results(
        steps.expanded_tool_calls,
        steps.network_requests,
        knowledge=knowledge,
        judgment_rule_use_counts=Counter(),
        unused_output_line_counts=Counter(),
        program_counts_of_unowned_output_lines=Counter(),
    )

    assert (
        knowledge.uses.row_use_counts[
            "output_line_patterns", ("program_output", "pip_successfully_installed")
        ]
        == 1
    )


def test_a_request_of_a_subagent_trajectory_takes_only_the_lines_of_its_own_calls():
    # The two calls have the same step id in two trajectories, so only the trajectory id of their keys tells them apart.
    steps = _steps(
        _bash_call(1, "pip install A", ""),
        _bash_call(
            1, "pip install A", "Successfully installed A-1.0", trajectory_id="sub-1"
        ),
    )

    decided = _decided(steps)

    assert [
        (result.network_request.tool_call_key, result.level, result.evidence)
        for result in decided.results
    ] == [
        (_key(1), _EXECUTED, (_exit_zero(1),)),
        (
            _key(1, "sub-1"),
            _RECEIVED,
            (
                OutputLineEvidence(
                    _key(1, "sub-1"), 0, None, OutputLineKind.INSTALLED, False
                ),
                ExitCodeEvidence(_key(1, "sub-1"), 0, False),
            ),
        ),
    ]


# fetch.py as cat wrote it in call 1, whose content `sed -i s/x/y/ *.py` of call 2 may have changed, run after `pip install x` in call 3, whose line python may have printed too, since no row says which lines python prints.
FETCH_PY_WRITE = (
    "cat > fetch.py <<'EOF'\nimport requests\nrequests.get('https://a.org/x')\nEOF"
)
LAST_KNOWN_CONTENT_RULE_NAME = (
    treat_request_of_last_known_content_as_reaching_no_output_place.__name__
)


def _steps_of_install_beside_code_of_last_known_content() -> _Steps:
    return _steps(
        _bash_call(1, FETCH_PY_WRITE, ""),
        _bash_call(2, "sed -i s/x/y/ *.py", ""),
        _bash_call(
            3, "pip install x && python fetch.py", "Successfully installed x-1.0"
        ),
    )


def test_a_request_of_the_last_known_content_of_a_file_gets_no_line_and_leaves_the_lines_of_the_other_requests_as_they_were():
    steps = _steps_of_install_beside_code_of_last_known_content()

    decided = _decided(steps)

    pip_result, code_result = decided.results
    assert code_result == NetworkRequestResult(
        network_request=steps.network_requests[1],
        request_certainty_after_evidence=NetworkRequestCertainty.UNCERTAIN,
        level=_ATTEMPTED,
        stop_reason=_NOT_VISIBLE,
        level_certainty=_CONFIRMED,
        evidence=(),
        assumption_reasons=(),
    )
    assert code_result.network_request.uncertainty_reason == (
        NetworkRequestUncertaintyReason.FILE_MAY_HOLD_OTHER_CONTENT
    )
    assert (pip_result.level, pip_result.level_certainty) == (_RECEIVED, _CONFIRMED)
    assert decided.judgment_rule_use_counts[LAST_KNOWN_CONTENT_RULE_NAME] == 1


def test_on_the_other_answer_a_request_of_the_last_known_content_of_a_file_shares_the_lines_of_its_command_and_stays_uncertain(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        decide_network_request_results_module,
        LAST_KNOWN_CONTENT_RULE_NAME,
        lambda *, use_counts: False,
    )
    steps = _steps_of_install_beside_code_of_last_known_content()

    decided = _decided(steps)

    pip_result, code_result = decided.results
    assert code_result.request_certainty_after_evidence == (
        NetworkRequestCertainty.UNCERTAIN
    )
    assert _line(3, OutputLineKind.INSTALLED, is_shared=True) in code_result.evidence
    assert (pip_result.level, pip_result.level_certainty) == (_RECEIVED, _ASSUMED)


@pytest.mark.parametrize(
    "curl_text",
    [
        "curl -s --output-dir d -o f https://a.org/f.tgz",
        "curl -s --output-dir d -O https://a.org/f.tgz",
        "curl -s --output=f https://a.org/f.tgz",
    ],
)
def test_the_text_of_a_result_is_no_content_of_a_request_whose_option_sends_it_to_a_file_of_unknown_path(
    curl_text: str,
):
    """`done` of echo is the only text of the result, and curl saved what it received in a file whose path `expand_tool_calls` does not know, e.g. d/f, so only the exit code 0 of its command is its evidence."""
    steps = _steps(_bash_call(1, f"echo done; {curl_text}", "done"))

    (result,) = _decided(steps).results

    assert result.network_request.received_content_destination == ContentSaved(None)
    assert result.evidence == (_exit_zero(1),)
