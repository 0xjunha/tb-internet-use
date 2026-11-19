"""Tests for knowledge/tool_call_knowledge.py, with made-up catalogs."""

import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from tb_internet_use.knowledge.catalog import KnowledgeUses
from tb_internet_use.knowledge.harness_result_format_declaration import (
    HarnessJsonResultFormat,
    HarnessResultFormatList,
    HarnessTextResultFormat,
    HarnessToolResultDeclaration,
    JsonObject,
    MatchedHarnessResultFormat,
)
from tb_internet_use.knowledge.tool_call_knowledge import (
    HARNESS_RESULT_FORMATS_DECLARATIONS,
    HARNESS_RETURN_CODE_INTERPRETATIONS_CSV,
    HARNESS_TOOL_ARGUMENTS_CSV,
    HARNESS_TOOLS_CSV,
    ToolCallKnowledge,
)
from tb_internet_use.tool_call.model import (
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessTool,
    HarnessToolLabel,
    UnknownHarnessReturnCodeInterpretation,
    UnknownHarnessToolLabel,
    UnmatchedFormat,
)

_TOOLS_HEADER = "harness,tool,action_type,stops_execution,checked_against,reviewed,note"
_ARGUMENTS_HEADER = (
    "harness,tool,argument,action_field,handle_kind,checked_against,reviewed,note"
)
_RETURN_CODE_INTERPRETATIONS_HEADER = (
    "harness,tool,return_code_interpretation,exit_code,checked_against,reviewed,note"
)
# The values of the three columns that no code reads.
_REVIEW_COLUMNS = ",a manual,yes,"

_TOOL_ROWS = ("h,stop,PollAction,yes", "h,list,OtherAction,")
_ARGUMENT_ROWS = ("h,stop,id,handles,command", "h,stop,text,input,")
# The exit code is not 1, so that a door that gives 1 without reading the row fails.
_RETURN_CODE_INTERPRETATION_ROWS = ("h,list,Nothing listed,2",)

# (tool rows, argument rows, a part of the error message)
_ROWS_THAT_CANNOT_LOAD = [
    (["h,t,NoSuchAction,"], [], "'NoSuchAction' names no ToolCallAction class"),
    (
        ["h,t,RunCommandAction,"],
        ["h,t,a,path,"],
        "RunCommandAction has no field 'path'",
    ),
    # A Deferred tool has no action class, so none of its arguments can fill a field.
    (["h,t,Deferred,"], ["h,t,a,code,"], "Deferred has no field 'code'"),
    (["h,t,PollAction,no"], ["h,t,a,handles,shell"], "'shell' is not a valid"),
    (["h,t,PollAction,no"], ["h,t,a,input,command"], "handle_kind on the field"),
    (["h,t,OtherAction,"], ["h,other,a,path,"], "has no row in harness_tools.csv"),
    (["h,t,PollAction,maybe"], [], "stops_execution"),
    # An empty value on a poll tool would be read as `no`.
    (["h,t,PollAction,"], [], "stops_execution"),
    # Only a PollAction can stop something, so `yes` elsewhere would be ignored.
    (["h,t,OtherAction,yes"], [], "stops_execution"),
    (
        ["h,t,PollAction,no"],
        ["h,t,a,handles,command", "h,t,b,handles,script"],
        "differ in handle_kind",
    ),
]
# (return code interpretation rows, a part of the error message), with the tool rows of `_TOOL_ROWS`
_RETURN_CODE_INTERPRETATION_ROWS_THAT_CANNOT_LOAD = [
    (["h,other,Nothing listed,1"], "has no row in harness_tools.csv"),
    (["h,list,Nothing listed,one"], "invalid literal for int"),
    (["h,list,Nothing listed,"], "invalid literal for int"),
]

EXITED = HarnessTextResultFormat(
    "exited", "exit {exit_code:int}\n{tool_output:text}", ExecutionStatus.FINISHED
)
FAILED = HarnessTextResultFormat(
    "failed", "error {tool_output:text}", ExecutionStatus.FINISHED
)
DONE = HarnessJsonResultFormat("done", ExecutionStatus.FINISHED, present_paths=("a",))
# Made-up declarations of the harness `h`, whose tool `list` has no formats.
RESULT_FORMATS_BY_HARNESS = {
    "h": {
        "shell": HarnessToolResultDeclaration(
            text_formats=HarnessResultFormatList[str]((EXITED,)),
            text_formats_when_marked_as_error=HarnessResultFormatList[str]((FAILED,)),
        ),
        "fetch": HarnessToolResultDeclaration(
            json_formats=HarnessResultFormatList[JsonObject]((DONE,))
        ),
    }
}

# (tool name, raw text, JSON object, whether the harness marked it as an error, the name of the format found or the `UnmatchedFormat`)
RESULT_FORMAT_CASES = [
    ("shell", "exit 3\nhi", None, False, "exited"),
    ("shell", "something else", None, False, UnmatchedFormat.UNKNOWN),
    # A result marked as an error is held against the list for such results only.
    ("shell", "error boom", None, True, "failed"),
    ("shell", "exit 3\nhi", None, True, UnmatchedFormat.UNKNOWN),
    ("fetch", '{"a": 1}', {"a": 1}, False, "done"),
    # A tool with JSON formats only can match nothing in a text result.
    ("fetch", "plain", None, False, UnmatchedFormat.UNKNOWN),
    ("list", "anything", None, False, UnmatchedFormat.SKIPPED),
]


