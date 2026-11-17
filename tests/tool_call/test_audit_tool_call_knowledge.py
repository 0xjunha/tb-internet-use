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
    use_counts = Counter(
        {
            "treat_negative_exit_code_as_killed": 5,
            "treat_web_fetch_text_as_finished": 7,
        }
    )
    trial_counts = Counter(
        {
            "treat_negative_exit_code_as_killed": 2,
            "treat_web_fetch_text_as_finished": 3,
        }
    )

    rows = list(audit.judgment_rule_rows(use_counts, trial_counts))

    assert rows[:2] == [
        ("treat_web_fetch_text_as_finished", 7, 3),
        ("treat_negative_exit_code_as_killed", 5, 2),
    ]
    # Every other rule follows with 0, by name.
    unused_names = [name for name, _, _ in rows[2:]]
    assert rows[2:] == [(name, 0, 0) for name in sorted(unused_names)]
    assert "treat_wait_on_several_tasks_as_their_shared_status" in unused_names
