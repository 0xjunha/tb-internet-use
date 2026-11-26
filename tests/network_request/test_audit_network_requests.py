"""Tests for scripts/audit_network_requests.py, with a made-up trial run through the steps on the catalogs of the repo, broken copies of its output that each make a named equation differ, and made-up trial folders run through `audit_trial` and `main`.

The equations hold whatever the catalogs say, so the cases use the catalogs of the repo. The counts they assert rest on the made-up names `mytool` and `mylib.fetch` having no row.
"""

import csv
import dataclasses
import importlib.util
import inspect
import json
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any, ClassVar, Self

import pytest

from tb_internet_use.expanded_tool_call.model import (
    ArgumentText,
    CallCommandText,
    CodeLanguage,
    ExpandedToolCall,
    OutputVisibility,
    ProgramInvocation,
    RanCodeText,
    RanCommand,
    RanShellText,
    RanText,
    UnknownProgramInvocation,
)
from tb_internet_use.knowledge.catalog import KnowledgeUses
from tb_internet_use.knowledge.network_request_knowledge import NetworkRequestKnowledge
from tb_internet_use.network_request import extract_network_requests
from tb_internet_use.network_request.model import (
    ContentPipedToCommand,
    ContentSaved,
    FromCode,
    FromCommand,
    FromWebTool,
    NetworkRequest,
    NetworkRequestCertainty,
    NetworkRequestTargetKind,
    NetworkRequestUncertaintyReason,
    NoNetworkRequestReason,
    UnknownCodeCall,
    UnknownReceivedContentDestination,
)
from tb_internet_use.pipeline import PipelineKnowledge, run_steps_to_expanded_tool_calls
from tb_internet_use.tool_call.model import (
    HarnessTool,
    HarnessToolCall,
    ShellCommand,
    ToolCallKey,
)

_SPEC = importlib.util.spec_from_file_location(
    "audit_network_requests",
    Path(__file__).parents[2] / "scripts/audit_network_requests.py",
)
assert _SPEC is not None and _SPEC.loader is not None
audit = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = audit  # registered as an import would do
_SPEC.loader.exec_module(audit)


def _key(step_id: int) -> ToolCallKey:
    return ToolCallKey("t1", "main", step_id, 0)


def _harness_tool_call(
    step_id: int, tool_name: str, args: dict[str, Any], content: str = ""
) -> HarnessToolCall:
    return HarnessToolCall(
        _key(step_id),
        HarnessTool("claude-code", tool_name),
        str(step_id),
        args,
        {"content": content},
    )


# A made-up Claude Code trial with a request of each means. The comments name what the `Bash` calls add.
_MADE_UP_TRIAL = (
    _harness_tool_call(
        1,
        "Write",
        {"file_path": "fetch.sh", "content": "curl https://a.org/x"},
        "File created successfully at: fetch.sh",
    ),
    # bash runs fetch.sh, and mytool has no row and shows a public URL.
    _harness_tool_call(2, "Bash", {"command": "bash fetch.sh; mytool https://b.org/y"}),
    # Code with a call that fetches and a call without a row.
    _harness_tool_call(
        3,
        "Bash",
        {
            "command": """python3 -c 'import requests; requests.get("https://e.org/x"); mylib.fetch("https://f.org")'"""
        },
    ),
    _harness_tool_call(4, "WebSearch", {"query": "a query"}),
    _harness_tool_call(5, "Agent", {"prompt": "read https://g.org/doc"}),
    # Code without a request, whose only URL is local.
    _harness_tool_call(
        6, "Bash", {"command": """python3 -c 'print("http://localhost:8000")'"""}
    ),
)


@dataclasses.dataclass(slots=True)
class _Steps:
    """Output of the steps on made-up calls, which a broken input changes before the check."""

    expanded_tool_calls: tuple[ExpandedToolCall, ...]
    network_requests: tuple[NetworkRequest, ...]
    no_network_request_counts: Counter[NoNetworkRequestReason]
    judgment_rule_use_counts: Counter[str]
    knowledge_uses: KnowledgeUses


