"""Test each flag of `analysis/check_reports.py` and the facts it derives from step ids, on made-up reports, request rows and trajectory steps."""

import dataclasses

import pytest
from analysis_modules import analysis_module
from made_up_reports import (
    made_up_effect,
    made_up_failed_request,
    made_up_request_group,
)

check_reports = analysis_module("check_reports")
pipeline_rows = analysis_module("pipeline_rows")
reading_groups = analysis_module("reading_groups")
trajectory_steps = analysis_module("trajectory_steps")

ReadingGroup = reading_groups.ReadingGroup
Flag = check_reports.ReportFlagKind
STEP_IDS = set(range(1, 21))
# The text of every made-up step, which holds the quotes of the made-up reports.
STEP_TEXT = "The agent said:  only\n docs. I need the structure. " + "word " * 30
REQUEST_GROUP = made_up_request_group()
ONLINE_RULE = {
    "treatment": "limited_itself",
    "reason_given": "only docs",
    "step_ids": [2],
}


def flags_of(
    report,
    reading_group=ReadingGroup.REQUESTED_AND_SOLVED,
    commands=(),
    *,
    listed_hosts=(),
    request_rows=(),
):
    context = check_reports.ReadingContext(
        reading_group,
        [
            trajectory_steps.TrajectoryStep(
                "main", {"step_id": step_id, "message": STEP_TEXT}
            )
            for step_id in STEP_IDS
        ],
        request_rows,
        listed_hosts,
        commands
        if isinstance(commands, dict)
        else {command: [3] for command in commands},
    )
    return [
        (flag.flag, flag.where)
        for flag in check_reports.flags_of_report(report, context)
    ]


def report_with_group(**group_fields):
    return {
        "request_groups": [made_up_request_group(**group_fields)],
        "failed_requests": [],
        "online_rule": ONLINE_RULE,
        "request_rows_disputed": [],
        "notes": "",
    }


def test_a_report_that_keeps_every_rule_has_no_flag():
    assert flags_of(report_with_group()) == []


@pytest.mark.parametrize(
    ("group_fields", "expected"),
    [
        (
            {"request_steps": [], "effects": [made_up_effect("none_shown")]},
            (Flag.EMPTY_REQUEST_STEPS, "request_groups[0].request_steps"),
        ),
        (
            {"content_kinds": []},
            (Flag.EMPTY_CONTENT_KINDS, "request_groups[0].content_kinds"),
        ),
        ({"effects": []}, (Flag.EMPTY_EFFECTS, "request_groups[0].effects")),
        (
            {
                "effects": [
                    made_up_effect("none_shown"),
                    made_up_effect("decided_later_request_or_plan"),
                ]
            },
            (Flag.NONE_SHOWN_BESIDE_OTHER_EFFECT, "request_groups[0].effects"),
        ),
        (
            {
                "shown_before_request": "failed_step",
                "shown_before_request_step_ids": [],
                "shown_before_request_detail": "",
            },
            (
                Flag.FAILED_STEP_WITHOUT_CITED_STEP,
                "request_groups[0].shown_before_request_step_ids",
            ),
        ),
        (
            {"prior_candidate": "other"},
            (
                Flag.OTHER_WITHOUT_EXPLANATION,
                "request_groups[0].prior_candidate",
            ),
        ),
        (
            {"content_kinds": ["other"], "use_detail": ""},
            (Flag.OTHER_WITHOUT_EXPLANATION, "request_groups[0].content_kinds"),
        ),
        (
            {"effects": [made_up_effect("other", detail="")]},
            (Flag.OTHER_WITHOUT_EXPLANATION, "request_groups[0].effects[0].effect"),
        ),
        (
            {
                "request_steps": [
                    {"step_id": 4, "response": "other", "response_other": ""}
                ],
                "effects": [made_up_effect("none_shown")],
            },
            (
                Flag.OTHER_WITHOUT_EXPLANATION,
                "request_groups[0].request_steps[0].response",
            ),
        ),
        (
            {
                "request_steps": [
                    {"step_id": 4, "response": "nothing", "response_other": ""}
                ]
            },
            (
                Flag.ANSWER_EFFECT_WITHOUT_RECEIVED_CONTENT,
                "request_groups[0].effects[0]",
            ),
        ),
        (
            {"effects": [made_up_effect("none_shown", answer_part="x")]},
            (
                Flag.ANSWER_PART_FOR_NONE_SHOWN,
                "request_groups[0].effects[0].answer_part",
            ),
        ),
        (
            {"effects": [made_up_effect("entered_answer", answer_part=" ")]},
            (
                Flag.NO_ANSWER_PART_FOR_ANSWER_EFFECT,
                "request_groups[0].effects[0].answer_part",
            ),
        ),
        (
            {"prior_candidate_step_ids": [99]},
            (Flag.UNKNOWN_STEP_ID, "request_groups[0].prior_candidate_step_ids"),
        ),
        (
            {"shown_before_request_detail": "I lack nothing"},
            (
                Flag.QUOTE_NOT_IN_CITED_STEPS,
                "request_groups[0].shown_before_request_detail",
            ),
        ),
    ],
)
def test_each_rule_of_a_request_group_has_its_flag(group_fields, expected):
    assert flags_of(report_with_group(**group_fields)) == [expected]


