"""Test the task rules and the draw order of `analysis/pick_trials.py`, and the group conditions of `analysis/reading_groups.py`, on made-up trials and request rows."""

from collections import Counter

from analysis_modules import analysis_module

pipeline_rows = analysis_module("pipeline_rows")
reading_groups = analysis_module("reading_groups")
pick_trials = analysis_module("pick_trials")

ReadingGroup = reading_groups.ReadingGroup
DrawStep = pick_trials.DrawStep
READ_TASK = reading_groups.TASKS_READ[0].task
UNCONFIRMED_COMMAND_TASK = reading_groups.UNCONFIRMED_COMMAND_TASKS[0].task
HUGGING_FACE_TASK = reading_groups.OTHER_TASK_DRAWS[0].task


def made_up_trial(
    trial_id: str,
    task: str,
    pair: tuple[str, str] = ("claude-code", "model-a"),
    reward: float | None = 1.0,
):
    return pipeline_rows.TrialFacts(
        trial_id=trial_id,
        task=task,
        harness=pair[0],
        model=pair[1],
        reward=reward,
        is_readable=True,
    )


def made_up_row(
    trial_id: str,
    category: str = "content_fetch",
    *,
    is_internet_use: str = "true",
    request_measure_bound: str = "lower_and_upper",
    sender: str = "task_environment",
    result_view: str = "received",
    host_names: str = "a.org",
    step_id: int = 1,
    made_by: str = "curl",
):
    return pipeline_rows.RequestRow(
        trial_id=trial_id,
        trajectory_id="main",
        step_id=step_id,
        made_by=made_by,
        target="",
        host_names=host_names,
        category=category,
        is_internet_use=is_internet_use,
        sender=sender,
        result_view=result_view,
        request_measure_bound=request_measure_bound,
    )


def requesting_trials(task: str, count: int, pair_count: int, prefix: str):
    """Make `count` solved trials of `task`, each with a confirmed fetch, spread over `pair_count` pairs."""
    trials = [
        made_up_trial(f"{prefix}{index}", task, ("codex", f"m{index % pair_count}"))
        for index in range(count)
    ]
    return trials, {trial.trial_id: [made_up_row(trial.trial_id)] for trial in trials}


def test_read_tasks_need_ten_requesting_solved_trials_and_five_pairs_and_follow_their_share():
    trials, rows = [], {}
    for task, count, pair_count, without_count in (
        ("all", 10, 5, 0),
        ("half", 10, 5, 10),
        ("four_pairs", 10, 4, 0),
        ("nine_trials", 9, 9, 0),
    ):
        task_trials, task_rows = requesting_trials(task, count, pair_count, task)
        trials += task_trials + [
            made_up_trial(f"{task}-without{index}", task)
            for index in range(without_count)
        ]
        rows |= task_rows
    # Neither an unsolved nor an unreadable trial counts among the solved trials.
    trials.append(made_up_trial("half-failed", "half", reward=0.0))

    task_shares = pick_trials.count_read_task_shares(trials, rows)

    assert [
        (share.task, share.solved_trials, share.counted_trials) for share in task_shares
    ] == [
        ("all", 10, 10),
        ("half", 20, 10),
    ]
    # Ten trials without requests of one claude-code pair share no pair with the requesting codex trials.
    assert task_shares[1].pairs_also_without == 0


def test_a_package_or_unconfirmed_request_makes_no_requesting_trial():
    trials = [
        made_up_trial(f"t{index}", "a", ("codex", f"m{index}")) for index in range(10)
    ]
    rows = {
        "t0": [made_up_row("t0", "package")],
        "t1": [made_up_row("t1", request_measure_bound="upper_only")],
        "t2": [made_up_row("t2", "connectivity_check")],
    }

    assert pick_trials.count_read_task_shares(trials, rows) == []


def test_unconfirmed_command_tasks_need_more_than_half_of_the_solved_trials():
    trials = [
        made_up_trial(f"{task}{index}", task)
        for task in ("more", "half")
        for index in range(4)
    ]
    rows = {
        trial_id: [made_up_row(trial_id, "package", request_measure_bound="upper_only")]
        for trial_id in ("more0", "more1", "more2", "half0", "half1")
    }
    # A confirmed request beside the unconfirmed one leaves the trial out.
    rows["more2"].append(made_up_row("more2", "package"))
    rows["more3"] = [
        made_up_row("more3", "package", request_measure_bound="upper_only")
    ]

    task_shares = pick_trials.count_unconfirmed_command_task_shares(trials, rows)

    assert [(share.task, share.counted_trials) for share in task_shares] == [
        ("more", 3)
    ]


