"""Test the prompt assembly and the report schemas of `analysis/reading_prompt.py` for every reading group, with made-up values and made-up reports."""

import dataclasses
from pathlib import Path

import jsonschema
import pytest
from analysis_modules import analysis_module
from made_up_reports import made_up_failed_request, made_up_request_group

pipeline_rows = analysis_module("pipeline_rows")
reading_groups = analysis_module("reading_groups")
reading_prompt = analysis_module("reading_prompt")

ReadingGroup = reading_groups.ReadingGroup
# The heading that starts each prompt part, by which a test tells the parts of a prompt.
PART_HEADINGS = {
    reading_prompt.GROUPS_PART: "REQUEST GROUPS.",
    reading_prompt.FAILED_PART: "FAILED REQUESTS.",
    reading_prompt.COMMANDS_PART: "UNCONFIRMED COMMANDS.",
    reading_prompt.ONLINE_RULE_PART: "ONLINE RULE.",
    reading_prompt.WITHOUT_PART: "WITHOUT REQUESTS.",
}
EXPECTED_HEADINGS = {
    ReadingGroup.REQUESTED_AND_SOLVED: {
        "REQUEST GROUPS.",
        "FAILED REQUESTS.",
        "ONLINE RULE.",
    },
    ReadingGroup.SOLVED_WITHOUT: {
        "REQUEST GROUPS.",
        "WITHOUT REQUESTS.",
        "ONLINE RULE.",
    },
    ReadingGroup.NOT_RECEIVED_IN_READ_TASKS: {"FAILED REQUESTS."},
    ReadingGroup.REQUESTED_AND_NOT_SOLVED: {"REQUEST GROUPS.", "FAILED REQUESTS."},
    ReadingGroup.UNCONFIRMED_COMMAND: {"UNCONFIRMED COMMANDS."},
}
COMMANDS = ["lake build", "npx"]
REQUEST_GROUP = made_up_request_group()
FAILED_REQUEST = made_up_failed_request()
GRADED_ANSWER_REACH = {
    "graded_answer_reach": "none",
    "graded_answer_reach_detail": "No graded part holds fetched content.",
}
ONLINE_RULE = {"treatment": "did_not_mention", "reason_given": "", "step_ids": []}
# A made-up report of each reading group that its schema allows.
REPORTS = {
    ReadingGroup.REQUESTED_AND_SOLVED: {
        "request_groups": [REQUEST_GROUP],
        **GRADED_ANSWER_REACH,
        "failed_requests": [FAILED_REQUEST],
        "online_rule": ONLINE_RULE,
        "request_rows_disputed": [],
        "notes": "",
    },
    ReadingGroup.SOLVED_WITHOUT: {
        "request_groups": [],
        **GRADED_ANSWER_REACH,
        "trial_without_requests": {
            "entries": [
                {
                    "host": "files.a.org",
                    "did_instead": "It derived the table from the files in /app.",
                    "step_ids": [3],
                    "content_origin": "files_in_container",
                }
            ],
            "considered_internet": "no_mention",
        },
        "online_rule": ONLINE_RULE,
        "request_rows_disputed": [],
        "notes": "",
    },
    ReadingGroup.NOT_RECEIVED_IN_READ_TASKS: {
        "failed_requests": [],
        "request_rows_disputed": [
            {
                "step_id": 4,
                "target": "https://a.org/x",
                "dispute": "never_sent",
                "reason": "The command before && failed.",
            }
        ],
        "notes": "",
    },
    ReadingGroup.REQUESTED_AND_NOT_SOLVED: {
        "request_groups": [REQUEST_GROUP],
        **GRADED_ANSWER_REACH,
        "failed_requests": [FAILED_REQUEST],
        "request_rows_disputed": [],
        "notes": "",
    },
    ReadingGroup.UNCONFIRMED_COMMAND: {
        "unconfirmed_commands": [
            {
                "command": "lake build",
                "step_ids": [21],
                "download_evidence": "output_shows_download",
                "what_was_downloaded": "mathlib",
                "evidence_quote": "Downloading mathlib",
                "evidence_step_ids": [22],
                "first_run_step_id": 21,
                "image_fetches_dependencies": "no",
                "image_evidence_quote": "",
            }
        ],
        "request_rows_disputed": [],
        "notes": "",
    },
}