def test_a_kept_or_changed_candidate_with_a_prior_candidate_and_no_effect_need_no_flag():
    for effects in (
        [made_up_effect("existing_candidate_changed", answer_part="x")],
        [made_up_effect("none_shown")],
        [made_up_effect("decided_later_request_or_plan")],
    ):
        report = report_with_group(prior_candidate="in_file_or_output", effects=effects)

        assert flags_of(report) == []


def test_a_step_in_two_groups_is_no_fault_since_one_step_can_hold_several_calls():
    report = report_with_group()
    report["request_groups"].append(
        made_up_request_group(steps=[(5, "wanted_content"), (8, "nothing")])
    )

    assert flags_of(report) == []


def test_a_step_id_outside_the_trajectory_is_flagged_in_every_part():
    report = {
        "failed_requests": [
            {
                "step_ids": [0],
                "hosts": ["a.org"],
                "failure_shown": "timeout",
                "next_action": "retried_same",
                "next_action_step_ids": [21],
                "content_obtained_later": "no",
            }
        ],
        "notes": "",
    }

    assert flags_of(report, ReadingGroup.NOT_RECEIVED_IN_READ_TASKS) == [
        (Flag.UNKNOWN_STEP_ID, "failed_requests[0].step_ids"),
        (Flag.UNKNOWN_STEP_ID, "failed_requests[0].next_action_step_ids"),
    ]


def test_a_quote_of_fifteen_words_and_notes_of_more_than_150_words_are_too_long():
    report = report_with_group()
    report["online_rule"] = {**ONLINE_RULE, "reason_given": " ".join(["word"] * 15)}
    report["notes"] = " ".join(["word"] * 151)

    assert flags_of(report) == [
        (Flag.QUOTE_TOO_LONG, "online_rule.reason_given"),
        (Flag.NOTES_TOO_LONG, "notes"),
    ]
    report["online_rule"]["reason_given"] = " ".join(["word"] * 14)
    report["notes"] = " ".join(["word"] * 150)
    assert flags_of(report) == []


def test_a_listed_command_without_an_entry_and_a_long_evidence_quote_are_flagged():
    report = {
        "unconfirmed_commands": [
            {
                "command": "npx",
                "step_ids": [3],
                "download_evidence": "output_filtered_or_not_shown",
                "what_was_downloaded": "",
                "evidence_quote": " ".join(["word"] * 20),
                "first_run_step_id": 3,
                "image_fetches_dependencies": "cannot_tell",
                "image_evidence_quote": "",
            }
        ],
        "notes": "",
    }

    assert flags_of(
        report, ReadingGroup.UNCONFIRMED_COMMAND, ["lake build", "npx"]
    ) == [
        (Flag.QUOTE_TOO_LONG, "unconfirmed_commands[0].evidence_quote"),
        (Flag.COMMAND_WITHOUT_ENTRY, "unconfirmed_commands"),
    ]


def without_report(*hosts):
    return {
        "request_groups": [],
        "trial_without_requests": {
            "entries": [
                {
                    "host": host,
                    "did_instead": "",
                    "step_ids": [],
                    "content_origin": "cannot_tell",
                }
                for host in hosts
            ],
            "considered_internet": "no_mention",
        },
        "online_rule": ONLINE_RULE,
        "request_rows_disputed": [],
        "notes": "",
    }


