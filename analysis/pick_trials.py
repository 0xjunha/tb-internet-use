"""Pick the trials of the trajectory analysis from the rows of a pipeline run, after checking that the task rules give the task tables again.

Tasks are picked by how much their solved trials request beyond packages, since a package cache replaces package requests and turning the internet off can lower the share of solved trials only in tasks whose solved trials use it. Each draw is random with a fixed seed, so the same run and seed give the same trials.

Run it as `uv run python -I analysis/pick_trials.py <pipeline_run_dir> <out_dir> --seed 0`.
"""

import argparse
import random
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

# `python -I` leaves the folder of this script off `sys.path`.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from output_files import write_csv
from pipeline_rows import (
    RequestRow,
    TrialFacts,
    is_confirmed_non_package_request,
    read_request_rows_by_trial,
    read_trial_facts,
)
from reading_groups import (
    OTHER_TASK_DRAWS,
    TASKS_READ,
    UNCONFIRMED_COMMAND_TASKS,
    ReadingGroup,
    TaskShareExpectation,
    has_confirmed_non_package_request,
    has_only_unconfirmed_requests,
    is_without_requests,
    reading_groups_of,
)

# A task is kept only with at least this many solved trials with a confirmed non-package request.
MINIMUM_REQUESTING_SOLVED_TRIALS = 10
# A task is kept only when at least this many pairs have such a trial, so that no task is picked for the habit of one pair.
MINIMUM_REQUESTING_PAIRS = 5
READ_TASK_COUNT = 10
# A task is one of `UNCONFIRMED_COMMAND_TASKS` when more than this share of its solved trials has only unconfirmed requests.
MINIMUM_UNCONFIRMED_ONLY_SHARE = 0.5
# Each task of `TASKS_READ` gets this many trials of `REQUESTED_AND_SOLVED`, each of another pair.
REQUESTED_AND_SOLVED_PER_TASK = 4
# Two pairs each give one trial of `REQUESTED_AND_SOLVED` and one of `SOLVED_WITHOUT`.
SAME_PAIR_COUNT = 2
# Each task of `UNCONFIRMED_COMMAND_TASKS` gets this many trials, of two harnesses.
UNCONFIRMED_COMMAND_PER_TASK = 2
# Trials of `REQUESTED_AND_SOLVED` are read by two readers who do not see each other.
READER_COUNT_OF_TWICE_READ_GROUP = 2

PICKED_TRIAL_COLUMNS = (
    "trial_id",
    "task",
    "harness",
    "model",
    "reward",
    "reading_group",
    "reader_count",
    "draw_step",
    "note",
)
NOTE_SUBSTITUTE = "reward 0 in place of a solved trial, since no solved trial qualifies"
NOTE_WITHOUT_STEP_CONDITION = "drawn without the extra condition of its step"
NOTE_EMPTY_SLOT = "empty slot, no trial left that qualifies"


class DrawStep(StrEnum):
    """Step of the draw order that picked a trial."""

    # One trial of each of the two groups from a pair that has candidates of both.
    SAME_PAIR = "same_pair"
    # A trial of a third pair whose confirmed non-package request left from the task environment.
    TASK_ENVIRONMENT_PAIR = "task_environment_pair"
    FURTHER_PAIR = "further_pair"
    NOT_RECEIVED = "not_received"
    # A draw among all candidates of the task, for a group whose draw has no steps.
    ANY_TRIAL = "any_trial"
    # The second trial of a task of `UNCONFIRMED_COMMAND`, of a harness other than the first.
    OTHER_HARNESS = "other_harness"


