"""Tests for parse_tool_output_text.py, with made-up tool output texts shaped as in the trajectories."""

import json
import time

import pytest

from tb_internet_use.network_request_result.model import ToolOutputLine
from tb_internet_use.network_request_result.parse_tool_output_text import (
    parse_tool_output_text,
)


def _codex_step_result_line(output: str, **other_keys: object) -> str:
    """Make one JSON line as a Codex `exec` script prints the result of a step."""
    return json.dumps({"chunk_id": "a1", "output": output, **other_keys})


def test_every_line_keeps_its_0_based_index_and_an_empty_last_line_stays():
    assert parse_tool_output_text("Collecting x\n  Downloading x-1.0.whl\n") == (
        ToolOutputLine(0, None, ("Collecting x",)),
        ToolOutputLine(1, None, ("  Downloading x-1.0.whl",)),
        ToolOutputLine(2, None, ("",)),
    )


def test_a_codex_step_result_line_is_read_as_the_lines_of_its_output_string():
    # The `exit_code` of the step is not read, so no field of the lines holds it.
    step_result = _codex_step_result_line(
        "a\nCould not resolve host: a.org", exit_code=6
    )
    assert parse_tool_output_text(f"step 1\n{step_result}\ndone") == (
        ToolOutputLine(0, None, ("step 1",)),
        ToolOutputLine(1, 0, ("a",)),
        ToolOutputLine(1, 1, ("Could not resolve host: a.org",)),
        ToolOutputLine(2, None, ("done",)),
    )


def test_an_empty_output_string_gives_one_empty_line():
    assert parse_tool_output_text(_codex_step_result_line("", exit_code=0)) == (
        ToolOutputLine(0, 0, ("",)),
    )


@pytest.mark.parametrize(
    "line",
    [
        pytest.param("{not json", id="broken JSON"),
        pytest.param('{"chunk_id": "a1", "output": ["a"]}', id="output not a string"),
        pytest.param('["output", "a"]', id="JSON array"),
        pytest.param('{"session_id": 3, "note": "no output yet"}', id="no output key"),
    ],
)
def test_a_line_that_is_no_json_object_with_an_output_string_stays_one_line(
    line: str,
):
    assert parse_tool_output_text(line) == (ToolOutputLine(0, None, (line,)),)


def test_parts_split_at_carriage_returns_come_last_part_first_without_color_codes():
    text = (
        "Downloading x 10%\rSuccessfully downloaded x\n"
        "\x1b[32mSuccessfully installed y-1.0\x1b[0m\n"
        "200\r\n"
        "HTTP/1.1 200 OK\rContent-Length: 9\n"
        "Done\r\x1b[0m\n"
        "Downloading x 50%\x1b[K\rDownloaded x\n"
        + _codex_step_result_line("Downloading z 10%\rDownloaded z-1.0\r")
    )
    assert parse_tool_output_text(text) == (
        ToolOutputLine(0, None, ("Successfully downloaded x", "Downloading x 10%")),
        ToolOutputLine(1, None, ("Successfully installed y-1.0",)),
        ToolOutputLine(2, None, ("200",)),
        ToolOutputLine(3, None, ("Content-Length: 9", "HTTP/1.1 200 OK")),
        ToolOutputLine(4, None, ("Done",)),
        ToolOutputLine(5, None, ("Downloaded x", "Downloading x 50%")),
        ToolOutputLine(6, 0, ("Downloaded z-1.0", "Downloading z 10%")),
    )


def test_long_output_is_split_in_linear_time():
    one_long_line = "{" + "a" * 2_000_000
    many_lines = "\n".join(["200"] * 200_000)
    start = time.perf_counter()
    assert parse_tool_output_text(one_long_line) == (
        ToolOutputLine(0, None, (one_long_line,)),
    )
    many_tool_output_lines = parse_tool_output_text(many_lines)
    assert len(many_tool_output_lines) == 200_000
    assert many_tool_output_lines[-1] == ToolOutputLine(199_999, None, ("200",))
    assert time.perf_counter() - start < 10