def _steps(harness_tool_calls: tuple[HarnessToolCall, ...] = _MADE_UP_TRIAL) -> _Steps:
    pipeline_knowledge = PipelineKnowledge()
    expanded_tool_calls = run_steps_to_expanded_tool_calls(
        harness_tool_calls,
        pipeline_knowledge=pipeline_knowledge,
        tool_call_judgment_rule_use_counts=Counter(),
        expanded_tool_call_judgment_rule_use_counts=Counter(),
    )
    judgment_rule_use_counts: Counter[str] = Counter()
    no_network_request_counts: Counter[NoNetworkRequestReason] = Counter()
    network_requests = extract_network_requests(
        expanded_tool_calls,
        knowledge=pipeline_knowledge.network_request_knowledge,
        judgment_rule_use_counts=judgment_rule_use_counts,
        no_network_request_counts=no_network_request_counts,
    )
    return _Steps(
        expanded_tool_calls,
        network_requests,
        no_network_request_counts,
        judgment_rule_use_counts,
        pipeline_knowledge.network_request_knowledge.uses,
    )


def _checked(steps: _Steps) -> Any:
    """Check the output of the steps as `audit_trial` does and give the trial audit."""
    trial_audit = audit.TrialAudit(
        "t1",
        audit.EXTRACTED,
        harness="claude-code",
        task="4-0-0 terminal-bench/a",
        judgment_rule_use_counts=steps.judgment_rule_use_counts,
        knowledge_uses=steps.knowledge_uses,
    )
    audit.TrialChecker(
        trial_audit,
        steps.expanded_tool_calls,
        steps.network_requests,
        steps.no_network_request_counts,
        NetworkRequestKnowledge(),
        audit.WorkerProcessKnowledge().code_call_names,
    ).check()
    return trial_audit


def _differing_equations(trial_audit: Any) -> set[str]:
    return {
        equation
        for equation, _ in trial_audit.equation_sides
        if trial_audit.equation_sides[equation, "left"]
        != trial_audit.equation_sides[equation, "right"]
    }


def _requests_from(steps: _Steps, source_type: type) -> list[NetworkRequest]:
    return [
        network_request
        for network_request in steps.network_requests
        if isinstance(network_request.source, source_type)
    ]


def test_every_equation_holds_on_a_made_up_trial_with_a_request_of_each_means():
    steps = _steps()

    trial_audit = _checked(steps)

    assert _differing_equations(trial_audit) == set()
    # curl of fetch.sh, mytool, the two code calls and the web search.
    assert trial_audit.counts["all", "requests"] == 5
    assert trial_audit.counts["all", "requests from FromCode"] == 2
    assert trial_audit.counts["all", "trials with a request"] == 1
    assert trial_audit.counts["all", "subagent calls with a public URL"] == 1
    assert trial_audit.uncertain_request_counts == Counter(
        {("unknown_program", "mytool"): 1, ("unknown_code_call", "unknown call"): 1}
    )
    # Every other equation has a value on its left side, so that each holds on something.
    assert {
        equation
        for equation in audit.EQUATIONS
        if trial_audit.equation_sides[equation, "left"] == 0
    } == {
        "no_request_repeats_a_request_of_the_text_it_runs",
        "request_fields_agree",
        "pip_install_requests_equal_targets",
        "code_requests_within_urls_and_calls",
    }


def test_every_equation_holds_when_the_last_known_content_of_a_file_gives_requests():
    """`sed -i s/x/y/ *.sh` may have changed fetch.sh, so `bash fetch.sh` gives the requests of its last known content, a curl and a mytool, as uncertain."""
    steps = _steps(
        (
            _harness_tool_call(
                1,
                "Write",
                {
                    "file_path": "fetch.sh",
                    "content": "curl https://a.org/x\nmytool https://c.org/z\n",
                },
                "File created successfully at: fetch.sh",
            ),
            _harness_tool_call(2, "Bash", {"command": "sed -i s/x/y/ *.sh"}),
            _harness_tool_call(3, "Bash", {"command": "bash fetch.sh"}),
        )
    )

    trial_audit = _checked(steps)

    assert _differing_equations(trial_audit) == set()
    assert [
        network_request.uncertainty_reason for network_request in steps.network_requests
    ] == [NetworkRequestUncertaintyReason.FILE_MAY_HOLD_OTHER_CONTENT] * 2


def test_every_equation_has_its_definition_above_its_name():
    source_lines = inspect.getsource(audit).splitlines()
    equations_start = source_lines.index("EQUATIONS = (")
    equations_without_definition = [
        equation
        for equation in audit.EQUATIONS
        if not source_lines[
            source_lines.index(f'    "{equation}",', equations_start) - 1
        ].startswith("    # ")
    ]

    assert equations_without_definition == []


def _with_requests(steps: _Steps, network_requests: Iterable[NetworkRequest]) -> _Steps:
    return dataclasses.replace(steps, network_requests=tuple(network_requests))


