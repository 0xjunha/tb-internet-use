"""mini-swe-agent tool call converter."""

from typing import ClassVar

from tb_internet_use.toolcall.harnesses.base import HarnessToolCallConverter
from tb_internet_use.toolcall.model import ExecutionStatus
from tb_internet_use.toolcall.result_formats import (
    HarnessJsonResultFormat,
    HarnessResultFormatList,
    JsonCondition,
    JsonObject,
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


class MiniSweAgentConverter(HarnessToolCallConverter):
    json_formats: ClassVar = {"bash": _BASH}