def test_a_solved_without_trial_with_a_request_group_is_flagged_for_a_person():
    report = without_report("a.org")
    report["request_groups"] = [REQUEST_GROUP]

    assert flags_of(report, ReadingGroup.SOLVED_WITHOUT, listed_hosts=["a.org"]) == [
        (Flag.REQUEST_GROUP_IN_SOLVED_WITHOUT, "request_groups")
    ]


def test_without_entries_must_be_those_of_the_listed_hosts():
    report = without_report("a.org", "c.org")

    assert flags_of(
        report, ReadingGroup.SOLVED_WITHOUT, listed_hosts=["a.org", "b.org"]
    ) == [
        (Flag.WITHOUT_ENTRY_OF_UNLISTED_HOST, "trial_without_requests.entries[1].host"),
        (Flag.LISTED_HOST_WITHOUT_ENTRY, "trial_without_requests.entries"),
    ]


def request_row(
    step_id,
    category="content_fetch",
    sender="task_environment",
    *,
    is_internet_use="true",
    trajectory_id="main",
    result_view="received",
    request_measure_bound="lower_and_upper",
):
    return pipeline_rows.RequestRow(
        trial_id="t",
        trajectory_id=trajectory_id,
        step_id=step_id,
        made_by="curl",
        target=f"https://a.org/{step_id}",
        host_names="a.org",
        category=category,
        is_internet_use=is_internet_use,
        sender=sender,
        result_view=result_view,
        request_measure_bound=request_measure_bound,
    )


def main_step(step_id, is_sidechain):
    extra = {} if is_sidechain is None else {"is_sidechain": is_sidechain}
    return trajectory_steps.TrajectoryStep("main", {"step_id": step_id, "extra": extra})


def test_derived_facts_give_the_steps_subagent_and_senders_of_a_group_and_the_rows_no_group_names():
    report = {
        "request_groups": [
            made_up_request_group(
                steps=[(7, "nothing"), (4, "wanted_content"), (5, "nothing")]
            ),
            made_up_request_group(steps=[(8, "wanted_content")]),
        ],
        "request_rows_disputed": [
            {
                "step_id": 12,
                "target": "https://a.org/12",
                "dispute": "never_sent",
                "reason": "",
            }
        ],
    }
    request_rows = [
        request_row(4),
        request_row(5, sender="harness_process"),
        request_row(6, "search"),
        request_row(9, "package"),
        request_row(8),
        # A request to a local host and a row of a subagent trajectory, whose step ids are not those of the report.
        request_row(10, is_internet_use="false"),
        request_row(7, trajectory_id="sub-1"),
        # A row that the reader disputes.
        request_row(12),
    ]
    steps = [
        main_step(4, True),
        main_step(5, False),
        main_step(7, None),
        main_step(8, None),
    ]

    facts = check_reports.derived_facts_of_report(report, request_rows, steps)

    first, second, in_no_group = facts
    assert (first.first_step_id, first.last_step_id) == (4, 7)
    assert first.made_by_subagent == "partly"
    assert first.request_row_senders == "harness_process task_environment"
    assert first.steps_without_request_row == "7"
    assert second.made_by_subagent == "not_recorded"
    assert (
        in_no_group.fact_kind == check_reports.DerivedFactKind.REQUEST_ROW_IN_NO_GROUP
    )
    assert in_no_group.request_row.step_id == 6


def test_a_subagent_made_the_group_when_every_flag_of_its_steps_says_so():
    report = {"request_groups": [made_up_request_group()]}
    for flags, expected in (((True, True), "yes"), ((False, False), "no")):
        steps = [main_step(4, flags[0]), main_step(5, flags[1])]

        (fact,) = check_reports.derived_facts_of_report(report, [], steps)

        assert fact.made_by_subagent == expected


def test_a_report_without_request_groups_derives_no_facts():
    assert (
        check_reports.derived_facts_of_report(
            {"failed_requests": []}, [request_row(3)], []
        )
        == []
    )


def test_a_single_step_id_such_as_that_of_a_disputed_row_is_checked_too():
    report = report_with_group()
    report["request_rows_disputed"] = [
        {"step_id": 99, "target": "", "dispute": "not_a_request", "reason": ""}
    ]

    assert flags_of(report) == [
        (Flag.UNKNOWN_STEP_ID, "request_rows_disputed[0].step_id"),
        (Flag.DISPUTE_OF_NO_ROW, "request_rows_disputed[0]"),
    ]