@dataclass(frozen=True, slots=True)
class TaskShare:
    """Counts of one task that the task rules order and keep tasks by."""

    task: str
    solved_trials: int
    # The solved trials that the rule counts, e.g. those with a confirmed non-package request.
    counted_trials: int
    # The pairs of the counted trials.
    counted_pairs: int = 0
    # Of the counted trials, those with a confirmed non-package request from the task environment.
    task_environment_trials: int = 0
    # Of the pairs of the counted trials, those that also have a solved trial without requests.
    pairs_also_without: int = 0
    # The hosts of the confirmed non-package requests of the counted trials, with the number of trials that ask each, most asked first.
    top_hosts: tuple[tuple[str, int], ...] = ()

    @property
    def share(self) -> float:
        return self.counted_trials / self.solved_trials


@dataclass(frozen=True, slots=True)
class PickedTrial:
    """Row of `picked_trials.csv`, one trial drawn into a reading group or an empty slot of one."""

    # Empty for an empty slot.
    trial_id: str
    task: str
    harness: str
    model: str
    reward: float | None
    reading_group: ReadingGroup
    reader_count: int
    draw_step: DrawStep
    note: str = ""


@dataclass(slots=True)
class _TaskDraw:
    """State of the draws of one task, shared by its steps so that no trial is drawn twice."""

    task: str
    candidates_by_group: dict[ReadingGroup, list[TrialFacts]]
    random_generator: random.Random
    picked_trials: list[PickedTrial] = field(default_factory=list)
    drawn_trial_ids: set[str] = field(default_factory=set)

    def remaining(self, reading_group: ReadingGroup) -> list[TrialFacts]:
        return [
            trial
            for trial in self.candidates_by_group.get(reading_group, [])
            if trial.trial_id not in self.drawn_trial_ids
        ]

    def remaining_of_unused_pairs(
        self, reading_group: ReadingGroup
    ) -> list[TrialFacts]:
        used_pairs = self.used_pairs(reading_group)
        return [
            trial
            for trial in self.remaining(reading_group)
            if trial.pair not in used_pairs
        ]

    def used_pairs(self, reading_group: ReadingGroup) -> set[tuple[str, str]]:
        return {
            (picked.harness, picked.model)
            for picked in self.picked_trials
            if picked.reading_group == reading_group and picked.trial_id
        }

    def draw(
        self,
        reading_group: ReadingGroup,
        draw_step: DrawStep,
        candidates: list[TrialFacts],
        *,
        fallback_candidates: list[TrialFacts] | None = None,
        note: str = "",
    ) -> PickedTrial:
        """Draw one of `candidates`, else one of `fallback_candidates` with a note that the step's condition was dropped, else record an empty slot."""
        if not candidates and fallback_candidates:
            candidates = fallback_candidates
            note = "; ".join(filter(None, [note, NOTE_WITHOUT_STEP_CONDITION]))
        reader_count = (
            READER_COUNT_OF_TWICE_READ_GROUP
            if reading_group == ReadingGroup.REQUESTED_AND_SOLVED
            else 1
        )
        if not candidates:
            picked = PickedTrial(
                "",
                self.task,
                "",
                "",
                None,
                reading_group,
                0,
                draw_step,
                NOTE_EMPTY_SLOT,
            )
        else:
            trial = self.random_generator.choice(
                sorted(candidates, key=lambda candidate: candidate.trial_id)
            )
            self.drawn_trial_ids.add(trial.trial_id)
            picked = PickedTrial(
                trial.trial_id,
                trial.task,
                trial.harness,
                trial.model,
                trial.reward,
                reading_group,
                reader_count,
                draw_step,
                note,
            )
        self.picked_trials.append(picked)
        return picked


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument(
        "pipeline_run_dir",
        type=Path,
        help="the output folder of a pipeline run, with trial_rows.csv and network_request_rows.csv",
    )
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--seed", type=int, default=0)
    arguments = parser.parse_args()

    trials = read_trial_facts(arguments.pipeline_run_dir / "trial_rows.csv")
    request_rows_by_trial = read_request_rows_by_trial(
        arguments.pipeline_run_dir / "network_request_rows.csv"
    )
    read_task_shares = count_read_task_shares(trials, request_rows_by_trial)
    unconfirmed_command_task_shares = count_unconfirmed_command_task_shares(
        trials, request_rows_by_trial
    )
    differences = differences_from_expectations(
        "tasks read", read_task_shares, TASKS_READ
    ) + differences_from_expectations(
        "unconfirmed command tasks",
        unconfirmed_command_task_shares,
        UNCONFIRMED_COMMAND_TASKS,
    )
    if differences:
        sys.exit(
            "the task rules do not give the task tables again\n"
            + "\n".join(differences)
        )
    _print_task_shares(read_task_shares, unconfirmed_command_task_shares)

    candidates = candidates_by_task_and_group(trials, request_rows_by_trial)
    solved_without_substitutes = solved_without_substitutes_by_task(
        trials, request_rows_by_trial, candidates
    )
    picked_trials = pick_trials(
        candidates,
        request_rows_by_trial,
        solved_without_substitutes=solved_without_substitutes,
        seed=arguments.seed,
    )
    arguments.out_dir.mkdir(parents=True, exist_ok=True)
    _write_picked_trials(arguments.out_dir / "picked_trials.csv", picked_trials)
    _write_qualifying_trial_counts(
        arguments.out_dir / "qualifying_trial_counts.csv", candidates
    )
    _print_counts(candidates, picked_trials)
    for task, substitutes in solved_without_substitutes.items():
        print(
            f"  {task} has no solved trial without requests, and {len(substitutes)} with reward 0 that meet the rest"
        )