def _with_call(
    steps: _Steps,
    step_id: int,
    ran_texts: tuple[RanText, ...],
    network_requests: Iterable[NetworkRequest],
) -> _Steps:
    """Add a made-up `Bash` call with the texts it ran and its requests to the output of the steps."""
    expanded_tool_call = dataclasses.replace(
        steps.expanded_tool_calls[1],
        tool_call=dataclasses.replace(
            steps.expanded_tool_calls[1].tool_call,
            harness_tool_call=_harness_tool_call(step_id, "Bash", {}),
        ),
        ran_texts=ran_texts,
        written_files=(),
    )
    return dataclasses.replace(
        steps,
        expanded_tool_calls=(*steps.expanded_tool_calls, expanded_tool_call),
        network_requests=(*steps.network_requests, *network_requests),
    )


def _ran_command(*words: str) -> RanCommand:
    """Give command 0 of a call, read as the run of one program whose name is its first word, with no row when that is `mytool`."""
    program_invocation = (
        UnknownProgramInvocation(words[0], words[1:])
        if words[0] == "mytool"
        else ProgramInvocation(words[0], (words[1],), (), words[2:], False, (), False)
    )
    return RanCommand(ShellCommand(0, words), (program_invocation,), (), (), ())


def _package_request(
    step_id: int, ran_command: RanCommand, target: str
) -> NetworkRequest:
    """Give the confirmed request 0 of a call for a package that command 0 names."""
    return NetworkRequest(
        _key(step_id),
        0,
        FromCommand(0, CallCommandText(), ran_command.program_invocations[0]),
        target,
        NetworkRequestTargetKind.PACKAGE_NAME,
        (),
        UnknownReceivedContentDestination(),
        NetworkRequestCertainty.CONFIRMED,
        None,
    )


def _program_lookup_dropped(steps: _Steps) -> _Steps:
    uses = KnowledgeUses()
    uses.row_use_counts.update(steps.knowledge_uses.row_use_counts)
    uses.unknown_input_counts.update(steps.knowledge_uses.unknown_input_counts)
    uses.unknown_input_counts[
        "program_network_requests.csv", ("mytool", "", "", "")
    ] -= 1
    return dataclasses.replace(steps, knowledge_uses=uses)


def _command_request_dropped(steps: _Steps) -> _Steps:
    dropped = _requests_from(steps, FromCommand)[0]
    return _with_requests(steps, (r for r in steps.network_requests if r != dropped))


def _code_requests_dropped(steps: _Steps) -> _Steps:
    return _with_requests(
        steps, (r for r in steps.network_requests if not isinstance(r.source, FromCode))
    )


def _index_skipped(steps: _Steps) -> _Steps:
    return _with_requests(
        steps,
        (
            dataclasses.replace(r, index_in_tool_call=5)
            if isinstance(r.source, FromWebTool)
            else r
            for r in steps.network_requests
        ),
    )


def _request_of_the_code_runner_added(steps: _Steps) -> _Steps:
    code_request = _requests_from(steps, FromCode)[0]
    assert isinstance(code_request.source, FromCode)
    runner_command_id = code_request.source.runner_command_id
    assert runner_command_id is not None
    runner_request = dataclasses.replace(
        code_request,
        index_in_tool_call=2,
        source=FromCommand(
            runner_command_id,
            CallCommandText(),
            ProgramInvocation("python3", (), (), (), False, (), False),
        ),
        certainty=NetworkRequestCertainty.CONFIRMED,
        uncertainty_reason=None,
    )
    return _with_requests(steps, (*steps.network_requests, runner_request))


def _saved_path_of_no_file(steps: _Steps) -> _Steps:
    return _with_requests(
        steps,
        (
            dataclasses.replace(r, received_content_destination=ContentSaved("nowhere"))
            if isinstance(r.source, FromCommand)
            else r
            for r in steps.network_requests
        ),
    )


def _pip_install_without_a_request(steps: _Steps) -> _Steps:
    pip_install = _ran_command("pip", "install", "A", "B")
    return _with_call(
        steps,
        9,
        (RanShellText(CallCommandText(), (pip_install,)),),
        (_package_request(9, pip_install, "A"),),
    )


def _code_requests_repeated(steps: _Steps) -> _Steps:
    code_requests = _requests_from(steps, FromCode)
    repeats = [
        dataclasses.replace(code_requests[0], index_in_tool_call=index)
        for index in range(2, 7)
    ]
    return _with_requests(steps, (*steps.network_requests, *repeats))


def _web_request_dropped(steps: _Steps) -> _Steps:
    return _with_requests(
        steps,
        (r for r in steps.network_requests if not isinstance(r.source, FromWebTool)),
    )