def _write_catalogs(
    tmp_path: Path,
    tool_rows: list[str],
    argument_rows: list[str],
    return_code_interpretation_rows: list[str] | None = None,
) -> Path:
    """Write the three harness tool CSVs into a folder and return the folder, with no return code interpretation rows unless given."""
    for file_name, header, rows in (
        (HARNESS_TOOLS_CSV, _TOOLS_HEADER, tool_rows),
        (HARNESS_TOOL_ARGUMENTS_CSV, _ARGUMENTS_HEADER, argument_rows),
        (
            HARNESS_RETURN_CODE_INTERPRETATIONS_CSV,
            _RETURN_CODE_INTERPRETATIONS_HEADER,
            return_code_interpretation_rows or [],
        ),
    ):
        lines = [header, *(row + _REVIEW_COLUMNS for row in rows)]
        (tmp_path / file_name).write_text("\n".join(lines) + "\n")
    return tmp_path


def test_label_of_a_tool_merges_its_row_with_the_rows_of_the_arguments_of_the_call(
    tmp_path,
):
    catalogs_dir = _write_catalogs(tmp_path, list(_TOOL_ROWS), list(_ARGUMENT_ROWS))
    knowledge = ToolCallKnowledge(catalogs_dir=catalogs_dir)

    # An argument without a row, here `wait`, fills no field.
    assert knowledge.harness_tool_label(
        HarnessTool("h", "stop"), ("id", "text", "wait")
    ) == HarnessToolLabel(
        action_type="PollAction",
        action_field_by_argument_name={"id": "handles", "text": "input"},
        stops_execution=True,
        argument_handle_kind=ExecutionHandleKind.COMMAND,
    )
    # A call without the `handles` argument gets no handle kind, since it has no handle to give one.
    assert knowledge.harness_tool_label(
        HarnessTool("h", "stop"), ("text",)
    ) == HarnessToolLabel(
        action_type="PollAction",
        action_field_by_argument_name={"text": "input"},
        stops_execution=True,
        argument_handle_kind=None,
    )
    assert knowledge.harness_tool_label(
        HarnessTool("h", "list"), ()
    ) == HarnessToolLabel(
        action_type="OtherAction",
        action_field_by_argument_name={},
        stops_execution=False,
        argument_handle_kind=None,
    )


def test_tool_without_a_row_is_unknown_and_an_argument_row_counts_only_the_calls_with_its_argument(
    tmp_path,
):
    catalogs_dir = _write_catalogs(tmp_path, list(_TOOL_ROWS), list(_ARGUMENT_ROWS))
    knowledge = ToolCallKnowledge(catalogs_dir=catalogs_dir)

    answer = knowledge.harness_tool_label(HarnessTool("h", "new"), ("id",))
    knowledge.harness_tool_label(HarnessTool("h", "stop"), ("id", "text"))
    knowledge.harness_tool_label(HarnessTool("h", "stop"), ("id",))
    # A call without either argument counts the tool row only, and its argument without a row counts nothing.
    knowledge.harness_tool_label(HarnessTool("h", "stop"), ("wait",))

    assert answer == UnknownHarnessToolLabel()
    assert knowledge.uses == KnowledgeUses(
        row_use_counts=Counter(
            {
                (HARNESS_TOOLS_CSV, ("h", "stop")): 3,
                (HARNESS_TOOL_ARGUMENTS_CSV, ("h", "stop", "id")): 2,
                (HARNESS_TOOL_ARGUMENTS_CSV, ("h", "stop", "text")): 1,
            }
        ),
        unknown_input_counts=Counter({(HARNESS_TOOLS_CSV, ("h", "new")): 1}),
    )


def test_each_door_counts_only_its_own_lookups(tmp_path):
    catalogs_dir = _write_catalogs(tmp_path, list(_TOOL_ROWS), list(_ARGUMENT_ROWS))
    first = ToolCallKnowledge(catalogs_dir=catalogs_dir)
    second = ToolCallKnowledge(catalogs_dir=catalogs_dir)

    first.harness_tool_label(HarnessTool("h", "list"), ())

    assert second.uses == KnowledgeUses()


@pytest.mark.parametrize(
    ("tool_rows", "argument_rows", "message"), _ROWS_THAT_CANNOT_LOAD
)
def test_row_that_convert_tool_calls_cannot_use_raises_when_the_catalogs_load(
    tmp_path, tool_rows, argument_rows, message
):
    catalogs_dir = _write_catalogs(tmp_path, tool_rows, argument_rows)

    with pytest.raises(ValueError, match=message):
        ToolCallKnowledge(catalogs_dir=catalogs_dir)


