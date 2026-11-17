"""Fixtures shared by the tests of the trial package."""

from typing import Any

import pytest


@pytest.fixture
def detail_file_contents() -> dict[str, Any]:
    """Give the contents of a made-up detail file of a trial that a verifier gave the reward 1.0, as a dict that a test may change before it writes it as JSON."""
    return {
        "task_name": "terminal-bench/fix-git",
        "agent_info": {
            "name": "claude-code",
            "version": "2.1.0",
            "model_info": {"name": "model-a"},
        },
        "verifier_result": {"rewards": {"reward": 1.0}},
        "exception_info": None,
    }


@pytest.fixture
def status_file_contents() -> dict[str, Any]:
    """Give the contents of a made-up status file of a trial of the leaderboard row `row-1` of the benchmark version `4-0-0`, as a dict that a test may change."""
    return {"memberships": [{"version": "4-0-0", "row_id": "row-1"}]}