def _rule_of_another_step_counted(steps: _Steps) -> _Steps:
    return dataclasses.replace(
        steps,
        judgment_rule_use_counts=Counter(
            {"treat_first_poll_that_saw_end_as_command_text_status": 1}
        ),
    )


def _option_that_sends_no_request_counted(steps: _Steps) -> _Steps:
    return dataclasses.replace(
        steps,
        no_network_request_counts=steps.no_network_request_counts
        + Counter({NoNetworkRequestReason.OPTION_SENDS_NO_REQUEST: 1}),
    )


def _run_without_target_arguments_counted(steps: _Steps) -> _Steps:
    return dataclasses.replace(
        steps,
        no_network_request_counts=steps.no_network_request_counts
        + Counter({NoNetworkRequestReason.NO_TARGET_ARGUMENTS: 1}),
    )


def _request_of_a_reserved_url(steps: _Steps) -> _Steps:
    mytool = _ran_command("mytool", "http://example.com/x")
    return _with_call(
        steps,
        9,
        (RanShellText(CallCommandText(), (mytool,)),),
        (
            NetworkRequest(
                _key(9),
                0,
                FromCommand(0, CallCommandText(), mytool.program_invocations[0]),
                "http://example.com/x",
                NetworkRequestTargetKind.URL,
                ("example.com",),
                UnknownReceivedContentDestination(),
                NetworkRequestCertainty.UNCERTAIN,
                NetworkRequestUncertaintyReason.UNKNOWN_PROGRAM,
            ),
        ),
    )


def _url_host_missing_from_host_names(steps: _Steps) -> _Steps:
    return _with_requests(
        steps,
        (
            dataclasses.replace(r, host_names=())
            if r.target == "https://a.org/x"
            else r
            for r in steps.network_requests
        ),
    )


def _pipe_reader_of_another_text(steps: _Steps) -> _Steps:
    return _with_requests(
        steps,
        (
            dataclasses.replace(
                r,
                received_content_destination=ContentPipedToCommand(
                    99, OutputVisibility.WHOLE
                ),
            )
            if isinstance(r.source, FromCommand)
            else r
            for r in steps.network_requests
        ),
    )


def _pipe_reader_that_reads_no_stdout_of_the_command(steps: _Steps) -> _Steps:
    """Pipe the content of `mytool https://a.org/x` to command 1 of the same text, `cat f`, which reads no stdout route of it, as in `mytool https://a.org/x; cat f`."""
    mytool = _ran_command("mytool", "https://a.org/x")
    cat = RanCommand(
        ShellCommand(1, ("cat", "f")),
        (ProgramInvocation("cat", (), (), ("f",), False, (), False),),
        (),
        (),
        (),
    )
    return _with_call(
        steps,
        9,
        (RanShellText(CallCommandText(), (mytool, cat)),),
        (
            NetworkRequest(
                _key(9),
                0,
                FromCommand(0, CallCommandText(), mytool.program_invocations[0]),
                "https://a.org/x",
                NetworkRequestTargetKind.URL,
                ("a.org",),
                ContentPipedToCommand(1, OutputVisibility.WHOLE),
                NetworkRequestCertainty.UNCERTAIN,
                NetworkRequestUncertaintyReason.UNKNOWN_PROGRAM,
            ),
        ),
    )


def _pip_install_of_a_local_path_and_a_name_with_one_request(steps: _Steps) -> _Steps:
    pip_install = _ran_command("pip", "install", "./x.whl", "A")
    return _with_call(
        steps,
        9,
        (RanShellText(CallCommandText(), (pip_install,)),),
        (_package_request(9, pip_install, "A"),),
    )


BROKEN_INPUT_CASES: list[tuple[str, Callable[[_Steps], _Steps]]] = [
    ("program_invocations_equal_program_lookups", _program_lookup_dropped),
    (
        "command_request_runs_equal_fetching_and_public_url_runs",
        _command_request_dropped,
    ),
    ("code_texts_without_request_show_no_request", _code_requests_dropped),
    ("indexes_run_from_zero_in_each_call", _index_skipped),
    (
        "no_request_repeats_a_request_of_the_text_it_runs",
        _request_of_the_code_runner_added,
    ),
    ("request_fields_agree", _saved_path_of_no_file),
    ("pip_install_requests_equal_targets", _pip_install_without_a_request),
    ("code_requests_within_urls_and_calls", _code_requests_repeated),
    ("web_tool_requests_equal_web_targets", _web_request_dropped),
    ("judgment_rule_names_are_of_this_step", _rule_of_another_step_counted),
]