def test_a_host_with_a_space_or_a_slash_is_no_host_name():
    report = report_with_group(hosts=["a.org", "a.org/x", "how to x"])

    assert flags_of(report) == [
        (Flag.HOST_THAT_IS_NO_HOST_NAME, "request_groups[0].hosts[1]"),
        (Flag.HOST_THAT_IS_NO_HOST_NAME, "request_groups[0].hosts[2]"),
    ]


def command_entry(step_ids, evidence_quote=""):
    return {
        "command": "npx",
        "step_ids": step_ids,
        "first_run_step_id": step_ids[0],
        "download_evidence": "output_filtered_or_not_shown",
        "what_was_downloaded": "",
        "evidence_quote": evidence_quote,
        "evidence_step_ids": [],
        "image_fetches_dependencies": "no",
        "image_evidence_quote": "Not in any step at all",
    }


def test_the_steps_of_a_command_entry_must_be_those_of_the_prompt():
    report = {"unconfirmed_commands": [command_entry([3, 9])], "notes": ""}

    flags = check_reports.flags_of_report(
        report,
        check_reports.ReadingContext(
            ReadingGroup.UNCONFIRMED_COMMAND,
            [trajectory_steps.TrajectoryStep("main", {"step_id": s}) for s in STEP_IDS],
            command_step_ids={"npx": [3, 5, 7]},
        ),
    )

    assert [(f.flag, f.detail) for f in flags] == [
        (Flag.COMMAND_STEPS_DIFFER, "missing 5 7, extra 9")
    ]


@pytest.mark.parametrize(
    ("quote", "is_found"),
    [
        ("only docs", True),
        ('"The agent said: only docs."', True),
        ("The agent said ... docs", True),
        ("only manuals", False),
    ],
)
def test_a_quote_must_be_in_the_steps_it_cites(quote, is_found):
    report = {"unconfirmed_commands": [command_entry([3], quote)], "notes": ""}

    flags = flags_of(report, ReadingGroup.UNCONFIRMED_COMMAND, ["npx"])

    assert flags == (
        []
        if is_found
        else [(Flag.QUOTE_NOT_IN_CITED_STEPS, "unconfirmed_commands[0].evidence_quote")]
    )


def test_a_quote_in_a_step_it_does_not_cite_is_not_found():
    report = report_with_group()
    report["online_rule"] = {**ONLINE_RULE, "step_ids": [99]}

    assert (Flag.QUOTE_NOT_IN_CITED_STEPS, "online_rule.reason_given") in flags_of(
        report
    )


def test_a_confirmed_row_not_received_needs_a_failed_request_or_a_dispute():
    rows = [
        request_row(6, "package", result_view="not_received"),
        request_row(7, "package", result_view="not_received"),
        request_row(8, "package", result_view="not_received"),
        request_row(9, result_view="not_received", request_measure_bound="upper_only"),
        request_row(10, result_view="not_received", trajectory_id="sub-1"),
    ]
    report = report_with_group()
    report["failed_requests"] = [
        {
            "step_ids": [6],
            "hosts": ["a.org"],
            "failure_shown": "timeout",
            "failure_output_step_ids": [],
            "next_action": "retried_same",
            "next_action_step_ids": [],
            "content_obtained_later": "no",
        }
    ]
    report["request_rows_disputed"] = [
        {
            "step_id": 7,
            "target": "https://a.org/7",
            "dispute": "never_sent",
            "reason": "",
        }
    ]

    flags = check_reports.flags_of_report(
        report,
        check_reports.ReadingContext(
            ReadingGroup.REQUESTED_AND_SOLVED,
            [
                trajectory_steps.TrajectoryStep(
                    "main", {"step_id": s, "message": STEP_TEXT}
                )
                for s in STEP_IDS
            ],
            rows,
        ),
    )

    assert [(f.flag, f.detail) for f in flags] == [
        (Flag.NOT_RECEIVED_ROW_WITHOUT_FAILED_REQUEST, "step 8 https://a.org/8")
    ]


