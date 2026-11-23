"""Made-up parts of reports that the tests of the analysis share, each a valid value of its schema that a test changes where it needs."""

from typing import Any


def made_up_request_group(
    steps: list[tuple[int, str]] | None = None,
    effects: list[dict[str, Any]] | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Give a request group whose content entered a graded answer, with `steps` as (step_id, response) pairs and fields to replace."""
    return {
        "fetched_content": "A structure file.",
        "hosts": ["files.a.org"],
        "request_steps": [
            {"step_id": step_id, "response": response, "response_other": ""}
            for step_id, response in (steps or [(4, "wanted_content"), (5, "nothing")])
        ],
        "content_kinds": ["data"],
        "shown_before_request": "agent_says_what_it_will_get",
        "shown_before_request_step_ids": [3],
        "shown_before_request_detail": "I need the structure",
        "prior_candidate": "none_shown",
        "prior_candidate_step_ids": [],
        "prior_candidate_detail": "",
        "effects": effects
        if effects is not None
        else [made_up_effect("entered_answer", answer_part="The positions")],
        "use_detail": "The positions were read from the file.",
        "agent_says_task_inputs_come_from_source": False,
        **fields,
    }


def made_up_effect(
    effect: str, *, answer_part: str = "", tests_grade_part: str = "yes", **fields: Any
) -> dict[str, Any]:
    return {
        "effect": effect,
        "step_ids": [9],
        "answer_part": answer_part,
        "tests_grade_part": tests_grade_part,
        "detail": "The value went into the answer.",
        **fields,
    }


def made_up_failed_request(
    step_ids: list[int] | None = None, hosts: list[str] | None = None, **fields: Any
) -> dict[str, Any]:
    return {
        "step_ids": step_ids if step_ids is not None else [6],
        "hosts": hosts if hosts is not None else ["a.org"],
        "failure_shown": "timeout",
        "failure_output_step_ids": [],
        "next_action": "other_host_or_mirror",
        "next_action_step_ids": [7],
        "content_obtained_later": "yes",
        **fields,
    }