def test_every_equation_has_a_broken_input():
    assert [equation for equation, _ in BROKEN_INPUT_CASES] == list(audit.EQUATIONS)


# Further broken inputs, one for each part of an equation that the first input of the equation does not reach.
MORE_BROKEN_INPUT_CASES: list[tuple[str, Callable[[_Steps], _Steps]]] = [
    (
        "command_request_runs_equal_fetching_and_public_url_runs",
        _option_that_sends_no_request_counted,
    ),
    (
        "command_request_runs_equal_fetching_and_public_url_runs",
        _run_without_target_arguments_counted,
    ),
    (
        "command_request_runs_equal_fetching_and_public_url_runs",
        _request_of_a_reserved_url,
    ),
    ("request_fields_agree", _url_host_missing_from_host_names),
    ("request_fields_agree", _pipe_reader_of_another_text),
    ("request_fields_agree", _pipe_reader_that_reads_no_stdout_of_the_command),
    (
        "pip_install_requests_equal_targets",
        _pip_install_of_a_local_path_and_a_name_with_one_request,
    ),
]


@pytest.mark.parametrize(
    ("equation", "broken_input_of"),
    BROKEN_INPUT_CASES + MORE_BROKEN_INPUT_CASES,
    ids=[
        f"{equation} {broken_input_of.__name__}"
        for equation, broken_input_of in BROKEN_INPUT_CASES + MORE_BROKEN_INPUT_CASES
    ],
)
def test_a_broken_input_makes_its_equation_differ(equation, broken_input_of):
    trial_audit = _checked(broken_input_of(_steps()))

    assert equation in _differing_equations(trial_audit)


# (equation, made-up Claude Code calls of a shape that the full Terminal-Bench 3.0/4.0 data of 2026-10-08 showed, with the requests right and the recount once wrong). The comments name the shape.
SHAPES_THAT_HOLD: list[tuple[str, tuple[HarnessToolCall, ...]]] = [
    # A variable of one value fills the host of a URL with localhost.
    (
        "command_request_runs_equal_fetching_and_public_url_runs",
        (
            _harness_tool_call(
                1, "Bash", {"command": "H=localhost; mytool http://$H:8000/x"}
            ),
        ),
    ),
    # A call name of a sending row in a string is no call, as in code that edits code.
    (
        "code_texts_without_request_show_no_request",
        (
            _harness_tool_call(
                1,
                "Bash",
                {"command": """python3 -c 'x = "requests.get(u)"; print(x)'"""},
            ),
        ),
    ),
    # A JavaScript method named like a sending call is a definition, and a comment is no call.
    (
        "code_texts_without_request_show_no_request",
        (
            _harness_tool_call(
                1,
                "Bash",
                {
                    "command": "node -e '// fetch(u)\nconst o = { fetch(u) { return 1 } }; console.log(o)'"
                },
            ),
        ),
    ),
    # The step reads no call after a string that never closes.
    (
        "code_texts_without_request_show_no_request",
        (
            _harness_tool_call(
                1, "Bash", {"command": """python3 -c 'x = \"\"\"a\nrequests.get(u)'"""}
            ),
        ),
    ),
    # The curl of a script pipes into tail of the text that runs the script.
    (
        "request_fields_agree",
        (
            _harness_tool_call(
                1,
                "Write",
                {"file_path": "fetch.sh", "content": "curl https://a.org/x"},
                "File created successfully at: fetch.sh",
            ),
            _harness_tool_call(2, "Bash", {"command": "bash fetch.sh | tail -1"}),
        ),
    ),
    # A pattern in code that starts like a URL gives a request whose host cannot be read.
    (
        "code_requests_within_urls_and_calls",
        (
            _harness_tool_call(
                1,
                "Bash",
                {"command": """python3 -c 'mylib.match(r"http://[^ ]+", s)'"""},
            ),
        ),
    ),
    # An f-string URL with a `{...}` host is a URL of a call without a row.
    (
        "code_requests_within_urls_and_calls",
        (
            _harness_tool_call(
                1,
                "Bash",
                {"command": """python3 -c 'mylib.fetch(f"http://{h}:80/x")'"""},
            ),
        ),
    ),
]


@pytest.mark.parametrize(
    ("equation", "harness_tool_calls"),
    SHAPES_THAT_HOLD,
    ids=[equation for equation, _ in SHAPES_THAT_HOLD],
)
def test_a_shape_of_the_full_data_holds_its_equation(equation, harness_tool_calls):
    trial_audit = _checked(_steps(harness_tool_calls))

    assert equation not in _differing_equations(trial_audit)