def test_a_command_quote_may_sit_in_an_evidence_step():
    entry = {**command_entry([3], "Downloaded 12 files"), "evidence_step_ids": [5]}
    steps = [
        trajectory_steps.TrajectoryStep("main", {"step_id": 3, "message": "run"}),
        trajectory_steps.TrajectoryStep(
            "main", {"step_id": 5, "message": "Downloaded 12 files"}
        ),
    ]

    flags = check_reports.flags_of_report(
        {"unconfirmed_commands": [entry], "notes": ""},
        check_reports.ReadingContext(
            ReadingGroup.UNCONFIRMED_COMMAND, steps, command_step_ids={"npx": [3]}
        ),
    )

    assert flags == []


def test_disputes_must_match_a_row_and_a_never_sent_request_belongs_to_no_group_or_failure():
    # The group of steps 4 and 5 asks files.a.org, so a fallback to a.org at step 4 that never left is no fault.
    report = report_with_group()
    report["failed_requests"] = [made_up_failed_request([6], ["a.org"])]

    def never_sent(step_id, target):
        return {
            "step_id": step_id,
            "target": target,
            "dispute": "never_sent",
            "reason": "",
        }

    report["request_rows_disputed"] = [
        never_sent(4, "https://a.org/4"),
        never_sent(4, "https://files.a.org/x"),
        never_sent(6, "https://a.org/6"),
        {"step_id": 9, "target": "", "dispute": "not_a_request", "reason": ""},
    ]
    rows = [
        request_row(4),
        dataclasses.replace(
            request_row(4), target="https://files.a.org/x", host_names="files.a.org"
        ),
        request_row(6, "package"),
        request_row(9, "package"),
    ]

    assert flags_of(report, request_rows=rows) == [
        (Flag.NEVER_SENT_STEP_IN_GROUP_OR_FAILURE, "request_rows_disputed[1]"),
        (Flag.NEVER_SENT_STEP_IN_GROUP_OR_FAILURE, "request_rows_disputed[2]"),
        (Flag.DISPUTE_OF_NO_ROW, "request_rows_disputed[3]"),
    ]


def test_a_confirmed_non_package_row_needs_a_group_or_a_dispute():
    report = report_with_group()
    report["request_rows_disputed"] = [
        {
            "step_id": 7,
            "target": "https://a.org/7",
            "dispute": "not_a_request",
            "reason": "",
        }
    ]
    rows = [
        request_row(4),
        request_row(6, "search"),
        request_row(7),
        request_row(8, "package"),
        request_row(9, request_measure_bound="upper_only"),
        request_row(10, is_internet_use="false", request_measure_bound="neither"),
    ]

    assert flags_of(report, request_rows=rows) == [
        (Flag.CONFIRMED_ROW_IN_NO_GROUP, "request_groups")
    ]


def test_a_failed_request_names_a_host_of_the_rows_at_its_steps():
    report = report_with_group()
    report["failed_requests"] = [
        made_up_failed_request([6], ["b.org"]),
        made_up_failed_request([6], ["a.org", "b.org"]),
        made_up_failed_request([12], ["b.org"]),
    ]
    rows = [request_row(6, "package"), request_row(12, "package")]
    # The row at step 12 names no host, so the entry of that step is not checked.
    rows[1] = dataclasses.replace(rows[1], host_names="")

    assert flags_of(report, request_rows=rows) == [
        (Flag.FAILED_HOSTS_NOT_AT_STEPS, "failed_requests[0].hosts")
    ]


def test_a_quote_may_change_dashes_quote_marks_and_backticks_but_not_its_words():
    steps = [
        trajectory_steps.TrajectoryStep(
            "main",
            {
                "step_id": 3,
                "reasoning_content": "Is it `vii` or `viio`? It's HTML - not the PDF.",
            },
        )
    ]
    for quote, is_found in (
        ("Is it vii or viio?", True),
        ("It’s HTML — not the PDF", True),
        ("Is it vii or vii°?", False),
    ):
        assert check_reports._is_quote_in_steps(quote, [3], steps) == is_found, quote


