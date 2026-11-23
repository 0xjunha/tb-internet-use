"""Derive the labels of request groups, request steps and trials from the facts that a reader recorded, so that no reader picks a label.

Two readers of one trial who record the same facts get the same labels, since each label follows from the facts by one fixed order of rules, e.g. a group whose content changed an existing candidate is `changed_existing_answer` whatever else it did.
"""

from collections.abc import Sequence
from enum import StrEnum
from typing import Any

# The responses that show that content came back.
RECEIVED_RESPONSES = frozenset({"wanted_content", "success_only"})
# The responses of a step that got no wanted content.
UNRECEIVED_RESPONSES = frozenset({"other_content", "nothing"})
# The effects that put content into the answer or change it, and the one that only checks it.
ANSWER_EFFECTS = frozenset({"entered_answer", "existing_candidate_changed"})
CHECK_EFFECT = "existing_candidate_kept"
# The effects that name a part of the submitted answer.
EFFECTS_WITH_ANSWER_PART = frozenset(
    {"entered_answer", "existing_candidate_changed", "existing_candidate_kept"}
)


class UseLabel(StrEnum):
    """Label of a request group, and of each of its steps, derived by `group_label_of` and `step_labels_of`."""

    ACCESS_TEST_ONLY = "access_test_only"
    # The reader listed no effect but `other`.
    UNCLASSIFIED = "unclassified"
    CHANGED_EXISTING_ANSWER = "changed_existing_answer"
    ENTERED_ANSWER = "entered_answer"
    KEPT_EXISTING_ANSWER = "kept_existing_answer"
    DECIDED_LATER_REQUEST_OR_PLAN = "decided_later_request_or_plan"
    NOT_RECORDED = "not_recorded"
    NOT_RECEIVED = "not_received"
    RECEIVED_NO_EFFECT_SHOWN = "received_no_effect_shown"


class MergedStepLabel(StrEnum):
    """Coarse label of a request step, by its own response alone, which two readers who form groups differently can still share."""

    RECEIVED = "received"
    NOT_RECEIVED = "not_received"
    ACCESS_TEST_ONLY = "access_test_only"


class FirstRequestStart(StrEnum):
    """What came before the trial's first request group that asks for content, derived by `first_request_start_of`."""

    AFTER_FAILED_STEP = "after_failed_step"
    WITH_CANDIDATE = "with_candidate"
    FROM_THE_START = "from_the_start"
    # Only `other` prior candidates, and no failed step.
    UNCLASSIFIED = "unclassified"
    NO_REQUEST_GROUP = "no_request_group"
    # Request groups that all only test access, so no group asks for content.
    NO_CONTENT_REQUEST = "no_content_request"


class TrialUseSummary(StrEnum):
    """Summary of what the requests of one trial did to the graded answer, derived by `trial_use_summary_of`."""

    GRADED_ANSWER_MADE_OR_CHANGED = "graded_answer_made_or_changed"
    GRADED_ANSWER_CHECKED_ONLY = "graded_answer_checked_only"
    NO_EFFECT_ON_GRADED_ANSWER_SHOWN = "no_effect_on_graded_answer_shown"
    # A group whose steps are all `not_recorded`, e.g. a search the model provider runs, may have received what the trajectory does not show.
    CONTENT_NOT_RECORDED = "content_not_recorded"
    # Requests whose recorded responses delivered no content, e.g. only `other_content` or `nothing`.
    NO_CONTENT_RECEIVED = "no_content_received"
    NO_REQUEST = "no_request"
    # Request groups whose steps are all `other` or that list no step.
    CANNOT_JUDGE = "cannot_judge"


def request_step_ids_of(request_group: dict[str, Any]) -> list[int]:
    """List the step ids of a group's request steps in the order the reader gave them."""
    return [request_step["step_id"] for request_step in request_group["request_steps"]]


def group_label_of(request_group: dict[str, Any]) -> UseLabel:
    """Give the first label whose rule a group meets, in the order of `UseLabel`, i.e. access tests, then the strongest listed effect, then `unclassified` when `other` is the only effect, then what came back.

    An `other` effect or prior candidate hides no other effect, so a group with `other` and `entered_answer` is `entered_answer`.
    """
    responses = [step["response"] for step in request_group["request_steps"]]
    effects = {effect["effect"] for effect in request_group["effects"]}
    if responses and all(response == "access_test_only" for response in responses):
        return UseLabel.ACCESS_TEST_ONLY
    for effect, label in (
        ("existing_candidate_changed", UseLabel.CHANGED_EXISTING_ANSWER),
        ("entered_answer", UseLabel.ENTERED_ANSWER),
        (CHECK_EFFECT, UseLabel.KEPT_EXISTING_ANSWER),
        ("decided_later_request_or_plan", UseLabel.DECIDED_LATER_REQUEST_OR_PLAN),
    ):
        if effect in effects:
            return label
    if effects == {"other"}:
        return UseLabel.UNCLASSIFIED
    if not RECEIVED_RESPONSES & set(responses):
        if responses and all(response == "not_recorded" for response in responses):
            return UseLabel.NOT_RECORDED
        return UseLabel.NOT_RECEIVED
    return UseLabel.RECEIVED_NO_EFFECT_SHOWN


