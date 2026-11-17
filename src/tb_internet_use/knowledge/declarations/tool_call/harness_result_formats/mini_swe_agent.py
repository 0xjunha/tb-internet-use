"""Declare the result formats of mini-swe-agent tools."""

from collections.abc import Mapping

from tb_internet_use.knowledge.harness_result_format_declaration import (
    HarnessJsonResultFormat,
    HarnessResultFormatList,
    HarnessToolResultDeclaration,
    JsonCondition,
    JsonObject,
)
from tb_internet_use.tool_call.model import (
    ExecutionStatus,
)

S = ExecutionStatus
Json = HarnessJsonResultFormat

_TOOL_OUTPUT_PATHS = ("output", "output_head", "output_tail")
_ENDED_VALUE_PATHS = {"tool_output": _TOOL_OUTPUT_PATHS, "exit_code": "returncode"}
_STOPPED_VALUE_PATHS = {"tool_output": _TOOL_OUTPUT_PATHS}
_TIMED_OUT_CONDITION = JsonCondition("exception_info", "contains", "timed out")
_NOT_EXECUTED_CONDITION = JsonCondition(
    "exception_info", "startswith", "action was not executed"
)
_SIGNALED_CONDITION = JsonCondition("returncode", "<", 0)
_EXITED_CONDITION = JsonCondition("returncode", ">", -1)

_BASH = HarnessResultFormatList[JsonObject](
    (
        Json("not_executed", S.NOT_RUN, condition=_NOT_EXECUTED_CONDITION),
        Json(
            "timed_out",
            S.TIMED_OUT,
            _STOPPED_VALUE_PATHS,
            absent_paths=("elided_chars",),
            condition=_TIMED_OUT_CONDITION,
        ),
        Json(
            "timed_out_truncated",
            S.TIMED_OUT,
            _STOPPED_VALUE_PATHS,
            present_paths=("elided_chars",),
            condition=_TIMED_OUT_CONDITION,
            is_truncated=True,
        ),
        Json(
            "killed",
            S.KILLED,
            _STOPPED_VALUE_PATHS,
            present_paths=("output",),
            absent_paths=("exception_info",),
            condition=_SIGNALED_CONDITION,
        ),
        Json(
            "killed_truncated",
            S.KILLED,
            _STOPPED_VALUE_PATHS,
            present_paths=("output_head",),
            absent_paths=("exception_info",),
            condition=_SIGNALED_CONDITION,
            is_truncated=True,
        ),
        Json(
            "exited",
            S.FINISHED,
            _ENDED_VALUE_PATHS,
            present_paths=("output",),
            absent_paths=("exception_info", "elided_chars"),
            condition=_EXITED_CONDITION,
        ),
        Json(
            "exited_truncated",
            S.FINISHED,
            _ENDED_VALUE_PATHS,
            present_paths=("output_head", "output_tail"),
            absent_paths=("exception_info",),
            condition=_EXITED_CONDITION,
            is_truncated=True,
        ),
    )
)


RESULT_FORMATS_BY_TOOL: Mapping[str, HarnessToolResultDeclaration] = {
    "bash": HarnessToolResultDeclaration(json_formats=_BASH),
}
