"""Reading groups of the trajectory analysis, the tasks each group is drawn from and the condition a trial meets to qualify for each group.

A trial can qualify for two groups, e.g. a solved trial whose request was not received, so the conditions here never look at other groups, and `pick_trials.py` draws each trial into one group only.
"""

import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

# `python -I` leaves the folder of this script off `sys.path`.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline_rows import (
    RequestRow,
    TrialFacts,
    is_confirmed_non_package_request,
    is_confirmed_request,
    is_unconfirmed_request,
)


class ReadingGroup(StrEnum):
    """Group of trials that get the same prompt parts and schema, in the order in which trials are drawn into them."""

    # Solved, with a confirmed request of a non-package category.
    REQUESTED_AND_SOLVED = "requested_and_solved"
    # Solved, without a request row of a category other than `package` and `connectivity_check` that may be internet use.
    SOLVED_WITHOUT = "solved_without"
    # A confirmed non-package request whose result view is `not_received`, in a task of `TASKS_READ`.
    NOT_RECEIVED_IN_READ_TASKS = "not_received_in_read_tasks"
    # Reward 0 with a confirmed request as `OTHER_TASK_DRAWS` gives, in a task where requests are common and solved trials rare, read to see how the requested content was used when the task was not solved.
    REQUESTED_AND_NOT_SOLVED = "requested_and_not_solved"
    # Solved, with an unconfirmed request and no confirmed one, in a task of `UNCONFIRMED_COMMAND_TASKS`.
    UNCONFIRMED_COMMAND = "unconfirmed_command"


@dataclass(frozen=True, slots=True)
class TaskShareExpectation:
    """Row of a task table that the task rules of `pick_trials.py` must give again, so that a changed run fails before trials are drawn."""

    task: str
    solved_trials: int
    # The solved trials that the rule of the table counts, e.g. those with a confirmed non-package request.
    counted_trials: int


# The tasks whose solved trials most often have a confirmed non-package request, in the order of that share.
TASKS_READ = (
    TaskShareExpectation("protein-autointerp-disulfide", 57, 57),
    TaskShareExpectation("hof-topology-interpenetration", 181, 105),
    TaskShareExpectation("fin-saccr-rwa", 210, 98),
    TaskShareExpectation("fp8-rmsnorm-gemm", 214, 75),
    TaskShareExpectation("music-harmony", 56, 16),
    TaskShareExpectation("gsea-proteomics", 67, 17),
    TaskShareExpectation("live-database-cutover", 136, 33),
    TaskShareExpectation("lake-temp-glm", 72, 17),
    TaskShareExpectation("ks-solver-cpp", 67, 13),
    TaskShareExpectation("formal-crypto", 145, 28),
)
# The tasks where more than half of the solved trials have an unconfirmed request and no confirmed one, in the order of that share.
UNCONFIRMED_COMMAND_TASKS = (
    TaskShareExpectation("takens-embedding-lean", 117, 117),
    TaskShareExpectation("react-lead-form", 160, 151),
    TaskShareExpectation("math-eval-grader", 101, 89),
    TaskShareExpectation("distributed-dedup", 150, 121),
)
# Harnesses whose trajectories miss some calls, so a trial of theirs without requests may hide one.
HARNESSES_THAT_MISS_CALLS = frozenset({"grok-build", "antigravity-cli", "copilot-cli"})
# The categories that a trial of `SOLVED_WITHOUT` may have rows of, since a package cache replaces the one and the other gets no content.
CATEGORIES_ALLOWED_WITHOUT_REQUESTS = frozenset({"package", "connectivity_check"})
HUGGING_FACE_HOST = "huggingface.co"


@dataclass(frozen=True, slots=True)
class OtherTaskDraw:
    """Task of `REQUESTED_AND_NOT_SOLVED`, i.e. one where requests are common and solved trials rare, with how many trials are drawn from it and whether its request must go to `HUGGING_FACE_HOST`."""

    task: str
    trial_count: int
    # True when the confirmed request must name `HUGGING_FACE_HOST`, false when any confirmed non-package request qualifies.
    needs_hugging_face_request: bool


OTHER_TASK_DRAWS = (
    OtherTaskDraw("vllm-deepseek-streaming", 3, needs_hugging_face_request=True),
    OtherTaskDraw("pretrain-shard-corruption", 3, needs_hugging_face_request=True),
    OtherTaskDraw("foodstuff-beta-activity", 2, needs_hugging_face_request=False),
    OtherTaskDraw("roy-polymorph-cn", 2, needs_hugging_face_request=False),
    OtherTaskDraw("medical-claims-processing", 2, needs_hugging_face_request=False),
)


def reading_groups_of(
    trial: TrialFacts, request_rows: list[RequestRow]
) -> list[ReadingGroup]:
    """List every reading group that a trial qualifies for, in the order of `ReadingGroup`."""
    if not trial.is_readable:
        return []
    groups: list[ReadingGroup] = []
    read_tasks = {expectation.task for expectation in TASKS_READ}
    if trial.task in read_tasks:
        if trial.is_solved and has_confirmed_non_package_request(request_rows):
            groups.append(ReadingGroup.REQUESTED_AND_SOLVED)
        if trial.is_solved and is_without_requests(trial, request_rows):
            groups.append(ReadingGroup.SOLVED_WITHOUT)
        if any(
            is_confirmed_non_package_request(row) and row.result_view == "not_received"
            for row in request_rows
        ):
            groups.append(ReadingGroup.NOT_RECEIVED_IN_READ_TASKS)
    if _qualifies_for_other_task_draw(trial, request_rows):
        groups.append(ReadingGroup.REQUESTED_AND_NOT_SOLVED)
    unconfirmed_command_tasks = {
        expectation.task for expectation in UNCONFIRMED_COMMAND_TASKS
    }
    if (
        trial.task in unconfirmed_command_tasks
        and trial.is_solved
        and has_only_unconfirmed_requests(request_rows)
    ):
        groups.append(ReadingGroup.UNCONFIRMED_COMMAND)
    return groups


def has_confirmed_non_package_request(request_rows: list[RequestRow]) -> bool:
    return any(is_confirmed_non_package_request(row) for row in request_rows)


def is_without_requests(trial: TrialFacts, request_rows: list[RequestRow]) -> bool:
    """Tell whether a trial of a harness that shows every call has no row of a category outside `CATEGORIES_ALLOWED_WITHOUT_REQUESTS` that may be internet use, whatever its reward."""
    return trial.harness not in HARNESSES_THAT_MISS_CALLS and not any(
        row.category not in CATEGORIES_ALLOWED_WITHOUT_REQUESTS
        and row.is_internet_use != "false"
        for row in request_rows
    )


def has_only_unconfirmed_requests(request_rows: list[RequestRow]) -> bool:
    """Tell whether a trial has an unconfirmed request and no confirmed one, of any category."""
    return any(is_unconfirmed_request(row) for row in request_rows) and not any(
        is_confirmed_request(row) for row in request_rows
    )


def _qualifies_for_other_task_draw(
    trial: TrialFacts, request_rows: list[RequestRow]
) -> bool:
    """Tell whether a trial with reward 0 has the confirmed request that its task of `OTHER_TASK_DRAWS` asks for."""
    draw = next((draw for draw in OTHER_TASK_DRAWS if draw.task == trial.task), None)
    if draw is None or trial.reward != 0.0:
        return False
    if draw.needs_hugging_face_request:
        return any(
            is_confirmed_request(row) and HUGGING_FACE_HOST in row.host_names.split()
            for row in request_rows
        )
    return has_confirmed_non_package_request(request_rows)