def test_differences_from_expectations_name_a_changed_order():
    expectation = reading_groups.TaskShareExpectation
    task_shares = [pick_trials.TaskShare("b", 10, 5), pick_trials.TaskShare("a", 10, 9)]

    assert (
        pick_trials.differences_from_expectations(
            "t", task_shares, [expectation("b", 10, 5), expectation("a", 10, 9)]
        )
        == []
    )
    assert pick_trials.differences_from_expectations(
        "t", task_shares, [expectation("a", 10, 9), expectation("b", 10, 5)]
    )


def test_solved_without_allows_package_and_connectivity_rows_and_rows_that_are_no_internet_use():
    trial = made_up_trial("t", READ_TASK)
    cases = [
        ([], True),
        ([made_up_row("t", "package"), made_up_row("t", "connectivity_check")], True),
        ([made_up_row("t", is_internet_use="false")], True),
        ([made_up_row("t", is_internet_use="")], False),
        ([made_up_row("t", "other_web", request_measure_bound="upper_only")], False),
    ]
    for request_rows, is_without in cases:
        assert (
            ReadingGroup.SOLVED_WITHOUT
            in reading_groups.reading_groups_of(trial, request_rows)
        ) == is_without, request_rows
    grok_trial = made_up_trial("g", READ_TASK, ("grok-build", "m"))
    assert reading_groups.reading_groups_of(grok_trial, []) == []


def test_a_trial_qualifies_for_every_group_whose_condition_it_meets():
    trial = made_up_trial("t", READ_TASK)
    request_rows = [made_up_row("t", result_view="not_received")]

    assert reading_groups.reading_groups_of(trial, request_rows) == [
        ReadingGroup.REQUESTED_AND_SOLVED,
        ReadingGroup.NOT_RECEIVED_IN_READ_TASKS,
    ]


def test_a_hugging_face_task_needs_a_confirmed_request_to_that_host_and_reward_0():
    failed = made_up_trial("t", HUGGING_FACE_TASK, reward=0.0)
    solved = made_up_trial("s", HUGGING_FACE_TASK)
    group = ReadingGroup.REQUESTED_AND_NOT_SOLVED

    assert reading_groups.reading_groups_of(
        failed, [made_up_row("t", "package", host_names="huggingface.co")]
    ) == [group]
    assert (
        reading_groups.reading_groups_of(failed, [made_up_row("t", host_names="a.org")])
        == []
    )
    assert (
        reading_groups.reading_groups_of(
            solved, [made_up_row("s", host_names="huggingface.co")]
        )
        == []
    )


def draw_read_task(trials, rows, *, seed: int = 0):
    candidates = pick_trials.candidates_by_task_and_group(trials, rows)
    substitutes = pick_trials.solved_without_substitutes_by_task(
        trials, rows, candidates
    )
    picked = pick_trials.pick_trials(
        candidates, rows, solved_without_substitutes=substitutes, seed=seed
    )
    return [picked_trial for picked_trial in picked if picked_trial.task == READ_TASK]


def read_task_trials():
    """Make a task where pairs p1 and p2 have trials of both groups, only p3 asks from the task environment and p4 and p5 have one requesting trial each.

    The requests of p1 and p2 go through a harness tool. Trial p5-0 was not received, and so was `failed` of pair p6 with reward 0.
    """
    trials, rows = [], {}
    for pair_name, requesting, without in (
        ("p1", 3, 2),
        ("p2", 3, 2),
        ("p3", 2, 0),
        ("p4", 1, 0),
        ("p5", 1, 0),
    ):
        pair = ("codex", pair_name)
        for index in range(requesting):
            trial_id = f"{pair_name}-{index}"
            trials.append(made_up_trial(trial_id, READ_TASK, pair))
            sender = "task_environment" if pair_name == "p3" else "harness_process"
            result_view = "not_received" if trial_id == "p5-0" else "received"
            rows[trial_id] = [
                made_up_row(trial_id, sender=sender, result_view=result_view)
            ]
        trials += [
            made_up_trial(f"{pair_name}-w{index}", READ_TASK, pair)
            for index in range(without)
        ]
    trials.append(made_up_trial("failed", READ_TASK, ("codex", "p6"), reward=0.0))
    rows["failed"] = [made_up_row("failed", result_view="not_received")]
    return trials, rows


