"""Tests for the judgment rule rows of scripts/audit_tool_call_knowledge.py, with made-up counts."""

import importlib.util
import sys
from collections import Counter
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "audit_tool_call_knowledge",
    Path(__file__).parents[2] / "scripts/audit_tool_call_knowledge.py",
)
assert _SPEC is not None and _SPEC.loader is not None
audit = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = audit  # dataclasses look the module up while it loads
_SPEC.loader.exec_module(audit)


def test_judgment_rule_rows_list_every_rule_with_the_most_used_first_and_0_for_unused():
    use_counts = Counter({"treat_negative_exit_code_as_killed": 5})
    trial_counts = Counter({"treat_negative_exit_code_as_killed": 2})

    rows = list(audit.judgment_rule_rows(use_counts, trial_counts))

    assert rows == [
        ("treat_negative_exit_code_as_killed", 5, 2),
        ("treat_exit_code_130_after_ctrl_c_as_killed", 0, 0),
        ("treat_wait_on_several_tasks_as_their_shared_status", 0, 0),
    ]
