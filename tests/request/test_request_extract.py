"""Tests for request/extract.py."""

from dataclasses import replace

from tb_internet_use.callrun import expand_calls
from tb_internet_use.network.model import Host, HostKind, PrintingProgram
from tb_internet_use.program.model import ExitZeroMeans, RequestKind
from tb_internet_use.request import extract_candidate_requests
from tb_internet_use.request.model import (
    CandidateRequest,
    FromCommand,
    FromWebTool,
    RequestTarget,
)
from tb_internet_use.toolcall.model import (
    Action,
    ExecutionStatus,
    HarnessTool,
    RawToolCall,
    RunCommandAction,
    RunToolScriptAction,
    ToolCall,
    ToolCallKey,
    ToolCallOutput,
    WebFetchAction,
    WebFindAction,
    WebSearchAction,
    WriteFileAction,
)


def _call(step_id: int, action: Action) -> ToolCall:
    key = ToolCallKey("trial", "main", step_id, 0)
    output = ToolCallOutput(execution_status=ExecutionStatus.FINISHED)
    return ToolCall(
        RawToolCall(key, HarnessTool("h", "t"), "", {}, None), action, output
    )


def _requests(*actions: Action) -> tuple[CandidateRequest, ...]:
    call_runs = expand_calls([_call(i, a) for i, a in enumerate(actions, 1)])
    return extract_candidate_requests(call_runs[-1])


def test_example_of_the_pipeline_doc():
    write = WriteFileAction("fetch.sh", "curl -sS -O https://data.example.org/a.tgz")
    run = RunCommandAction("bash fetch.sh > fetch.log 2>&1 || pip install requests")
    key = ToolCallKey("trial", "main", 2, 0)
    pip, curl = _requests(write, run)
    assert curl == CandidateRequest(
        call=key,
        source=FromCommand(2),
        kind=RequestKind.URL,
        program_name="curl",
        targets=(
            RequestTarget(
                "https://data.example.org/a.tgz", "https://data.example.org/a.tgz", None
            ),
        ),
        hosts=(Host("data.example.org", HostKind.RESERVED),),
        asked_package_names=frozenset(),
        printing_programs=frozenset({PrintingProgram.CURL}),
        fetches_only_to_run_or_build=False,
        has_offline_option=False,
        exit_zero_means=ExitZeroMeans.SERVER_RESPONDED,
        asks_for_no_content=False,
        prints_response_body=False,
        prints_status_code=False,
        quiet_progress_lines=True,
        quiet_error_lines=False,
    )
    assert (pip.source, pip.kind, pip.program_name, pip.asked_package_names) == (
        FromCommand(1),
        RequestKind.PACKAGE,
        "pip",
        frozenset({"requests"}),
    )
    assert pip.exit_zero_means == ExitZeroMeans.NOTHING


def test_one_request_per_command_with_every_loop_value():
    (request,) = _requests(RunCommandAction("for p in a b; do pip install $p; done"))
    assert request.targets == (
        RequestTarget("$p", "a", "p"),
        RequestTarget("$p", "b", "p"),
    )
    assert request.asked_package_names == frozenset({"a", "b"})


def test_commands_without_a_request():
    texts = [
        "curl --version",
        "pip install --help",
        "curl",  # no target
        "pip list",
        "rsync -a ./a /b",  # names no host
        "cat log",
    ]
    for text in texts:
        assert _requests(RunCommandAction(text)) == (), text


def test_a_call_the_tool_did_not_run_keeps_its_candidate_requests():
    # A rejected request still counts as attempted, and the call's status tells that it did not run.
    call = replace(
        _call(1, RunCommandAction("curl https://a.org")),
        output=ToolCallOutput(execution_status=ExecutionStatus.NOT_RUN),
    )
    (request,) = extract_candidate_requests(expand_calls([call])[0])
    assert (request.call, request.program_name) == (call.raw.key, "curl")


def test_a_name_lookup_names_its_hosts():
    (request,) = _requests(RunCommandAction("getent hosts pypi.org"))
    assert (request.kind, request.program_name, request.hosts) == (
        RequestKind.REMOTE_HOST,
        "getent",
        (Host("pypi.org", HostKind.PUBLIC),),
    )


def test_a_subcommand_without_a_target_makes_a_request():
    (request,) = _requests(RunCommandAction("npm install"))
    assert (request.targets, request.asked_package_names) == ((), None)


def test_options_change_the_request():
    (curl,) = _requests(RunCommandAction("curl -fsI -w '%{http_code}' https://a.org"))
    assert curl.exit_zero_means == ExitZeroMeans.REQUEST_SUCCEEDED
    assert curl.asks_for_no_content and not curl.prints_response_body
    assert curl.prints_status_code and curl.quiet_error_lines
    assert {PrintingProgram.HTTP_HEADERS, PrintingProgram.HTTP_FAILURE} <= set(
        curl.printing_programs
    )
    (pip,) = _requests(
        RunCommandAction("pip install --no-index -i https://i.org/simple x")
    )
    assert pip.has_offline_option
    assert pip.hosts == (Host("i.org", HostKind.PUBLIC),)


def test_a_program_that_gets_its_targets_at_run_time_makes_a_request():
    (request,) = _requests(RunCommandAction("cat urls | xargs curl -O"))
    assert request.program_name == "curl" and request.targets == ()


def test_requests_of_programs_that_npx_runs():
    (playwright,) = _requests(RunCommandAction("npx -y playwright install chromium"))
    assert (playwright.program_name, playwright.kind) == ("playwright", RequestKind.URL)
    assert PrintingProgram.NPM in playwright.printing_programs
    (tsc,) = _requests(RunCommandAction("npx tsc --version"))
    assert (tsc.program_name, tsc.fetches_only_to_run_or_build, tsc.targets) == (
        "npx",
        True,
        (RequestTarget("tsc", "tsc", None),),
    )
    (pytest_run,) = _requests(RunCommandAction("uv run pytest -q"))
    assert not pytest_run.quiet_progress_lines


def test_web_tool_steps():
    script = RunToolScriptAction(
        steps=(
            WebSearchAction(("q",)),
            WebFetchAction(("https://a.org/x",)),
            WebFindAction(("https://a.org/x",)),
        )
    )
    requests = _requests(script)
    assert [(r.kind, r.source) for r in requests] == [
        (RequestKind.WEB_SEARCH, FromWebTool(0)),
        (RequestKind.WEB_FETCH, FromWebTool(1)),
        (RequestKind.WEB_FIND, FromWebTool(2)),
    ]
    assert requests[1].hosts == (Host("a.org", HostKind.PUBLIC),)
    assert all(r.prints_response_body and r.program_name is None for r in requests)


def test_code_request_names_its_runner():
    (request,) = _requests(
        RunCommandAction("python3 -c 'import requests; requests.get(u)'")
    )
    assert (request.kind, request.program_name) == (RequestKind.CODE, "python")
    behind_uv = _requests(
        WriteFileAction("get.py", "import requests; requests.get(u)"),
        RunCommandAction("uv run python get.py"),
    )
    assert [(r.kind, r.program_name) for r in behind_uv] == [
        (RequestKind.PACKAGE, "uv"),
        (RequestKind.CODE, "python"),
    ]