def made_up_values():
    return reading_prompt.ReadingValues(
        task="task-a",
        harness="codex",
        model="model-a",
        reward="1.0",
        trial_out_dir=Path("/out/trials/t1"),
        task_dir=Path("/tasks/task-a"),
        work_dir=Path("/out/trials/t1/work_0"),
        unconfirmed_commands=(
            reading_prompt.UnconfirmedCommand("lake build", (21, 30)),
            reading_prompt.UnconfirmedCommand("npx", (4,)),
        ),
        fetched_hosts=(("files.a.org", 12), ("b.org", 3)),
        requesting_trial_count=20,
    )


@pytest.mark.parametrize("reading_group", list(ReadingGroup))
def test_a_prompt_holds_the_common_part_and_exactly_the_parts_of_its_reading_group(
    reading_group,
):
    prompt = reading_prompt.reading_prompt_of(reading_group, made_up_values())

    headings = {heading for heading in PART_HEADINGS.values() if heading in prompt}
    assert headings == EXPECTED_HEADINGS[reading_group]
    assert prompt.startswith("Read one Terminal-Bench 4.1 agent trajectory")
    assert not reading_prompt.PLACEHOLDER.search(prompt)


def test_a_prompt_names_the_trial_its_files_and_its_work_folder():
    prompt = reading_prompt.reading_prompt_of(
        ReadingGroup.SOLVED_WITHOUT, made_up_values()
    )

    assert "Trial: task task-a, harness codex, model model-a, reward 1.0." in prompt
    assert "kept in your work folder work_0 and run as" in prompt
    assert "Read no other work_ folder." in prompt
    assert (
        "Files in /out/trials/t1, which also holds your work folder:\n- requests.csv"
        in prompt
    )
    assert "- trajectory.json: the full ATIF JSON" in prompt
    assert "- /tasks/task-a: its statement, tests and solution" in prompt
    assert (
        "Other solved trials of this task fetched content from these hosts, each with how many of the 20 solved trials with a confirmed non-package request asked it: `files.a.org` (12), `b.org` (3). Give one entry"
        in prompt
    )


def test_the_commands_part_lists_each_command_with_the_steps_of_its_rows():
    prompt = reading_prompt.reading_prompt_of(
        ReadingGroup.UNCONFIRMED_COMMAND, made_up_values()
    )

    assert "`lake build` at steps 21, 30; `npx` at step 4, over all its runs." in prompt


def test_a_filled_value_that_looks_like_a_placeholder_stays_as_it_is():
    values = dataclasses.replace(made_up_values(), model="<task>")

    prompt = reading_prompt.reading_prompt_of(
        ReadingGroup.NOT_RECEIVED_IN_READ_TASKS, values
    )

    assert "model <task>, reward" in prompt


def test_unconfirmed_commands_are_the_made_by_of_upper_only_rows_in_order_of_their_first_row():
    def row(step_id, made_by, bound):
        return pipeline_rows.RequestRow(
            "t",
            "main",
            step_id,
            made_by,
            "",
            "",
            "package",
            "true",
            "task_environment",
            "unknown",
            bound,
        )

    request_rows = [
        row(3, "npx", "upper_only"),
        row(5, "pip install", "lower_and_upper"),
        row(7, "lake build", "upper_only"),
        row(7, "lake build", "upper_only"),
        row(9, "npx", "upper_only"),
    ]

    assert reading_prompt.unconfirmed_commands_of(request_rows) == (
        reading_prompt.UnconfirmedCommand("npx", (3, 9)),
        reading_prompt.UnconfirmedCommand("lake build", (7,)),
    )


@pytest.mark.parametrize("reading_group", list(ReadingGroup))
def test_each_schema_is_a_json_schema_that_takes_its_made_up_report_and_requires_every_key(
    reading_group,
):
    schema = reading_prompt.report_schema_of(reading_group, COMMANDS)
    report = REPORTS[reading_group]

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(report, schema)
    assert schema["type"] == "object"
    for key in report:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({k: v for k, v in report.items() if k != key}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**report, "extra": ""}, schema)


def test_schemas_refuse_a_nested_key_that_is_missing_or_added_and_a_value_outside_an_enum():
    schema = reading_prompt.report_schema_of(ReadingGroup.REQUESTED_AND_SOLVED, [])
    report = REPORTS[ReadingGroup.REQUESTED_AND_SOLVED]
    without_effects = {k: v for k, v in REQUEST_GROUP.items() if k != "effects"}
    for request_group in (
        without_effects,
        {**REQUEST_GROUP, "verdict": "fine"},
        {**REQUEST_GROUP, "prior_candidate": "maybe"},
        {**REQUEST_GROUP, "content_kinds": ["blog"]},
        made_up_request_group(steps=[(4, "half_received")]),
        made_up_request_group(effects=[{"effect": "entered_answer"}]),
    ):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({**report, "request_groups": [request_group]}, schema)