def count_read_task_shares(
    trials: Sequence[TrialFacts], request_rows_by_trial: dict[str, list[RequestRow]]
) -> list[TaskShare]:
    """Give the tasks to read, i.e. of the tasks with enough solved trials with a confirmed non-package request and enough pairs that have one, those with the highest share of such trials."""
    solved_trials_by_task = _solved_readable_trials_by_task(trials)
    task_shares: list[TaskShare] = []
    for task, solved_trials in solved_trials_by_task.items():
        requesting_trials = [
            trial
            for trial in solved_trials
            if has_confirmed_non_package_request(
                request_rows_by_trial.get(trial.trial_id, [])
            )
        ]
        requesting_pairs = {trial.pair for trial in requesting_trials}
        pairs_without_requests = {
            trial.pair
            for trial in solved_trials
            if is_without_requests(trial, request_rows_by_trial.get(trial.trial_id, []))
        }
        host_counts = Counter(
            host_name
            for trial in requesting_trials
            for host_name in {
                name
                for row in request_rows_by_trial[trial.trial_id]
                if is_confirmed_non_package_request(row)
                for name in row.host_names.split()
            }
        )
        task_shares.append(
            TaskShare(
                task=task,
                solved_trials=len(solved_trials),
                counted_trials=len(requesting_trials),
                counted_pairs=len(requesting_pairs),
                task_environment_trials=sum(
                    _has_task_environment_request(request_rows_by_trial[trial.trial_id])
                    for trial in requesting_trials
                ),
                pairs_also_without=len(requesting_pairs & pairs_without_requests),
                top_hosts=tuple(
                    sorted(host_counts.items(), key=lambda item: (-item[1], item[0]))
                ),
            )
        )
    kept = [
        task_share
        for task_share in task_shares
        if task_share.counted_trials >= MINIMUM_REQUESTING_SOLVED_TRIALS
        and task_share.counted_pairs >= MINIMUM_REQUESTING_PAIRS
    ]
    return sorted(kept, key=lambda task_share: (-task_share.share, task_share.task))[
        :READ_TASK_COUNT
    ]


