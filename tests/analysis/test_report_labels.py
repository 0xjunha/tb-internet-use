"""Test each rule by which `analysis/report_labels.py` derives the labels of groups, steps and trials, on made-up request groups."""

import pytest
from analysis_modules import analysis_module
from made_up_reports import made_up_effect, made_up_request_group

report_labels = analysis_module("report_labels")
UseLabel = report_labels.UseLabel
Summary = report_labels.TrialUseSummary


@pytest.mark.parametrize(
    ("group", "expected"),
    [
        # Rule 1, every step only tested access, whatever the effects say.
        (
            made_up_request_group(
                steps=[(4, "access_test_only"), (5, "access_test_only")],
                effects=[made_up_effect("other")],
            ),
            UseLabel.ACCESS_TEST_ONLY,
        ),
        # An `other` prior candidate or effect hides no listed effect.
        (
            made_up_request_group(prior_candidate="other"),
            UseLabel.ENTERED_ANSWER,
        ),
        (
            made_up_request_group(
                effects=[
                    made_up_effect("existing_candidate_changed"),
                    made_up_effect("other"),
                ]
            ),
            UseLabel.CHANGED_EXISTING_ANSWER,
        ),
        # `unclassified` only when `other` is the only effect, before what came back.
        (
            made_up_request_group(
                steps=[(4, "nothing")], effects=[made_up_effect("other")]
            ),
            UseLabel.UNCLASSIFIED,
        ),
        # Rules 3 to 6 by the strongest effect.
        (
            made_up_request_group(
                effects=[
                    made_up_effect("entered_answer"),
                    made_up_effect("existing_candidate_changed"),
                ]
            ),
            UseLabel.CHANGED_EXISTING_ANSWER,
        ),
        (
            made_up_request_group(
                effects=[
                    made_up_effect("existing_candidate_kept"),
                    made_up_effect("entered_answer"),
                ]
            ),
            UseLabel.ENTERED_ANSWER,
        ),
        (
            made_up_request_group(
                effects=[
                    made_up_effect("decided_later_request_or_plan"),
                    made_up_effect("existing_candidate_kept"),
                ]
            ),
            UseLabel.KEPT_EXISTING_ANSWER,
        ),
        (
            made_up_request_group(
                effects=[made_up_effect("decided_later_request_or_plan")]
            ),
            UseLabel.DECIDED_LATER_REQUEST_OR_PLAN,
        ),
        # Rule 7, nothing came back.
        (
            made_up_request_group(
                steps=[(4, "not_recorded"), (5, "not_recorded")],
                effects=[made_up_effect("none_shown")],
            ),
            UseLabel.NOT_RECORDED,
        ),
        (
            made_up_request_group(
                steps=[(4, "not_recorded"), (5, "other_content")],
                effects=[made_up_effect("none_shown")],
            ),
            UseLabel.NOT_RECEIVED,
        ),
        # Rule 8, content came back and showed no effect.
        (
            made_up_request_group(
                steps=[(4, "success_only")], effects=[made_up_effect("none_shown")]
            ),
            UseLabel.RECEIVED_NO_EFFECT_SHOWN,
        ),
    ],
)
def test_a_group_gets_the_label_of_the_first_rule_it_meets(group, expected):
    assert report_labels.group_label_of(group) == expected


def test_a_step_takes_its_own_label_when_it_only_tested_access_or_got_nothing():
    group = made_up_request_group(
        steps=[
            (4, "access_test_only"),
            (5, "nothing"),
            (6, "other_content"),
            (7, "wanted_content"),
            (8, "not_recorded"),
        ]
    )

    assert report_labels.step_labels_of(group) == [
        (4, UseLabel.ACCESS_TEST_ONLY),
        (5, UseLabel.NOT_RECEIVED),
        (6, UseLabel.NOT_RECEIVED),
        (7, UseLabel.ENTERED_ANSWER),
        (8, UseLabel.ENTERED_ANSWER),
    ]


def test_steps_from_a_failed_step_count_to_the_first_request_step():
    group = made_up_request_group(
        steps=[(12, "nothing"), (9, "wanted_content")],
        shown_before_request="failed_step",
        shown_before_request_step_ids=[3, 5],
    )

    assert report_labels.steps_from_failed_step_of(group) == 4
    assert (
        report_labels.steps_from_failed_step_of(
            {**group, "shown_before_request": "agent_says_what_it_will_get"}
        )
        is None
    )


