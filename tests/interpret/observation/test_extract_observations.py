"""Tests for interpret/observation/_extract_observations.py."""

import json
import time

from tb_internet_use.interpret.observation import extract_observations
from tb_internet_use.interpret.observation.model import (
    HttpStatusField,
    ObservationKind,
    OutputLine,
)
from tb_internet_use.parse.toolcall.model import (
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
)

COMMAND = RunCommandAction("x")


def _call(
    text: str | None,
    action: Action = COMMAND,
    http_status: int | None = None,
) -> ToolCall:
    key = ToolCallKey("trial", "main", 1, 0)
    output = ToolCallOutput(
        tool_output_text=text,
        execution_status=ExecutionStatus.FINISHED,
        http_status=http_status,
    )
    return ToolCall(
        RawToolCall(key, HarnessTool("h", "t"), "", {}, None), action, output
    )


def test_lines_and_their_places():
    text = "Collecting x\n  Downloading x-1.0.whl\nSuccessfully installed x-1.0\n"
    observations = extract_observations(_call(text))
    assert [(o.place, o.kind) for o in observations] == [
        (OutputLine(1, None), ObservationKind.DOWNLOAD_STARTED),
        (OutputLine(2, None), ObservationKind.INSTALLED),
    ]


def test_http_status_field():
    (observation,) = extract_observations(
        _call("page text", WebFetchAction(("https://a.org",)), http_status=403)
    )
    assert (observation.place, observation.kind, observation.status_code) == (
        HttpStatusField(),
        ObservationKind.HTTP_STATUS,
        403,
    )


def test_lines_of_a_json_output_string():
    step_result = json.dumps(
        {
            "output": "Collecting x\nSuccessfully installed x-1.0\ncurl: (6) Could not resolve host: a.org",
            "exit_code": 1,
        }
    )
    observations = extract_observations(_call(f"step 1\n{step_result}\n{{not json"))
    assert [(o.place, o.kind) for o in observations] == [
        (OutputLine(1, 1), ObservationKind.INSTALLED),
        (OutputLine(1, 2), ObservationKind.NAME_NOT_RESOLVED),
    ]


def test_lines_are_read_as_a_terminal_shows_them():
    step_result = json.dumps({"output": "Downloading x 10%\rDownloaded x-1.0"})
    text = (
        "\x1b[32mSuccessfully installed x-1.0\x1b[0m\n"
        "Downloading y 10%\rSuccessfully installed y-1.0\n"
        "200\r\n"
        "HTTP/1.1 200 OK\rContent-Length: 9\n"
        f"{step_result}"
    )
    observations = extract_observations(_call(text))
    assert [(o.place, o.kind, o.package_names) for o in observations] == [
        (OutputLine(0, None), ObservationKind.INSTALLED, frozenset({"x"})),
        (OutputLine(1, None), ObservationKind.INSTALLED, frozenset({"y"})),
        (OutputLine(2, None), ObservationKind.BARE_STATUS_CODE, frozenset()),
        (OutputLine(3, None), ObservationKind.HTTP_STATUS, frozenset()),
        (OutputLine(4, 0), ObservationKind.DOWNLOADED, frozenset({"x"})),
    ]


def test_a_web_tool_result_is_read_as_page_text():
    page = "Successfully installed x-1.0\nPlease verify you are not a robot"
    (observation,) = extract_observations(
        _call(page, WebFetchAction(("https://a.org",)))
    )
    assert (
        observation.kind,
        observation.place,
        observation.is_printed_by_other_programs_too,
    ) == (
        ObservationKind.SERVER_ANSWERED,
        OutputLine(1, None),
        False,
    )


def test_a_tool_script_without_steps_is_read_as_program_output():
    call = _call("curl: (6) Could not resolve host: a.org", RunToolScriptAction())
    (observation,) = extract_observations(call)
    assert observation.kind == ObservationKind.NAME_NOT_RESOLVED


def test_no_result_gives_no_observation():
    call = _call(None)
    assert extract_observations(ToolCall(call.raw, call.action, None)) == ()


def test_long_output_is_scanned_in_linear_time():
    one_long_line = "a" * 2_000_000
    many_codes = "\n".join(["200"] * 200_000)
    start = time.perf_counter()
    assert extract_observations(_call(one_long_line)) == ()
    assert len(extract_observations(_call(many_codes))) == 200_000
    assert time.perf_counter() - start < 10