def test_a_reason_is_looked_for_from_its_cited_step_through_the_first_request_step():
    def quote_flags(texts):
        report = report_with_group(
            steps=[(6, "wanted_content")],
            shown_before_request="failed_step",
            shown_before_request_step_ids=[3],
            shown_before_request_detail='The "mirror" is blocked.',
        )
        steps = [
            trajectory_steps.TrajectoryStep(
                "main", {"step_id": step_id, "message": text}
            )
            for step_id, text in {2: STEP_TEXT, 9: STEP_TEXT, **texts}.items()
        ]
        context = check_reports.ReadingContext(ReadingGroup.REQUESTED_AND_SOLVED, steps)
        return [
            (f.flag, f.where)
            for f in check_reports.flags_of_report(report, context)
            if f.flag in (Flag.QUOTE_NOT_IN_CITED_STEPS, Flag.QUOTE_ONLY_AFTER_REQUEST)
        ]

    where = "request_groups[0].shown_before_request_detail"
    # A step between the cited one and the request, with other case, marks and punctuation.
    assert (
        quote_flags(
            {3: "error 403", 5: "the **mirror** is blocked - try another", 6: "curl"}
        )
        == []
    )
    assert quote_flags({3: "error 403", 6: "curl", 8: "The mirror is blocked"}) == [
        (Flag.QUOTE_ONLY_AFTER_REQUEST, where)
    ]
    assert quote_flags({3: "error 403", 6: "curl", 8: "The mirror is down"}) == [
        (Flag.QUOTE_NOT_IN_CITED_STEPS, where)
    ]


def test_quotes_are_compared_without_escapes_case_marks_links_and_punctuation():
    step_text = 'echo \\"Note:\\" see [the docs](https://a.org/x) — TLS 1.3 / ok\nDone'
    for quote, is_found in (
        ('"note" see the docs, tls 1.3 ok done.', True),
        ("Note: see the docs - TLS 1.3 ok", True),
        ("see the manual", False),
    ):
        assert (
            check_reports._comparable_text_of(quote)
            in check_reports._comparable_text_of(step_text)
        ) == is_found, quote


@pytest.mark.parametrize(
    ("effects", "steps", "detail"),
    [
        (
            [made_up_effect("entered_answer", answer_part="x")],
            [(4, "not_recorded")],
            "entered_answer, every step not_recorded",
        ),
        (
            [made_up_effect("entered_answer", answer_part="x")],
            [(4, "nothing")],
            "entered_answer",
        ),
    ],
)
def test_an_answer_effect_without_received_content_says_when_nothing_was_recorded(
    effects, steps, detail
):
    report = report_with_group(effects=effects, steps=steps)
    context = check_reports.ReadingContext(
        ReadingGroup.REQUESTED_AND_SOLVED,
        [
            trajectory_steps.TrajectoryStep(
                "main", {"step_id": s, "message": STEP_TEXT}
            )
            for s in STEP_IDS
        ],
    )

    assert [
        f.detail
        for f in check_reports.flags_of_report(report, context)
        if f.flag == Flag.ANSWER_EFFECT_WITHOUT_RECEIVED_CONTENT
    ] == [detail]


def test_a_reach_beside_content_that_was_not_recorded_is_no_contradiction():
    report = report_with_group(
        steps=[(4, "not_recorded")],
        effects=[made_up_effect("entered_answer", answer_part="x")],
    )
    report["graded_answer_reach"] = "some"
    report["graded_answer_reach_detail"] = ""

    assert (
        Flag.GRADED_ANSWER_REACH_AGAINST_EFFECTS,
        "graded_answer_reach",
    ) not in flags_of(report)


def test_a_failed_request_without_hosts_is_not_checked_against_the_rows():
    report = report_with_group()
    report["failed_requests"] = [made_up_failed_request([6], [])]

    assert flags_of(report, request_rows=[request_row(6, "package")]) == []


@pytest.mark.parametrize(
    ("reach", "effects", "is_flagged"),
    [
        ("some", [made_up_effect("entered_answer", answer_part="x")], False),
        (
            "all",
            [made_up_effect("entered_answer", answer_part="x", tests_grade_part="no")],
            True,
        ),
        ("none", [made_up_effect("entered_answer", answer_part="x")], True),
        ("none", [made_up_effect("none_shown")], False),
        ("cannot_tell", [made_up_effect("none_shown")], False),
    ],
)
def test_graded_answer_reach_must_fit_the_effects_on_graded_parts(
    reach, effects, is_flagged
):
    report = report_with_group(effects=effects)
    report["graded_answer_reach"] = reach
    report["graded_answer_reach_detail"] = ""

    assert (
        (Flag.GRADED_ANSWER_REACH_AGAINST_EFFECTS, "graded_answer_reach")
        in flags_of(report)
    ) == is_flagged