@pytest.mark.parametrize(
    ("groups", "expected"),
    [
        (
            [
                made_up_request_group(
                    effects=[
                        made_up_effect(
                            "existing_candidate_kept", tests_grade_part="yes"
                        )
                    ]
                ),
                made_up_request_group(
                    effects=[
                        made_up_effect(
                            "existing_candidate_changed", tests_grade_part="yes"
                        )
                    ]
                ),
            ],
            Summary.GRADED_ANSWER_MADE_OR_CHANGED,
        ),
        (
            [
                made_up_request_group(
                    effects=[
                        made_up_effect("entered_answer", tests_grade_part="no"),
                        made_up_effect(
                            "existing_candidate_kept", tests_grade_part="yes"
                        ),
                    ]
                )
            ],
            Summary.GRADED_ANSWER_CHECKED_ONLY,
        ),
        (
            [
                made_up_request_group(
                    effects=[
                        made_up_effect("entered_answer", tests_grade_part="cannot_tell")
                    ]
                )
            ],
            Summary.NO_EFFECT_ON_GRADED_ANSWER_SHOWN,
        ),
        # The effect of a group that received nothing counts for nothing, e.g. a provider search answered from timing alone.
        (
            [
                made_up_request_group(steps=[(4, "not_recorded")]),
                made_up_request_group(
                    steps=[(6, "success_only")], effects=[made_up_effect("none_shown")]
                ),
            ],
            Summary.NO_EFFECT_ON_GRADED_ANSWER_SHOWN,
        ),
        # A group whose steps are all `not_recorded` may have received what the trajectory does not show.
        (
            [
                made_up_request_group(steps=[(4, "not_recorded")]),
                made_up_request_group(
                    steps=[(6, "nothing")], effects=[made_up_effect("none_shown")]
                ),
            ],
            Summary.CONTENT_NOT_RECORDED,
        ),
        # A `not_recorded` step beside a step that got nothing leaves the group shown as not received.
        (
            [
                made_up_request_group(
                    steps=[(4, "not_recorded"), (5, "other_content")],
                    effects=[made_up_effect("none_shown")],
                )
            ],
            Summary.NO_CONTENT_RECEIVED,
        ),
        (
            [
                made_up_request_group(
                    steps=[(4, "access_test_only")],
                    effects=[made_up_effect("none_shown")],
                )
            ],
            Summary.NO_CONTENT_RECEIVED,
        ),
        ([], Summary.NO_REQUEST),
        (
            [
                made_up_request_group(
                    steps=[(4, "other")], effects=[made_up_effect("none_shown")]
                )
            ],
            Summary.CANNOT_JUDGE,
        ),
    ],
)
def test_a_trial_is_summed_up_by_its_strongest_effect_on_a_graded_part(
    groups, expected
):
    assert report_labels.trial_use_summary_of(groups) == expected


def test_effects_whose_grading_cannot_be_told_are_counted():
    groups = [
        made_up_request_group(
            effects=[
                made_up_effect("entered_answer", tests_grade_part="cannot_tell"),
                made_up_effect(
                    "decided_later_request_or_plan", tests_grade_part="cannot_tell"
                ),
            ]
        ),
        made_up_request_group(effects=[made_up_effect("entered_answer")]),
    ]

    assert report_labels.cannot_tell_grade_count_of(groups) == 2


def test_a_step_in_several_groups_carries_every_label_of_those_groups():
    groups = [
        made_up_request_group(steps=[(4, "wanted_content"), (5, "access_test_only")]),
        made_up_request_group(
            steps=[(5, "success_only")], effects=[made_up_effect("none_shown")]
        ),
    ]

    assert report_labels.step_label_sets_of(groups) == {
        4: {UseLabel.ENTERED_ANSWER},
        5: {UseLabel.ACCESS_TEST_ONLY, UseLabel.RECEIVED_NO_EFFECT_SHOWN},
    }


def test_a_step_gets_a_merged_label_by_its_own_response():
    groups = [
        made_up_request_group(
            steps=[(4, "wanted_content"), (5, "not_recorded"), (6, "access_test_only")]
        ),
        made_up_request_group(
            steps=[(5, "success_only")], effects=[made_up_effect("none_shown")]
        ),
    ]
    Merged = report_labels.MergedStepLabel

    assert report_labels.merged_step_label_sets_of(groups) == {
        4: {Merged.RECEIVED},
        5: {Merged.NOT_RECEIVED, Merged.RECEIVED},
        6: {Merged.ACCESS_TEST_ONLY},
    }


Start = report_labels.FirstRequestStart