def count_unconfirmed_command_task_shares(
    trials: Sequence[TrialFacts], request_rows_by_trial: dict[str, list[RequestRow]]
) -> list[TaskShare]:
    """Give the tasks where more than half of the solved trials have an unconfirmed request and no confirmed one, highest share first."""
    task_shares = [
        TaskShare(
            task=task,
            solved_trials=len(solved_trials),
            counted_trials=sum(
                has_only_unconfirmed_requests(
                    request_rows_by_trial.get(trial.trial_id, [])
                )
                for trial in solved_trials
            ),
        )
        for task, solved_trials in _solved_readable_trials_by_task(trials).items()
    ]
    kept = [
        task_share
        for task_share in task_shares
        if task_share.share > MINIMUM_UNCONFIRMED_ONLY_SHARE
    ]
    return sorted(kept, key=lambda task_share: (-task_share.share, task_share.task))


def differences_from_expectations(
    table_name: str,
    task_shares: Sequence[TaskShare],
    expectations: Sequence[TaskShareExpectation],
) -> list[str]:
    """List each row where the computed tasks differ from a task table in task, order or counts, empty when they agree."""
    computed = [
        (share.task, share.solved_trials, share.counted_trials) for share in task_shares
    ]
    expected = [
        (expectation.task, expectation.solved_trials, expectation.counted_trials)
        for expectation in expectations
    ]
    if computed == expected:
        return []
    return [f"{table_name}, computed {computed}", f"{table_name}, expected {expected}"]