def test_requests_of_calls_that_run_a_program_stay_within_the_bound_of_their_code_text():
    code_text = RanCodeText(
        ArgumentText(0), CodeLanguage.PYTHON, "subprocess.run(a)\nos.system(b)"
    )
    code_requests = [
        NetworkRequest(
            _key(9),
            index_in_tool_call,
            FromCode(0, code_text.source, CodeLanguage.PYTHON, UnknownCodeCall()),
            "https://a.org/x",
            NetworkRequestTargetKind.URL,
            ("a.org",),
            UnknownReceivedContentDestination(),
            NetworkRequestCertainty.UNCERTAIN,
            NetworkRequestUncertaintyReason.UNKNOWN_CODE_CALL,
        )
        for index_in_tool_call in range(3)
    ]

    within_bound = _checked(_with_call(_steps(), 9, (code_text,), code_requests[:2]))
    over_bound = _checked(_with_call(_steps(), 9, (code_text,), code_requests))

    # The bound is the two calls that run a program, since the text holds no URL.
    for trial_audit, left in ((within_bound, 0), (over_bound, 1)):
        assert (
            trial_audit.equation_sides["code_requests_within_urls_and_calls", "left"]
            == left
        )


@pytest.mark.parametrize(
    ("argument", "is_local_path"),
    [
        (".", True),
        ("./dist/x.whl", True),
        (".[dev]", True),
        ("~/pkg", True),
        ("/opt/pkg", True),
        ("x-1.0-py3-none-any.whl", True),
        ("x-1.0.tar.gz", True),
        ("src/pkg", True),
        ("file:///tmp/x.whl", True),
        ("git+file:///repo", True),
        ("requests", False),
        ("zope.interface", False),
        ("git+https://github.com/a/b", False),
        ("x@https://a.org/x.zip", False),
    ],
)
def test_a_pip_argument_is_a_local_path_by_the_list_of_the_evidence(
    argument, is_local_path
):
    assert audit._is_local_path(argument) is is_local_path


def _csv_rows(path: Path) -> list[list[str]]:
    with path.open(newline="") as csv_file:
        return list(csv.reader(csv_file))


def test_writes_each_differing_call_with_its_trial_and_exits_1_only_then(tmp_path):
    differing = audit.TrialAudit("t1", audit.EXTRACTED)
    differing.add_sides("request_fields_agree", 1, 0, _key(3), "curl")
    holding = audit.TrialAudit("t2", audit.EXTRACTED)
    holding.add_sides("request_fields_agree", 0, 0, _key(3))
    total_of_holding = audit.TrialAuditTotal()
    total_of_holding.add_trial(holding)
    total = audit.TrialAuditTotal()
    total.add_trial(differing)
    total.add_trial(holding)

    audit.write_audit_files(total, tmp_path)

    assert _csv_rows(tmp_path / "equation_examples.csv") == [
        ["equation", "trial_id", "tool_call_key", "name"],
        ["request_fields_agree", "t1", "main:3:0", "curl"],
    ]
    assert not total_of_holding.has_exception_or_differing_equation()
    assert total.has_exception_or_differing_equation()


def test_writes_uncertain_requests_by_means_with_places_trials_and_tasks_most_first(
    tmp_path,
):
    total = audit.TrialAuditTotal()
    for trial_id, task, places in (
        ("t1", "task a", {"main:1:0:0", "main:2:0:0"}),
        ("t2", "task a", {"main:1:0:0"}),
    ):
        trial_audit = audit.TrialAudit(trial_id, audit.EXTRACTED, task=task)
        trial_audit.uncertain_request_counts["unread_words", "curl"] = len(places)
        trial_audit.uncertain_places["unread_words", "curl"] = places
        trial_audit.uncertain_request_counts["unknown_program", "mytool"] = 1
        trial_audit.uncertain_places["unknown_program", "mytool"] = {"main:1:0:1"}
        total.add_trial(trial_audit)

    audit.write_audit_files(total, tmp_path)

    assert _csv_rows(tmp_path / "uncertain_requests_by_means.csv")[1:] == [
        ["unknown_program", "mytool", "2", "2", "2", "1", ""],
        ["unread_words", "curl", "3", "3", "2", "1", ""],
    ]
    assert _csv_rows(tmp_path / "uncertain_requests_by_trial.csv")[1:] == [
        ["t1", "unknown_program", "1"],
        ["t1", "unread_words", "2"],
        ["t2", "unknown_program", "1"],
        ["t2", "unread_words", "1"],
    ]


