"""Tests for _decide_output_line_meanings.py, with made-up results read against the declared output line patterns."""

import json
from collections import Counter

import pytest

from tb_internet_use.knowledge.network_request_result_knowledge import (
    OUTPUT_LINE_PATTERNS_DECLARATIONS,
    NetworkRequestResultKnowledge,
)
from tb_internet_use.network_request_result._decide_output_line_meanings import (
    decide_output_line_meanings,
)
from tb_internet_use.network_request_result.model import (
    OutputLineKind,
    OutputLineWithMeaning,
)
from tb_internet_use.tool_call.model import (
    ExecutionStatus,
    HarnessTool,
    HarnessToolCall,
    RunCommandAction,
    ToolCall,
    ToolCallAction,
    ToolCallKey,
    ToolCallResult,
    WebFetchAction,
)

K = OutputLineKind
# A key other than the first call of a trial, so that a key made up inside the code does not match it by chance.
SHOWING_TOOL_CALL_KEY = ToolCallKey("trial", "main", 7, 2)
COMMAND = RunCommandAction("x")


def build_tool_call(
    result: ToolCallResult | None,
    action: ToolCallAction = COMMAND,
) -> ToolCall:
    return ToolCall(
        HarnessToolCall(SHOWING_TOOL_CALL_KEY, HarnessTool("h", "t"), "", {}, None),
        action,
        result,
    )


def build_finished_tool_call(
    tool_output_text: str, action: ToolCallAction = COMMAND
) -> ToolCall:
    return build_tool_call(
        ToolCallResult(
            tool_output_text=tool_output_text,
            execution_status=ExecutionStatus.FINISHED,
        ),
        action,
    )


def places_and_kinds_of(
    output_lines_with_meaning: tuple[OutputLineWithMeaning, ...],
) -> list[tuple[int, int | None, OutputLineKind]]:
    return [
        (
            output_line_with_meaning.line_index,
            output_line_with_meaning.line_index_in_json_string,
            output_line_with_meaning.output_line_meaning.kind,
        )
        for output_line_with_meaning in output_lines_with_meaning
    ]


def row_use_key_of_program_output_pattern(
    pattern_name: str,
) -> tuple[str, tuple[str, str]]:
    return OUTPUT_LINE_PATTERNS_DECLARATIONS, ("program_output", pattern_name)


def test_lines_with_a_pattern_keep_their_0_based_place_and_the_key_of_the_showing_call():
    knowledge = NetworkRequestResultKnowledge()
    tool_call = build_finished_tool_call(
        "Collecting x\n  Downloading x-1.0.whl\n  Downloading y-1.0.whl\nSuccessfully installed x-1.0 y-1.0\n"
    )

    output_lines_with_meaning = decide_output_line_meanings(
        tool_call, is_web_tool_result=False, knowledge=knowledge
    )

    assert places_and_kinds_of(output_lines_with_meaning) == [
        (1, None, K.DOWNLOAD_STARTED),
        (2, None, K.DOWNLOAD_STARTED),
        (3, None, K.INSTALLED),
    ]
    assert {
        output_line_with_meaning.showing_tool_call_key
        for output_line_with_meaning in output_lines_with_meaning
    } == {SHOWING_TOOL_CALL_KEY}


def test_a_blank_first_line_keeps_its_place_so_the_lines_after_it_count_from_1():
    output_lines_with_meaning = decide_output_line_meanings(
        build_finished_tool_call("\nSuccessfully installed x-1.0"),
        is_web_tool_result=False,
        knowledge=NetworkRequestResultKnowledge(),
    )

    assert places_and_kinds_of(output_lines_with_meaning) == [(1, None, K.INSTALLED)]


def test_a_result_that_timed_out_with_a_failing_exit_code_still_gives_its_line_meanings():
    tool_call = build_tool_call(
        ToolCallResult(
            tool_output_text="bash: pip: command not found",
            execution_status=ExecutionStatus.TIMED_OUT,
            exit_code=127,
        )
    )

    output_lines_with_meaning = decide_output_line_meanings(
        tool_call, is_web_tool_result=False, knowledge=NetworkRequestResultKnowledge()
    )

    assert places_and_kinds_of(output_lines_with_meaning) == [
        (0, None, K.PROGRAM_MISSING)
    ]


