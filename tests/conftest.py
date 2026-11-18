"""Fixtures shared by the tests that run the steps on made-up trial folders, i.e. those of pipeline.py and of the scripts that run it."""

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

# A made-up detail file of a Claude Code trial that a verifier gave the reward 1.0, as a dict to change before it is written.
_DETAIL_FILE_CONTENTS: dict[str, Any] = {
    "task_name": "terminal-bench/a",
    "agent_info": {
        "name": "claude-code",
        "version": "2.1.0",
        "model_info": {"name": "model-a"},
    },
    "verifier_result": {"rewards": {"reward": 1.0}},
}
_STATUS_FILE_CONTENTS = {"memberships": [{"version": "4-0-0", "row_id": "row-1"}]}


@pytest.fixture
def write_trial_folder() -> Callable[..., Path]:
    """Give a function that writes a made-up trial folder named `trial_id` under `raw_trials_dir` and returns it.

    `bash_calls` gives the Claude Code `Bash` calls of the trajectory, each as its command and the text of its result, one per step from step 1 on. Bytes are written as the trajectory file as they are, e.g. broken JSON, and None leaves the file out.
    `task_name` is the task of the detail file, and `has_detail_file=False` leaves that file out.
    """

    def write(
        raw_trials_dir: Path,
        trial_id: str,
        bash_calls: Sequence[tuple[str, str]] | bytes | None,
        *,
        task_name: str = "terminal-bench/a",
        has_detail_file: bool = True,
    ) -> Path:
        trial_dir = raw_trials_dir / trial_id
        trial_dir.mkdir(parents=True)
        if has_detail_file:
            (trial_dir / "detail.json").write_text(
                json.dumps({**_DETAIL_FILE_CONTENTS, "task_name": task_name})
            )
        (trial_dir / "status.json").write_text(json.dumps(_STATUS_FILE_CONTENTS))
        if isinstance(bash_calls, bytes):
            (trial_dir / "trajectory.json").write_bytes(bash_calls)
        elif bash_calls is not None:
            (trial_dir / "trajectory.json").write_text(
                json.dumps(_claude_code_trajectory_of(bash_calls))
            )
        return trial_dir

    return write


def _claude_code_trajectory_of(bash_calls: Sequence[tuple[str, str]]) -> dict[str, Any]:
    """Give a made-up Claude Code trajectory with one `Bash` call per step, each with its result text and no exit code line."""
    return {
        "schema_version": "ATIF-v1.7",
        "agent": {"name": "claude-code"},
        "steps": [
            {
                # Step ids are 1-based, as in the trajectories.
                "step_id": step_id,
                "tool_calls": [
                    {
                        "tool_call_id": f"call-{step_id}",
                        "function_name": "Bash",
                        "arguments": {"command": command},
                    }
                ],
                "observation": {
                    "results": [
                        {"source_call_id": f"call-{step_id}", "content": output}
                    ]
                },
            }
            for step_id, (command, output) in enumerate(bash_calls, start=1)
        ],
    }