def test_writes_the_uses_of_rules_and_rows_the_unknown_inputs_and_the_host_scopes_over_trials_most_first(
    tmp_path,
):
    curl_row = ("program_network_requests.csv", ("curl", "", "", ""))
    mytool = ("program_network_requests.csv", ("mytool", "", "", ""))
    fetch_call = ("code_calls.csv", ("python", "mylib.fetch"))
    sync_tool = ("program_network_requests.csv", ("synctool", "", "", ""))
    total = audit.TrialAuditTotal()
    for trial_id, task, rule_uses, row_uses, unknown_inputs, scopes, dotted in (
        (
            "t1",
            "task a",
            {
                "treat_web_find_as_uncertain_request": 2,
                "treat_dotted_host_name_as_public": 1,
            },
            {curl_row: 3},
            {mytool: 2, fetch_call: 1},
            {"public": 2, "unknown_dotted_name": 1},
            {"b.org": 1},
        ),
        (
            "t2",
            "task a",
            {"treat_web_find_as_uncertain_request": 1},
            {curl_row: 1},
            {mytool: 1, sync_tool: 4},
            {"public": 1},
            {"a.org": 2, "b.org": 1},
        ),
    ):
        knowledge_uses = KnowledgeUses()
        knowledge_uses.row_use_counts.update(row_uses)
        knowledge_uses.unknown_input_counts.update(unknown_inputs)
        trial_audit = audit.TrialAudit(
            trial_id,
            audit.EXTRACTED,
            task=task,
            judgment_rule_use_counts=Counter(rule_uses),
            knowledge_uses=knowledge_uses,
        )
        trial_audit.host_scope_request_counts.update(scopes)
        trial_audit.dotted_public_host_names.update(dotted)
        total.add_trial(trial_audit)

    audit.write_audit_files(total, tmp_path)

    assert _csv_rows(tmp_path / "judgment_rule_uses.csv")[1:] == [
        ["treat_web_find_as_uncertain_request", "3", "2"],
        ["treat_dotted_host_name_as_public", "1", "1"],
    ]
    assert _csv_rows(tmp_path / "knowledge_row_uses.csv")[1:] == [
        ["program_network_requests.csv", "curl   ", "4", "2"],
    ]
    # Most lookups first, not in the order of the names.
    assert _csv_rows(tmp_path / "unknown_inputs.csv")[1:] == [
        ["program_network_requests.csv", "synctool |  |  | ", "4", "1", "1"],
        # The two trials of mytool are of one task.
        ["program_network_requests.csv", "mytool |  |  | ", "3", "2", "1"],
        ["code_calls.csv", "python | mylib.fetch", "1", "1", "1"],
    ]
    # Each name that the rule reads as public comes with the most trials first, not in the order of the names.
    assert _csv_rows(tmp_path / "host_names_by_scope.csv")[1:] == [
        ["public", "", "3", "2"],
        ["unknown_dotted_name", "", "1", "1"],
        ["public by treat_dotted_host_name_as_public", "b.org", "2", "2"],
        ["public by treat_dotted_host_name_as_public", "a.org", "2", "1"],
    ]


def test_every_equation_starts_at_zero_for_a_trial_that_was_not_extracted():
    trial_audit = audit.TrialAudit("t1", audit.NOT_FOUND)

    assert list(trial_audit.equation_sides) == [
        (equation, side) for equation in audit.EQUATIONS for side in ("left", "right")
    ]


def test_an_unknown_equation_name_raises():
    with pytest.raises(ValueError, match="no equation"):
        audit.TrialAudit("t1", audit.EXTRACTED).add_sides("requests", 1, 1, None)


def _raw_trials_dir(tmp_path: Path) -> Path:
    """Make a raw trials folder with the made-up trial t1, a Claude Code `Bash` call that runs curl."""
    trial_dir = tmp_path / "raw" / "t1"
    trial_dir.mkdir(parents=True)
    (trial_dir / "detail.json").write_text(
        json.dumps(
            {
                "id": "t1",
                "task_name": "terminal-bench/fix-git",
                "agent_info": {
                    "name": "claude-code",
                    "version": "2.1.0",
                    "model_info": {"name": "model-a"},
                },
                "verifier_result": {"rewards": {"reward": 1.0}},
            }
        )
    )
    (trial_dir / "status.json").write_text(
        json.dumps(
            {
                "trial_id": "t1",
                "memberships": [{"version": "4-0-0", "row_id": "row-1"}],
                "assets": {"trajectory": {"status": "downloaded"}},
            }
        )
    )
    trajectory = {
        "schema_version": "ATIF-v1.7",
        "agent": {"name": "claude-code"},
        "steps": [
            {
                "step_id": 1,
                "tool_calls": [
                    {
                        "tool_call_id": "a",
                        "function_name": "Bash",
                        "arguments": {"command": "curl https://a.org/x"},
                    }
                ],
                "observation": {"results": [{"source_call_id": "a", "content": "ok"}]},
            }
        ],
    }
    (trial_dir / "trajectory.json").write_text(json.dumps(trajectory))
    return tmp_path / "raw"


