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

_TEXT = ("output", "output_head", "output_tail")
_ENDED = {"tool_output": _TEXT, "exit_code": "returncode"}
_STOPPED = {"tool_output": _TEXT}
_TIMED_OUT = JsonCondition("exception_info", "contains", "timed out")
_NOT_EXECUTED = JsonCondition("exception_info", "startswith", "action was not executed")
_SIGNALED = JsonCondition("returncode", "<", 0)
_EXITED = JsonCondition("returncode", ">", -1)

_BASH = HarnessResultFormatList[JsonObject](
    (
        Json("not_executed", S.NOT_RUN, condition=_NOT_EXECUTED),
        Json(
            "timed_out",
            S.TIMED_OUT,
            _STOPPED,
            absent_paths=("elided_chars",),
            condition=_TIMED_OUT,
        ),
        Json(
            "timed_out_truncated",
            S.TIMED_OUT,
            _STOPPED,
            present_paths=("elided_chars",),
            condition=_TIMED_OUT,
            is_truncated=True,
        ),
        Json(
            "killed",
            S.KILLED,
            _STOPPED,
            present_paths=("output",),
            absent_paths=("exception_info",),
            condition=_SIGNALED,
        ),
        Json(
            "killed_truncated",
            S.KILLED,
            _STOPPED,
            present_paths=("output_head",),
            absent_paths=("exception_info",),
            condition=_SIGNALED,
            is_truncated=True,
        ),
        Json(
            "exited",
            S.FINISHED,
            _ENDED,
            present_paths=("output",),
            absent_paths=("exception_info", "elided_chars"),
            condition=_EXITED,
        ),
        Json(
            "exited_truncated",
            S.FINISHED,
            _ENDED,
            present_paths=("output_head", "output_tail"),
            absent_paths=("exception_info",),
            condition=_EXITED,
            is_truncated=True,
        ),
    )
)


RESULT_FORMATS_BY_TOOL: Mapping[str, HarnessToolResultDeclaration] = {
    "bash": HarnessToolResultDeclaration(json_formats=_BASH),
}
