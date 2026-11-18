"""Tests for _decide_network_request_results.py, with made-up mini-swe-agent and Claude Code calls run through `convert_tool_calls`, `expand_tool_calls` and `extract_network_requests` on the doors made from the catalogs of the repo.

The cases use programs and options whose rows the catalogs hold, e.g. `pip install` and `wget` without options, so that the results rest on the rows and not on a missing one.
"""

import json
from collections import Counter
from dataclasses import dataclass

import pytest

from tb_internet_use.expanded_tool_call.model import ExpandedToolCall, FileUseKind
from tb_internet_use.knowledge.network_request_result_knowledge import (
    NetworkRequestResultKnowledge,
)
from tb_internet_use.network_request import extract_network_requests
from tb_internet_use.network_request.model import (
    ContentSaved,
    NetworkRequest,
    NetworkRequestCertainty,
)
from tb_internet_use.network_request_result import decide_network_request_results
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
from tb_internet_use.pipeline import KnowledgeDoors, run_steps_to_expanded_tool_calls
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
    knowledge_doors = KnowledgeDoors()
    expanded_tool_calls = run_steps_to_expanded_tool_calls(
        harness_tool_calls,
        knowledge_doors=knowledge_doors,
        tool_call_judgment_rule_use_counts=Counter(),
        expanded_tool_call_judgment_rule_use_counts=Counter(),
    )
    network_requests = extract_network_requests(
        expanded_tool_calls,
        knowledge=knowledge_doors.network_request_knowledge,
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
    """Decide the results of the requests of the steps, or of `network_requests` when given, on a new door."""
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
                "Connection reset by peer\nSuccessfully downloaded x",
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
                    _line(1, OutputLineKind.DOWNLOADED, line_index=1),
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
            HarnessToolCall(
                _key(2),
                HarnessTool("mini-swe-agent", "bash"),
                "2",
                {"command": "curl https://c.org/z; pip install w"},
                {"content": json.dumps({"exception_info": "action was not executed"})},
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
                "pip install A B",
                "Successfully downloaded A-1.0 B-2.0",
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
        id="one downloaded line that both requests of `pip install A B` own names the same line as the reason of both",
    ),
    pytest.param(
        (
            _bash_call(
                1,
                "pip install A B",
                'start\n{"output": "Collecting A\\nSuccessfully downloaded A-1.0 B-2.0"}',
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
            _bash_call(1, "pip install A B > log 2>&1", ""),
            _bash_call(2, "cat log", "Successfully downloaded A-1.0 B-2.0"),
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


# One case for each row of the table of results in the criteria, the input of a request that the row describes, with the level, stop reason and level certainty it gets.
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
        _bash_call(1, "pip install A", "Successfully downloaded A-1.0"),
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
        {"treat_installed_line_as_no_evidence_of_download": 5}
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
        {"treat_installed_line_as_no_evidence_of_download": 6}
    )
    assert unused_output_line_counts == Counter({unused_output_line_reason_and_kind: 6})
    assert program_counts_of_unowned_output_lines == Counter(
        {(*unused_output_line_reason_and_kind, "setup.sh"): 6}
    )


def test_counts_the_uses_of_the_door_on_the_door_it_is_given():
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
            1, "pip install A", "Successfully downloaded A-1.0", trajectory_id="sub-1"
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
                    _key(1, "sub-1"), 0, None, OutputLineKind.DOWNLOADED, False
                ),
                ExitCodeEvidence(_key(1, "sub-1"), 0, False),
            ),
        ),
    ]