@pytest.mark.parametrize(
    ("first_group_fields", "expected"),
    [
        ({"shown_before_request": "failed_step"}, Start.AFTER_FAILED_STEP),
        ({"prior_candidate": "in_agent_text_only"}, Start.WITH_CANDIDATE),
        ({"prior_candidate": "none_shown"}, Start.FROM_THE_START),
        # An `other` reason leaves it to the prior candidate too.
        ({"shown_before_request": "other"}, Start.FROM_THE_START),
        (
            {"shown_before_request": "other", "prior_candidate": "in_file_or_output"},
            Start.WITH_CANDIDATE,
        ),
        # A response of an earlier request is no failure, so the prior candidate decides.
        (
            {
                "shown_before_request": "earlier_response_led_here",
                "prior_candidate": "in_file_or_output",
            },
            Start.WITH_CANDIDATE,
        ),
        (
            {"shown_before_request": "earlier_response_led_here"},
            Start.FROM_THE_START,
        ),
        ({"prior_candidate": "other"}, Start.UNCLASSIFIED),
    ],
)
def test_the_first_request_start_comes_from_the_earliest_group_that_asks_for_content(
    first_group_fields, expected
):
    groups = [
        made_up_request_group(
            steps=[(9, "wanted_content")], shown_before_request="failed_step"
        ),
        made_up_request_group(steps=[(5, "wanted_content")], **first_group_fields),
        # An earlier access test without a failed step does not count.
        made_up_request_group(
            steps=[(2, "access_test_only")], shown_before_request="no_reason_shown"
        ),
    ]

    assert report_labels.first_request_start_of(groups) == expected
    # Only access tests ask for no content, and no group at all is no request, as `trial_use_summary_of` says.
    assert report_labels.first_request_start_of([groups[2]]) == Start.NO_CONTENT_REQUEST
    assert report_labels.first_request_start_of([]) == Start.NO_REQUEST_GROUP


def test_content_kinds_reach_the_graded_answer_only_through_an_effect_on_a_graded_part():
    groups = [
        made_up_request_group(content_kinds=["data", "code"]),
        made_up_request_group(
            content_kinds=["documentation"],
            effects=[made_up_effect("entered_answer", tests_grade_part="no")],
        ),
        made_up_request_group(
            content_kinds=["program"],
            effects=[made_up_effect("existing_candidate_kept", tests_grade_part="yes")],
        ),
    ]

    assert report_labels.content_kinds_reaching_graded_answer_of(groups) == "code data"


def test_every_other_answer_is_listed_with_its_explanation():
    group = made_up_request_group(
        steps=[(4, "other")],
        content_kinds=["other"],
        prior_candidate="other",
        prior_candidate_detail="a guess",
        effects=[made_up_effect("other", detail="kept a copy")],
        use_detail="used as a fixture",
    )
    group["request_steps"][0]["response_other"] = "a zip"

    assert report_labels.other_answers_of([made_up_request_group(), group]) == [
        (1, "request_steps[0].response", "a zip"),
        (1, "content_kinds", "used as a fixture"),
        (1, "prior_candidate", "a guess"),
        (1, "effects[0].effect", "kept a copy"),
    ]


def test_content_kinds_of_a_group_that_received_nothing_reach_no_graded_answer():
    groups = [
        made_up_request_group(
            steps=[(4, "not_recorded")], content_kinds=["documentation"]
        ),
        made_up_request_group(content_kinds=["data"]),
    ]

    assert report_labels.content_kinds_reaching_graded_answer_of(groups) == "data"
    assert report_labels.effects_on_answer_of(groups) == groups[1]["effects"]


def test_a_failed_step_before_an_earlier_access_test_counts_for_the_first_request():
    # One reader split `curl -I` after "go: command not found" from the download that followed.
    access_test = made_up_request_group(
        steps=[(3, "access_test_only")],
        shown_before_request="failed_step",
        effects=[made_up_effect("none_shown")],
    )
    download = made_up_request_group(steps=[(4, "wanted_content")])
    later_access_test = {
        **access_test,
        "request_steps": [
            {"step_id": 8, "response": "access_test_only", "response_other": ""}
        ],
    }

    assert (
        report_labels.first_request_start_of([download, access_test])
        == Start.AFTER_FAILED_STEP
    )
    assert (
        report_labels.first_request_start_of([download, later_access_test])
        == Start.FROM_THE_START
    )


def test_groups_tied_at_the_first_request_step_are_judged_together_whatever_their_order():
    plain = made_up_request_group(steps=[(4, "wanted_content")])
    with_candidate = made_up_request_group(
        steps=[(4, "wanted_content"), (6, "nothing")],
        prior_candidate="in_agent_text_only",
    )
    after_failure = made_up_request_group(
        steps=[(4, "nothing")], shown_before_request="failed_step"
    )

    for groups, expected in (
        ([plain, with_candidate], Start.WITH_CANDIDATE),
        ([with_candidate, plain], Start.WITH_CANDIDATE),
        ([plain, with_candidate, after_failure], Start.AFTER_FAILED_STEP),
    ):
        assert report_labels.first_request_start_of(groups) == expected