def candidates_by_task_and_group(
    trials: Sequence[TrialFacts], request_rows_by_trial: dict[str, list[RequestRow]]
) -> dict[str, dict[ReadingGroup, list[TrialFacts]]]:
    """Give the trials that qualify for each reading group, per task, with a trial in every group it qualifies for."""
    candidates: dict[str, dict[ReadingGroup, list[TrialFacts]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for trial in trials:
        for reading_group in reading_groups_of(
            trial, request_rows_by_trial.get(trial.trial_id, [])
        ):
            candidates[trial.task][reading_group].append(trial)
    return {task: dict(groups) for task, groups in candidates.items()}


def solved_without_substitutes_by_task(
    trials: Sequence[TrialFacts],
    request_rows_by_trial: dict[str, list[RequestRow]],
    candidates: dict[str, dict[ReadingGroup, list[TrialFacts]]],
) -> dict[str, list[TrialFacts]]:
    """Give, for each task of `TASKS_READ` without a candidate of `SOLVED_WITHOUT`, the trials with reward 0 that meet the rest of its condition.

    They are read in place of solved trials, only to see what an agent does in the task without the internet.
    """
    return {
        expectation.task: [
            trial
            for trial in trials
            if trial.task == expectation.task
            and trial.is_readable
            and trial.reward == 0.0
            and is_without_requests(
                trial, request_rows_by_trial.get(trial.trial_id, [])
            )
        ]
        for expectation in TASKS_READ
        if not candidates.get(expectation.task, {}).get(ReadingGroup.SOLVED_WITHOUT)
    }


def pick_trials(
    candidates: dict[str, dict[ReadingGroup, list[TrialFacts]]],
    request_rows_by_trial: dict[str, list[RequestRow]],
    *,
    solved_without_substitutes: dict[str, list[TrialFacts]],
    seed: int,
) -> list[PickedTrial]:
    """Draw the trials of every reading group, task by task in the order of the task tables, from one random generator seeded with `seed`.

    A task of `solved_without_substitutes` draws its trials of `SOLVED_WITHOUT` from those substitutes.
    """
    random_generator = random.Random(seed)
    picked_trials: list[PickedTrial] = []
    for expectation in TASKS_READ:
        task_candidates = dict(candidates.get(expectation.task, {}))
        if expectation.task in solved_without_substitutes:
            task_candidates[ReadingGroup.SOLVED_WITHOUT] = solved_without_substitutes[
                expectation.task
            ]
        picked_trials += _pick_read_task_trials(
            _TaskDraw(expectation.task, task_candidates, random_generator),
            request_rows_by_trial,
            solved_without_note=NOTE_SUBSTITUTE
            if expectation.task in solved_without_substitutes
            else "",
        )
    for other_task_draw in OTHER_TASK_DRAWS:
        task_draw = _TaskDraw(
            other_task_draw.task,
            candidates.get(other_task_draw.task, {}),
            random_generator,
        )
        for _ in range(other_task_draw.trial_count):
            group = ReadingGroup.REQUESTED_AND_NOT_SOLVED
            task_draw.draw(group, DrawStep.ANY_TRIAL, task_draw.remaining(group))
        picked_trials += task_draw.picked_trials
    for expectation in UNCONFIRMED_COMMAND_TASKS:
        picked_trials += _pick_unconfirmed_command_trials(
            _TaskDraw(
                expectation.task,
                candidates.get(expectation.task, {}),
                random_generator,
            )
        )
    return picked_trials


def _pick_read_task_trials(
    task_draw: _TaskDraw,
    request_rows_by_trial: dict[str, list[RequestRow]],
    *,
    solved_without_note: str,
) -> list[PickedTrial]:
    """Draw the trials of one task of `TASKS_READ` in the four steps of the draw order.

    1. Two pairs that have candidates of both `REQUESTED_AND_SOLVED` and `SOLVED_WITHOUT` each give one trial of each.
    2. A third pair gives a trial whose confirmed non-package request left from the task environment, unless a trial of step 1 has one.
    3. Further pairs give a trial each until `REQUESTED_AND_SOLVED` has four.
    4. One trial of `NOT_RECEIVED_IN_READ_TASKS`.

    A step without a candidate draws without its extra condition. The pairs of `REQUESTED_AND_SOLVED` always differ, so a slot that only a used pair could fill stays empty.
    """
    requested = ReadingGroup.REQUESTED_AND_SOLVED
    without = ReadingGroup.SOLVED_WITHOUT
    pairs_of_both = sorted(
        {trial.pair for trial in task_draw.remaining(requested)}
        & {trial.pair for trial in task_draw.remaining(without)}
    )
    same_pairs = task_draw.random_generator.sample(
        pairs_of_both, min(SAME_PAIR_COUNT, len(pairs_of_both))
    )
    for slot_index in range(SAME_PAIR_COUNT):
        if slot_index < len(same_pairs):
            pair = same_pairs[slot_index]
            task_draw.draw(
                requested,
                DrawStep.SAME_PAIR,
                [t for t in task_draw.remaining(requested) if t.pair == pair],
            )
            task_draw.draw(
                without,
                DrawStep.SAME_PAIR,
                [t for t in task_draw.remaining(without) if t.pair == pair],
                note=solved_without_note,
            )
            continue
        task_draw.draw(
            requested,
            DrawStep.SAME_PAIR,
            [],
            fallback_candidates=task_draw.remaining_of_unused_pairs(requested),
        )
        task_draw.draw(
            without,
            DrawStep.SAME_PAIR,
            [],
            fallback_candidates=task_draw.remaining(without),
            note=solved_without_note,
        )

    def has_task_environment_request(trial_id: str) -> bool:
        return _has_task_environment_request(request_rows_by_trial.get(trial_id, []))

    if not any(
        has_task_environment_request(picked.trial_id)
        for picked in task_draw.picked_trials
        if picked.reading_group == requested and picked.trial_id
    ):
        unused_pair_trials = task_draw.remaining_of_unused_pairs(requested)
        task_draw.draw(
            requested,
            DrawStep.TASK_ENVIRONMENT_PAIR,
            [t for t in unused_pair_trials if has_task_environment_request(t.trial_id)],
            fallback_candidates=unused_pair_trials,
        )
    while (
        sum(picked.reading_group == requested for picked in task_draw.picked_trials)
        < REQUESTED_AND_SOLVED_PER_TASK
    ):
        task_draw.draw(
            requested,
            DrawStep.FURTHER_PAIR,
            task_draw.remaining_of_unused_pairs(requested),
        )
    not_received = ReadingGroup.NOT_RECEIVED_IN_READ_TASKS
    task_draw.draw(
        not_received, DrawStep.NOT_RECEIVED, task_draw.remaining(not_received)
    )
    return task_draw.picked_trials


def _pick_unconfirmed_command_trials(task_draw: _TaskDraw) -> list[PickedTrial]:
    """Draw the trials of one task of `UNCONFIRMED_COMMAND_TASKS`, the second of a harness other than the first, or an empty slot when no other harness qualifies."""
    group = ReadingGroup.UNCONFIRMED_COMMAND
    task_draw.draw(group, DrawStep.ANY_TRIAL, task_draw.remaining(group))
    for _ in range(UNCONFIRMED_COMMAND_PER_TASK - 1):
        harnesses = {
            picked.harness for picked in task_draw.picked_trials if picked.trial_id
        }
        task_draw.draw(
            group,
            DrawStep.OTHER_HARNESS,
            [t for t in task_draw.remaining(group) if t.harness not in harnesses],
        )
    return task_draw.picked_trials


def _solved_readable_trials_by_task(
    trials: Sequence[TrialFacts],
) -> dict[str, list[TrialFacts]]:
    solved_trials_by_task: dict[str, list[TrialFacts]] = defaultdict(list)
    for trial in trials:
        if trial.is_solved and trial.is_readable:
            solved_trials_by_task[trial.task].append(trial)
    return solved_trials_by_task


def _has_task_environment_request(request_rows: list[RequestRow]) -> bool:
    return any(
        is_confirmed_non_package_request(row) and row.sender == "task_environment"
        for row in request_rows
    )


def _write_picked_trials(path: Path, picked_trials: Sequence[PickedTrial]) -> None:
    write_csv(
        path,
        PICKED_TRIAL_COLUMNS,
        (
            (
                picked.trial_id,
                picked.task,
                picked.harness,
                picked.model,
                "" if picked.reward is None else picked.reward,
                picked.reading_group,
                picked.reader_count,
                picked.draw_step,
                picked.note,
            )
            for picked in picked_trials
        ),
    )


def _write_qualifying_trial_counts(
    path: Path, candidates: dict[str, dict[ReadingGroup, list[TrialFacts]]]
) -> None:
    write_csv(
        path,
        ("reading_group", "task", "qualifying_trials"),
        (
            (reading_group, task, len(groups[reading_group]))
            for reading_group in ReadingGroup
            for task, groups in sorted(candidates.items())
            if groups.get(reading_group)
        ),
    )


def _print_task_shares(
    read_task_shares: Sequence[TaskShare],
    unconfirmed_command_task_shares: Sequence[TaskShare],
) -> None:
    print(
        "tasks read: task, solved, with a confirmed non-package request, of those from the task environment, pairs, pairs also without, top hosts"
    )
    for share in read_task_shares:
        hosts = " ".join(name for name, _ in share.top_hosts[:3])
        print(
            f"  {share.task} {share.solved_trials} {share.counted_trials} {share.task_environment_trials} {share.counted_pairs} {share.pairs_also_without} {hosts}"
        )
    print("unconfirmed command tasks: task, solved, with only unconfirmed requests")
    for share in unconfirmed_command_task_shares:
        print(f"  {share.task} {share.solved_trials} {share.counted_trials}")


def _print_counts(
    candidates: dict[str, dict[ReadingGroup, list[TrialFacts]]],
    picked_trials: Sequence[PickedTrial],
) -> None:
    print("reading group: qualifying trials, picked trials, empty slots")
    for reading_group in ReadingGroup:
        qualifying = sum(
            len(groups.get(reading_group, [])) for groups in candidates.values()
        )
        picked = [p for p in picked_trials if p.reading_group == reading_group]
        print(
            f"  {reading_group} {qualifying} {sum(bool(p.trial_id) for p in picked)} {sum(not p.trial_id for p in picked)}"
        )


if __name__ == "__main__":
    main()