def test_lines_of_a_codex_step_result_keep_the_line_and_the_index_in_its_output_string():
    # The `exit_code` of the step is not read, so `exit_code` 6 changes no meaning.
    step_result = json.dumps(
        {
            "output": "Collecting x\nSuccessfully installed x-1.0\ncurl: (6) Could not resolve host: a.org",
            "exit_code": 6,
        }
    )

    output_lines_with_meaning = decide_output_line_meanings(
        build_finished_tool_call(f"step 1\n{step_result}\n{{not json"),
        is_web_tool_result=False,
        knowledge=NetworkRequestResultKnowledge(),
    )

    assert places_and_kinds_of(output_lines_with_meaning) == [
        (1, 1, K.INSTALLED),
        (1, 2, K.NAME_NOT_RESOLVED),
    ]


@pytest.mark.parametrize(
    ("tool_output_text", "kind", "pattern_name"),
    [
        # Both parts fit a pattern, and the last part is what a terminal shows.
        pytest.param(
            "Downloading x 10%\rSuccessfully downloaded x",
            K.DOWNLOADED,
            "pip_successfully_downloaded",
            id="progress drawn over by the last part",
        ),
        # Only the first part fits a pattern, since the text was joined without line breaks.
        pytest.param(
            "HTTP/1.1 200 OK\rContent-Length: 9",
            K.HTTP_STATUS,
            "http_status_line",
            id="header lines joined at \\r",
        ),
    ],
)
def test_a_line_means_what_its_first_part_with_a_pattern_means_from_the_last_part_and_counts_once(
    tool_output_text: str, kind: OutputLineKind, pattern_name: str
):
    knowledge = NetworkRequestResultKnowledge()

    output_lines_with_meaning = decide_output_line_meanings(
        build_finished_tool_call(tool_output_text),
        is_web_tool_result=False,
        knowledge=knowledge,
    )

    assert places_and_kinds_of(output_lines_with_meaning) == [(0, None, kind)]
    assert knowledge.uses.row_use_counts == Counter(
        {row_use_key_of_program_output_pattern(pattern_name): 1}
    )


def test_a_web_tool_result_is_read_with_the_web_tool_result_patterns_only():
    page_text = "Successfully installed x-1.0\nPlease verify you are not a robot"
    web_fetch_call = build_finished_tool_call(
        page_text, WebFetchAction(("https://a.org",))
    )

    in_web_tool_result = decide_output_line_meanings(
        web_fetch_call,
        is_web_tool_result=True,
        knowledge=NetworkRequestResultKnowledge(),
    )
    in_program_output = decide_output_line_meanings(
        web_fetch_call,
        is_web_tool_result=False,
        knowledge=NetworkRequestResultKnowledge(),
    )

    assert places_and_kinds_of(in_web_tool_result) == [(1, None, K.SERVER_ANSWERED)]
    assert places_and_kinds_of(in_program_output) == [(0, None, K.INSTALLED)]


def test_lines_without_a_pattern_give_nothing_and_count_nothing():
    knowledge = NetworkRequestResultKnowledge()
    tool_call = build_finished_tool_call(
        "Collecting x\nexit code: 127\r\nSuccessfully built x\n\n"
    )

    assert (
        decide_output_line_meanings(
            tool_call, is_web_tool_result=False, knowledge=knowledge
        )
        == ()
    )
    assert not knowledge.uses.row_use_counts
    assert not knowledge.uses.unknown_input_counts


@pytest.mark.parametrize(
    "result",
    [
        pytest.param(None, id="no result in the trajectory"),
        pytest.param(
            ToolCallResult(
                tool_output_text=None,
                execution_status=ExecutionStatus.FINISHED,
                http_status=404,
            ),
            id="a result without text",
        ),
    ],
)
def test_a_call_without_result_text_gives_no_line(result: ToolCallResult | None):
    knowledge = NetworkRequestResultKnowledge()

    assert (
        decide_output_line_meanings(
            build_tool_call(result), is_web_tool_result=False, knowledge=knowledge
        )
        == ()
    )
    assert not knowledge.uses.row_use_counts