def test_return_code_interpretation_is_answered_with_its_exit_code_or_unknown_and_counted(
    tmp_path,
):
    catalogs_dir = _write_catalogs(
        tmp_path,
        list(_TOOL_ROWS),
        list(_ARGUMENT_ROWS),
        list(_RETURN_CODE_INTERPRETATION_ROWS),
    )
    knowledge = ToolCallKnowledge(catalogs_dir=catalogs_dir)

    known = knowledge.exit_code_of_harness_return_code_interpretation(
        HarnessTool("h", "list"), "Nothing listed"
    )
    knowledge.exit_code_of_harness_return_code_interpretation(
        HarnessTool("h", "list"), "Nothing listed"
    )
    unknown_text = knowledge.exit_code_of_harness_return_code_interpretation(
        HarnessTool("h", "list"), "Something else"
    )
    # The row belongs to one tool, so the same text of another tool is unknown.
    unknown_tool = knowledge.exit_code_of_harness_return_code_interpretation(
        HarnessTool("h", "stop"), "Nothing listed"
    )

    assert known == 2
    assert unknown_text == unknown_tool == UnknownHarnessReturnCodeInterpretation()
    assert knowledge.uses == KnowledgeUses(
        row_use_counts=Counter(
            {
                (
                    HARNESS_RETURN_CODE_INTERPRETATIONS_CSV,
                    ("h", "list", "Nothing listed"),
                ): 2
            }
        ),
        unknown_input_counts=Counter(
            {
                (
                    HARNESS_RETURN_CODE_INTERPRETATIONS_CSV,
                    ("h", "list", "Something else"),
                ): 1,
                (
                    HARNESS_RETURN_CODE_INTERPRETATIONS_CSV,
                    ("h", "stop", "Nothing listed"),
                ): 1,
            }
        ),
    )


@pytest.mark.parametrize(
    ("return_code_interpretation_rows", "message"),
    _RETURN_CODE_INTERPRETATION_ROWS_THAT_CANNOT_LOAD,
)
def test_return_code_interpretation_row_that_convert_tool_calls_cannot_use_raises_when_the_catalogs_load(
    tmp_path, return_code_interpretation_rows, message
):
    catalogs_dir = _write_catalogs(
        tmp_path, list(_TOOL_ROWS), [], return_code_interpretation_rows
    )

    with pytest.raises(ValueError, match=message):
        ToolCallKnowledge(catalogs_dir=catalogs_dir)


@pytest.mark.parametrize(
    ("tool_name", "raw_text", "tool_result_json", "is_marked_as_error", "found"),
    RESULT_FORMAT_CASES,
)
def test_result_format_is_answered_and_counted_as_a_row_use_or_an_unknown_input(
    tool_name: str,
    raw_text: str,
    tool_result_json: JsonObject | None,
    is_marked_as_error: bool,
    found: str | UnmatchedFormat,
):
    knowledge = ToolCallKnowledge(result_formats_by_harness=RESULT_FORMATS_BY_HARNESS)

    matched_or_unmatched_format = knowledge.harness_result_format(
        HarnessTool("h", tool_name),
        raw_text,
        tool_result_json,
        is_marked_as_error=is_marked_as_error,
    )

    if isinstance(found, UnmatchedFormat):
        assert matched_or_unmatched_format is found
        assert knowledge.uses == KnowledgeUses(
            unknown_input_counts=Counter(
                {(HARNESS_RESULT_FORMATS_DECLARATIONS, ("h", tool_name, str(found))): 1}
            )
        )
    else:
        assert isinstance(matched_or_unmatched_format, MatchedHarnessResultFormat)
        assert matched_or_unmatched_format.format.name == found
        assert knowledge.uses == KnowledgeUses(
            row_use_counts=Counter(
                {(HARNESS_RESULT_FORMATS_DECLARATIONS, ("h", tool_name, found)): 1}
            )
        )


def test_matched_result_format_carries_its_matched_values():
    knowledge = ToolCallKnowledge(result_formats_by_harness=RESULT_FORMATS_BY_HARNESS)

    matched_or_unmatched_format = knowledge.harness_result_format(
        HarnessTool("h", "shell"), "exit 3\nhi", None, is_marked_as_error=False
    )

    assert matched_or_unmatched_format == MatchedHarnessResultFormat(
        EXITED, {"exit_code": "3", "tool_output": "hi"}
    )


def test_only_a_tool_with_json_formats_has_them_and_asking_counts_nothing():
    knowledge = ToolCallKnowledge(result_formats_by_harness=RESULT_FORMATS_BY_HARNESS)

    assert knowledge.has_json_result_formats(HarnessTool("h", "fetch"))
    assert not knowledge.has_json_result_formats(HarnessTool("h", "shell"))
    assert not knowledge.has_json_result_formats(HarnessTool("other", "fetch"))
    assert knowledge.uses == KnowledgeUses()


def test_door_module_can_be_the_first_import_of_a_process():
    # The door imports the model of its step, whose package imports the door under TYPE_CHECKING only, so a fresh process shows that no cycle runs.
    module = "tb_internet_use.knowledge.tool_call_knowledge"
    subprocess.run([sys.executable, "-I", "-c", f"import {module}"], check=True)
