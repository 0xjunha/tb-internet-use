"""Tests for the bookkeeping of scripts/audit_results.py, with made-up calls."""

import importlib.util
import sys
from collections import Counter
from dataclasses import fields
from pathlib import Path

from tb_internet_use.toolcall.model import (
    ExecutionHandle,
    ExecutionHandleKind,
    HarnessTool,
    PollAction,
    RawToolCall,
    ReadFileAction,
    RunCommandAction,
    ToolCall,
    ToolCallKey,
    ToolCallOutput,
)

_SPEC = importlib.util.spec_from_file_location(
    "audit_results", Path(__file__).parents[2] / "scripts/audit_results.py"
)
assert _SPEC is not None and _SPEC.loader is not None
audit = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = audit  # dataclasses look the module up while it loads
_SPEC.loader.exec_module(audit)

KEY = ("h", "t", "f")


def test_merge_adds_every_count_and_caps_the_examples():
    first, second = audit.Tally(), audit.Tally()
    counters = [f.name for f in fields(audit.Tally) if f.name != "examples"]
    for name in counters:
        getattr(first, name)[KEY] = 1
        getattr(second, name)[KEY] = 2
    first.examples[KEY] = ["a", "b"]
    second.examples[KEY] = ["c", "d"]
    first.merge(second)
    for name in counters:
        assert getattr(first, name) == Counter({KEY: 3}), name
    assert first.examples[KEY] == ["a", "b", "c"]


def test_row_sums_hits_over_parts_and_multi_matches_wherever_the_format_is():
    tally = audit.Tally()
    tally.harness_text_hits[(*KEY, "part a")] = 2
    tally.harness_text_hits[(*KEY, "part b")] = 1
    tally.multi[("h", "t", "f > g")] = 5
    tally.multi[("h", "t", "e > f")] = 1
    tally.multi[("h", "t", "ff > g")] = 7  # a longer name that holds "f"
    row = audit._row(tally, KEY, "text")
    assert (row["harness_text_hits"], row["multi_match"]) == ("3", "6")


def _call(action, output: ToolCallOutput | None, index: int) -> ToolCall:
    raw = RawToolCall(
        ToolCallKey("t", "main", 1, index), HarnessTool("h", "x"), "id", {}, {}
    )
    return ToolCall(raw, action, output)


def test_links_count_polls_of_earlier_handles_and_later_reads_of_output_files():
    handle = ExecutionHandle(ExecutionHandleKind.COMMAND, "s1")
    other = ExecutionHandle(ExecutionHandleKind.COMMAND, "s9")
    calls = [
        _call(RunCommandAction("x"), ToolCallOutput(handles=(handle,)), 0),
        _call(PollAction((handle,)), ToolCallOutput(output_path="/o"), 1),
        # its own result naming the handle does not count as issued earlier
        _call(PollAction((other,)), ToolCallOutput(handles=(other,)), 2),
        _call(ReadFileAction("/o"), ToolCallOutput(output_path="/p"), 3),
        _call(RunCommandAction("cat /p"), ToolCallOutput(output_path="/q"), 4),
    ]
    tally = audit.Tally()
    audit.audit_links(tally, calls)
    assert tally.cross == Counter(
        {
            ("h", "x", "polled_handle", "issued_earlier"): 1,
            ("h", "x", "polled_handle", "not_issued"): 1,
            ("h", "x", "output_path", "read_later"): 1,
            ("h", "x", "output_path", "used_in_command_later"): 1,
            ("h", "x", "output_path", "not_read_later"): 1,
        }
    )