def test_the_draw_takes_two_same_pairs_then_a_task_environment_pair_then_a_further_pair():
    trials, rows = read_task_trials()

    picked = draw_read_task(trials, rows)

    steps = [(p.reading_group, p.draw_step) for p in picked]
    assert steps == [
        (ReadingGroup.REQUESTED_AND_SOLVED, DrawStep.SAME_PAIR),
        (ReadingGroup.SOLVED_WITHOUT, DrawStep.SAME_PAIR),
        (ReadingGroup.REQUESTED_AND_SOLVED, DrawStep.SAME_PAIR),
        (ReadingGroup.SOLVED_WITHOUT, DrawStep.SAME_PAIR),
        (ReadingGroup.REQUESTED_AND_SOLVED, DrawStep.TASK_ENVIRONMENT_PAIR),
        (ReadingGroup.REQUESTED_AND_SOLVED, DrawStep.FURTHER_PAIR),
        (ReadingGroup.NOT_RECEIVED_IN_READ_TASKS, DrawStep.NOT_RECEIVED),
    ]
    assert {picked[0].model, picked[2].model} == {"p1", "p2"}
    assert [picked[1].model, picked[3].model] == [picked[0].model, picked[2].model]
    assert picked[4].model == "p3"
    requested = [
        p for p in picked if p.reading_group == ReadingGroup.REQUESTED_AND_SOLVED
    ]
    assert len({p.model for p in requested}) == 4
    assert {p.reader_count for p in requested} == {2}
    assert (picked[6].trial_id, picked[6].reader_count) in {("failed", 1), ("p5-0", 1)}


def test_a_trial_drawn_into_an_earlier_group_is_not_drawn_again_and_its_slot_stays_empty():
    trials, rows = read_task_trials()
    # Only p5 is left for the further pair, so its only not received trial is drawn as requested and solved.
    trials = [trial for trial in trials if trial.model not in ("p4", "p6")]

    picked = draw_read_task(trials, rows)

    assert picked[5].trial_id == "p5-0"
    assert (picked[6].trial_id, picked[6].note) == ("", pick_trials.NOTE_EMPTY_SLOT)


def test_the_same_seed_gives_the_same_trials_and_another_seed_may_not():
    trials, rows = read_task_trials()

    ids_by_seed = {
        seed: [p.trial_id for p in draw_read_task(trials, rows, seed=seed)]
        for seed in range(5)
    }

    assert ids_by_seed[0] == [p.trial_id for p in draw_read_task(trials, rows, seed=0)]
    assert len({tuple(ids) for ids in ids_by_seed.values()}) > 1


def test_without_a_pair_of_both_groups_the_first_step_draws_without_its_condition():
    trials, rows = read_task_trials()
    # p1 keeps its trials without requests and loses those with, so no pair has both.
    trials = [
        t
        for t in trials
        if t.model not in ("p2",) and t.trial_id not in ("p1-0", "p1-1", "p1-2")
    ]

    picked = draw_read_task(trials, rows)

    first_step = [p for p in picked if p.draw_step == DrawStep.SAME_PAIR]
    assert all(p.note == pick_trials.NOTE_WITHOUT_STEP_CONDITION for p in first_step)
    assert Counter(p.reading_group for p in first_step if p.trial_id) == {
        ReadingGroup.REQUESTED_AND_SOLVED: 2,
        ReadingGroup.SOLVED_WITHOUT: 2,
    }


def test_a_task_without_solved_trials_without_requests_reads_trials_with_reward_0_instead():
    trials, rows = read_task_trials()
    trials = [t for t in trials if "-w" not in t.trial_id]
    trials += [made_up_trial("p1-failed", READ_TASK, ("codex", "p1"), reward=0.0)]

    picked = draw_read_task(trials, rows)

    without = [p for p in picked if p.reading_group == ReadingGroup.SOLVED_WITHOUT]
    assert [(p.trial_id, p.note) for p in without] == [
        ("p1-failed", pick_trials.NOTE_SUBSTITUTE),
        ("", pick_trials.NOTE_EMPTY_SLOT),
    ]


def test_the_second_unconfirmed_command_trial_is_of_another_harness_or_an_empty_slot():
    for harnesses, expected_slots in (
        (("codex", "codex", "muse-code"), 2),
        (("codex", "codex"), 1),
    ):
        trials = [
            made_up_trial(f"t{index}", UNCONFIRMED_COMMAND_TASK, (harness, "m"))
            for index, harness in enumerate(harnesses)
        ]
        rows = {
            t.trial_id: [
                made_up_row(t.trial_id, "package", request_measure_bound="upper_only")
            ]
            for t in trials
        }
        candidates = pick_trials.candidates_by_task_and_group(trials, rows)

        picked = [
            p
            for p in pick_trials.pick_trials(
                candidates, rows, solved_without_substitutes={}, seed=0
            )
            if p.task == UNCONFIRMED_COMMAND_TASK
        ]

        assert [p.draw_step for p in picked] == [
            DrawStep.ANY_TRIAL,
            DrawStep.OTHER_HARNESS,
        ]
        assert len({p.harness for p in picked if p.trial_id}) == expected_slots