def test_the_command_of_an_entry_must_be_one_of_the_commands_of_the_trial():
    schema = reading_prompt.report_schema_of(ReadingGroup.UNCONFIRMED_COMMAND, ["npx"])

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(REPORTS[ReadingGroup.UNCONFIRMED_COMMAND], schema)
    with pytest.raises(ValueError):
        reading_prompt.report_schema_of(ReadingGroup.UNCONFIRMED_COMMAND, [])


@pytest.mark.parametrize("reading_group", list(ReadingGroup))
def test_the_prompt_explains_every_enum_value_of_its_schema(reading_group):
    prompt = reading_prompt.reading_prompt_of(reading_group, made_up_values())
    schema = reading_prompt.report_schema_of(reading_group, COMMANDS)
    # `command` lists the trial's commands, which the prompt names in its list.
    unexplained = set(COMMANDS)
    # `tests_grade_part` lists its values in one sentence, each in backticks.
    listed_inline = set(reading_prompt.TESTS_GRADE_PART)

    def enum_values_of(value):
        if isinstance(value, dict):
            yield from value.get("enum", [])
            for item in value.values():
                yield from enum_values_of(item)

    missing = [
        value
        for value in enum_values_of(schema)
        if value not in unexplained
        and f"- {value}" not in prompt
        and not (value in listed_inline and f"`{value}`" in prompt)
    ]
    assert missing == []


def test_the_without_part_of_a_trial_with_reward_0_speaks_of_solved_trials_and_its_work():
    solved = reading_prompt.reading_prompt_of(
        ReadingGroup.SOLVED_WITHOUT, made_up_values()
    )
    failed = reading_prompt.reading_prompt_of(
        ReadingGroup.SOLVED_WITHOUT, dataclasses.replace(made_up_values(), reward="0.0")
    )

    assert "WITHOUT REQUESTS. Other solved trials of this task fetched" in solved
    assert "where that content in its answer visibly" in solved
    assert "WITHOUT REQUESTS. Solved trials of this task fetched" in failed
    assert "where that content in its work visibly" in failed


def test_only_a_trial_with_subagent_trajectories_gets_the_sentence_on_their_steps():
    values = made_up_values()

    without = reading_prompt.reading_prompt_of(ReadingGroup.SOLVED_WITHOUT, values)
    with_subagents = reading_prompt.reading_prompt_of(
        ReadingGroup.SOLVED_WITHOUT,
        dataclasses.replace(values, has_subagent_trajectories=True),
    )

    assert reading_prompt.SUBAGENT_STEPS_SENTENCE not in without
    assert (
        "Give only step_ids of the agent's own trajectory. Steps under a `[[[ subagent trajectory` line"
        in with_subagents
    )


@pytest.mark.parametrize("reading_group", list(ReadingGroup))
def test_graded_answer_reach_is_asked_exactly_where_request_groups_are(reading_group):
    schema = reading_prompt.report_schema_of(reading_group, COMMANDS)
    prompt = reading_prompt.reading_prompt_of(reading_group, made_up_values())

    has_groups = "request_groups" in schema["properties"]
    assert ("graded_answer_reach" in schema["properties"]) == has_groups
    assert ("graded_answer_reach_detail" in schema["required"]) == has_groups
    assert ("graded_answer_reach:" in prompt) == has_groups


def test_the_groups_part_defines_candidates_effects_record_groups_and_late_output():
    for sentence in (
        "A hypothesis about the rule behind the answer or about where the data comes from is not a candidate and not an answer part.",
        "Give each answer part one effect per group.",
        "entered_answer: a submitted file holds it or was computed or written from it, and no earlier candidate for that part existed.",
        "Records of one kind fetched from one host are one group, together with the search or listing that returned their ids.",
        "When these sentences do not settle it, split.",
        "For a background command, answer `response` by the step that reads its output.",
    ):
        assert sentence in reading_prompt.GROUPS_PART, sentence


def test_reasons_before_a_request_come_in_the_order_in_which_the_first_that_fits_is_taken():
    assert reading_prompt.SHOWN_BEFORE_REQUEST == (
        "failed_step",
        "earlier_response_led_here",
        "agent_wants_to_check_own_answer",
        "agent_says_what_it_will_get",
        "task_statement_names_source",
        "no_reason_shown",
        "other",
    )
    positions = [
        reading_prompt.GROUPS_PART.index(f"- {value}")
        for value in reading_prompt.SHOWN_BEFORE_REQUEST
        if value != "other"
    ]
    assert positions == sorted(positions)