def step_labels_of(request_group: dict[str, Any]) -> list[tuple[int, UseLabel]]:
    """Give each request step of a group its label, `access_test_only` or `not_received` by its own response where that says so, and the group's label otherwise."""
    group_label = group_label_of(request_group)
    labels: list[tuple[int, UseLabel]] = []
    for request_step in request_group["request_steps"]:
        if request_step["response"] == "access_test_only":
            label = UseLabel.ACCESS_TEST_ONLY
        elif request_step["response"] in UNRECEIVED_RESPONSES:
            label = UseLabel.NOT_RECEIVED
        else:
            label = group_label
        labels.append((request_step["step_id"], label))
    return labels


def step_label_sets_of(
    request_groups: Sequence[dict[str, Any]],
) -> dict[int, frozenset[UseLabel]]:
    """Give each request step of a report every label that its groups give it, since one step can hold several calls whose requests belong to different groups."""
    label_sets: dict[int, set[UseLabel]] = {}
    for request_group in request_groups:
        for step_id, label in step_labels_of(request_group):
            label_sets.setdefault(step_id, set()).add(label)
    return {step_id: frozenset(labels) for step_id, labels in label_sets.items()}


def merged_step_label_sets_of(
    request_groups: Sequence[dict[str, Any]],
) -> dict[int, frozenset[MergedStepLabel]]:
    """Give each request step the merged labels of its responses, `received` for `wanted_content` or `success_only`, `access_test_only` for an access test and `not_received` otherwise, e.g. for `not_recorded`."""
    label_sets: dict[int, set[MergedStepLabel]] = {}
    for request_group in request_groups:
        for step in request_group["request_steps"]:
            if step["response"] == "access_test_only":
                label = MergedStepLabel.ACCESS_TEST_ONLY
            elif step["response"] in RECEIVED_RESPONSES:
                label = MergedStepLabel.RECEIVED
            else:
                label = MergedStepLabel.NOT_RECEIVED
            label_sets.setdefault(step["step_id"], set()).add(label)
    return {step_id: frozenset(labels) for step_id, labels in label_sets.items()}


