"""List the steps of an ATIF trajectory and of the subagent trajectories inside it, for the dump that a reader gets and for the check of the step ids in a report.

Muse Code keeps the calls of a subagent in `subagent_trajectories`, each with its own step ids from 1, while Claude Code marks a step of a subagent with `is_sidechain` in its `extra`.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

MAIN_TRAJECTORY_ID = "main"


@dataclass(frozen=True, slots=True)
class TrajectoryStep:
    """One step of a trajectory file, with the trajectory it belongs to."""

    # `MAIN_TRAJECTORY_ID` for the agent, or the `trajectory_id` of a subagent trajectory.
    trajectory_id: str
    # The step as the JSON of the file holds it.
    step: dict[str, Any]

    @property
    def is_sidechain(self) -> bool | None:
        """Give the `is_sidechain` flag of the step's `extra`, None when the step has none."""
        extra = self.step.get("extra")
        if isinstance(extra, dict) and isinstance(extra.get("is_sidechain"), bool):
            return extra["is_sidechain"]
        return None


def trajectory_steps_of(trajectory: dict[str, Any]) -> list[TrajectoryStep]:
    """List the steps of the agent in file order, then those of each subagent trajectory in file order, also of one nested in another."""
    return list(_steps_of(trajectory, MAIN_TRAJECTORY_ID))


def _steps_of(
    trajectory: dict[str, Any], trajectory_id: str
) -> Iterator[TrajectoryStep]:
    for step in trajectory.get("steps") or []:
        if isinstance(step, dict):
            yield TrajectoryStep(trajectory_id, step)
    for subagent_trajectory in trajectory.get("subagent_trajectories") or []:
        if isinstance(subagent_trajectory, dict):
            yield from _steps_of(
                subagent_trajectory,
                str(subagent_trajectory.get("trajectory_id", "unnamed subagent")),
            )


def main_step_ids_of(trajectory_steps: list[TrajectoryStep]) -> set[int]:
    """Give the integer step ids of the agent's own trajectory, the only ones that the step id keys of a report hold, since those of a subagent trajectory count from 1 again."""
    return {
        trajectory_step.step["step_id"]
        for trajectory_step in trajectory_steps
        if trajectory_step.trajectory_id == MAIN_TRAJECTORY_ID
        and isinstance(trajectory_step.step.get("step_id"), int)
    }