def test_audit_trial_extracts_and_checks_a_trial_folder(tmp_path):
    trial_audit = audit.audit_trial(_raw_trials_dir(tmp_path) / "t1")

    assert trial_audit.outcome == audit.EXTRACTED
    assert trial_audit.harness == "claude-code"
    assert trial_audit.task == "4-0-0 terminal-bench/fix-git"
    assert _differing_equations(trial_audit) == set()
    assert trial_audit.counts["all", "requests from FromCommand"] == 1


def test_audit_trial_gives_the_same_lookups_for_a_trial_audited_twice(tmp_path):
    trial_dir = _raw_trials_dir(tmp_path) / "t1"

    first = audit.audit_trial(trial_dir)
    second = audit.audit_trial(trial_dir)

    assert first.knowledge_uses.row_use_counts
    assert second.knowledge_uses == first.knowledge_uses


def test_audit_trial_names_a_missing_folder_apart_from_a_missing_trajectory(
    tmp_path,
):
    raw_trials_dir = _raw_trials_dir(tmp_path)
    (raw_trials_dir / "t2").mkdir()

    assert audit.audit_trial(raw_trials_dir / "t9").outcome == audit.NOT_FOUND
    assert audit.audit_trial(raw_trials_dir / "t2").outcome == "unreadable missing"


class _InProcessPool:
    """Stand-in for the process pool of `main`, which maps in the test process so that a function that a test replaces is replaced in the run too, and keeps the process count it was asked for."""

    # The process counts that `main` asked for, kept across instances.
    process_counts: ClassVar[list[int]] = []

    def __init__(self, process_count: int) -> None:
        self.process_counts.append(process_count)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exception: object) -> None:
        pass

    def map(
        self, function: Callable[[Path], Any], items: Iterable[Path], chunksize: int
    ) -> Iterator[Any]:
        return map(function, items)


def _run_main(
    monkeypatch: pytest.MonkeyPatch, raw_trials_dir: Path, out_dir: Path
) -> None:
    """Run `main` on the trial ids t1, t1 again and t9, which names no folder."""
    trial_ids_file = raw_trials_dir.parent / "trial_ids.txt"
    trial_ids_file.write_text("t1\tclaude-code\nt1\nt9\n")
    monkeypatch.setattr(audit, "ProcessPoolExecutor", _InProcessPool)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "audit_network_requests",
            str(raw_trials_dir),
            "--trial-ids",
            str(trial_ids_file),
            "--out-dir",
            str(out_dir),
        ],
    )
    audit.main()


def test_main_runs_a_repeated_trial_once_and_names_a_missing_one(tmp_path, monkeypatch):
    _InProcessPool.process_counts.clear()
    out_dir = tmp_path / "out"

    _run_main(monkeypatch, _raw_trials_dir(tmp_path), out_dir)

    assert _InProcessPool.process_counts
    assert max(_InProcessPool.process_counts) <= 4
    assert _csv_rows(out_dir / "trial_outcomes.csv") == [
        ["outcome", "trial_count", "first_trial_ids"],
        ["extracted", "1", "t1"],
        ["not found", "1", "t9"],
    ]
    equation_rows = _csv_rows(out_dir / "equations.csv")[1:]
    assert [row[0] for row in equation_rows] == list(audit.EQUATIONS)
    assert {row[3] for row in equation_rows} == {"yes"}
    assert ["all", "requests", "1"] in _csv_rows(out_dir / "counts_by_harness.csv")


def test_main_names_a_trial_that_raised_and_exits_1(tmp_path, monkeypatch):
    def raise_error(*arguments: object, **keywords: object) -> None:
        raise RuntimeError

    monkeypatch.setattr(audit, "extract_network_requests", raise_error)
    out_dir = tmp_path / "out"

    with pytest.raises(SystemExit) as exit_info:
        _run_main(monkeypatch, _raw_trials_dir(tmp_path), out_dir)

    assert exit_info.value.code == 1
    assert _csv_rows(out_dir / "trials_not_extracted.csv") == [
        ["trial_id", "outcome"],
        ["t1", "exception RuntimeError"],
        ["t9", "not found"],
    ]