def first_content_groups_of(
    request_groups: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Give the groups that are not `access_test_only` and start at the earliest first request step among such groups, several when they tie, empty when there is none."""
    content_groups = [
        group
        for group in request_groups
        if group["request_steps"] and group_label_of(group) != UseLabel.ACCESS_TEST_ONLY
    ]
    if not content_groups:
        return []
    earliest_step_id = min(min(request_step_ids_of(group)) for group in content_groups)
    return [
        group
        for group in content_groups
        if min(request_step_ids_of(group)) == earliest_step_id
    ]


def first_request_start_of(
    request_groups: Sequence[dict[str, Any]],
) -> FirstRequestStart:
    """Tell what came before the first groups that ask for content, by the first rule that holds over all groups tied at the earliest first request step.

    1. No group gives `no_request_group`, and groups that all only test access give `no_content_request`.
    2. A failed step before one of the first groups, or before an `access_test_only` group that starts earlier, gives `after_failed_step`, since a reader may put such an access test in a group of its own.
    3. A prior candidate of one of the first groups gives `with_candidate`.
    4. A `prior_candidate` of `none_shown` gives `from_the_start`.
    5. Otherwise, i.e. only `other` prior candidates, `unclassified`.

    Any reason but a failed step, `other` too, leaves it to the prior candidate, so that list order and a reason a reader could not name hide no fact.
    """
    first_groups = first_content_groups_of(request_groups)
    if not first_groups:
        return (
            FirstRequestStart.NO_CONTENT_REQUEST
            if request_groups
            else FirstRequestStart.NO_REQUEST_GROUP
        )
    first_step_id = min(request_step_ids_of(first_groups[0]))
    earlier_access_tests = [
        group
        for group in request_groups
        if group["request_steps"]
        and group_label_of(group) == UseLabel.ACCESS_TEST_ONLY
        and min(request_step_ids_of(group)) < first_step_id
    ]
    if any(
        group["shown_before_request"] == "failed_step"
        for group in [*first_groups, *earlier_access_tests]
    ):
        return FirstRequestStart.AFTER_FAILED_STEP
    prior_candidates = {group["prior_candidate"] for group in first_groups}
    if prior_candidates & {"in_file_or_output", "in_agent_text_only"}:
        return FirstRequestStart.WITH_CANDIDATE
    if "none_shown" in prior_candidates:
        return FirstRequestStart.FROM_THE_START
    return FirstRequestStart.UNCLASSIFIED


def content_kinds_reaching_graded_answer_of(
    request_groups: Sequence[dict[str, Any]],
) -> str:
    """List, sorted and separated by spaces, the content kinds of the groups that received content and whose content entered or changed a graded part of the answer."""
    return " ".join(
        sorted(
            {
                kind
                for group in request_groups
                if has_received_step(group)
                and any(
                    effect["effect"] in ANSWER_EFFECTS
                    and effect["tests_grade_part"] == "yes"
                    for effect in group["effects"]
                )
                for kind in group["content_kinds"]
            }
        )
    )


def other_answers_of(
    request_groups: Sequence[dict[str, Any]],
) -> list[tuple[int, str, str]]:
    """List every answer `other` of the groups as its 0-based group index, the key that holds it and the text that explains it, e.g. `request_steps[0].response` with its `response_other`."""
    answers: list[tuple[int, str, str]] = []
    for group_index, group in enumerate(request_groups):
        for index, step in enumerate(group["request_steps"]):
            if step["response"] == "other":
                answers.append(
                    (
                        group_index,
                        f"request_steps[{index}].response",
                        step["response_other"],
                    )
                )
        if "other" in group["content_kinds"]:
            answers.append((group_index, "content_kinds", group["use_detail"]))
        for key in ("shown_before_request", "prior_candidate"):
            if group[key] == "other":
                answers.append((group_index, key, group[f"{key}_detail"]))
        for index, effect in enumerate(group["effects"]):
            if effect["effect"] == "other":
                answers.append(
                    (group_index, f"effects[{index}].effect", effect["detail"])
                )
    return answers


def steps_from_failed_step_of(request_group: dict[str, Any]) -> int | None:
    """Give the number of steps from the last cited failed step to the group's first request step, None when the reason shown is no failed step or no step is cited."""
    cited_step_ids = request_group["shown_before_request_step_ids"]
    step_ids = request_step_ids_of(request_group)
    if (
        request_group["shown_before_request"] != "failed_step"
        or not cited_step_ids
        or not step_ids
    ):
        return None
    return min(step_ids) - max(cited_step_ids)


def trial_use_summary_of(request_groups: Sequence[dict[str, Any]]) -> TrialUseSummary:
    """Sum up the groups of a trial by the first rule that holds, counting only the effects of groups that received content.

    1. No request group gives `no_request`.
    2. An effect that entered or changed a graded part gives `graded_answer_made_or_changed`, then one that kept a graded part gives `graded_answer_checked_only`.
    3. A step that received content gives `no_effect_on_graded_answer_shown`.
    4. A group whose steps are all `not_recorded` gives `content_not_recorded`.
    5. A step with any response but `other` gives `no_content_received`, and otherwise `cannot_judge`.
    """
    if not request_groups:
        return TrialUseSummary.NO_REQUEST
    effects = effects_on_answer_of(request_groups)
    if any(
        effect["effect"] in ANSWER_EFFECTS and effect["tests_grade_part"] == "yes"
        for effect in effects
    ):
        return TrialUseSummary.GRADED_ANSWER_MADE_OR_CHANGED
    if any(
        effect["effect"] == CHECK_EFFECT and effect["tests_grade_part"] == "yes"
        for effect in effects
    ):
        return TrialUseSummary.GRADED_ANSWER_CHECKED_ONLY
    if any(has_received_step(group) for group in request_groups):
        return TrialUseSummary.NO_EFFECT_ON_GRADED_ANSWER_SHOWN
    if any(
        group["request_steps"]
        and all(step["response"] == "not_recorded" for step in group["request_steps"])
        for group in request_groups
    ):
        return TrialUseSummary.CONTENT_NOT_RECORDED
    if any(
        step["response"] != "other"
        for group in request_groups
        for step in group["request_steps"]
    ):
        return TrialUseSummary.NO_CONTENT_RECEIVED
    return TrialUseSummary.CANNOT_JUDGE


def has_received_step(request_group: dict[str, Any]) -> bool:
    """Tell whether a step of a group got content back, i.e. is `wanted_content` or `success_only`."""
    return any(
        step["response"] in RECEIVED_RESPONSES
        for step in request_group["request_steps"]
    )


def effects_on_answer_of(
    request_groups: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """List the effects of the groups that received content, since a group whose content the trajectory never shows cannot be seen to change the answer, e.g. a provider search whose steps are all `not_recorded`."""
    return [
        effect
        for group in request_groups
        if has_received_step(group)
        for effect in group["effects"]
    ]


def cannot_tell_grade_count_of(request_groups: Sequence[dict[str, Any]]) -> int:
    """Count the effects of a trial's groups whose `tests_grade_part` is `cannot_tell`."""
    return sum(
        effect["tests_grade_part"] == "cannot_tell"
        for group in request_groups
        for effect in group["effects"]
    )
