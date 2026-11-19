"""Read the text of one trial's detail file into the task, harness, model and reward that a `Trial` holds.

The detail file is the `detail.json` of the trial folder, which the service that ran the trial wrote.
"""

import json

from tb_internet_use.trial.model import TrialDetail


def parse_trial_detail(detail_text: str | bytes, trial_id: str) -> TrialDetail:
    """Read the text of one trial's detail file into a `TrialDetail`, keeping the reward as the file writes it.

    The text can be the bytes of the file. The model name is None when `agent_info.model_info` is null, as in the detail files of one leaderboard row of claude-code. Text that is not JSON, or that lacks a key or holds a value of another type than the ones read here, raises ValueError with the trial id as a note.
    """
    try:
        match json.loads(detail_text):
            case {
                "task_name": str(task_name),
                "agent_info": {
                    "name": str(harness),
                    "version": str(harness_version),
                    "model_info": model_info,
                },
                "verifier_result": verifier_result,
            }:
                return TrialDetail(
                    task_name=task_name,
                    harness=harness,
                    harness_version=harness_version,
                    model_name=_model_name_from_model_info(model_info),
                    reward=_reward_from_verifier_result(verifier_result),
                )
            case _:
                raise ValueError(
                    "the detail file lacks one of `task_name`, `agent_info.name`, `agent_info.version`, `agent_info.model_info` and `verifier_result`, or one of the first three is no text"
                )
    except ValueError as error:
        error.add_note(f"trial_id: {trial_id}")
        raise


def _model_name_from_model_info(model_info: object) -> str | None:
    """Give the name of the model info of a detail file, or None when the file writes the model info as null.

    Model info that is neither null nor an object with a text `name` raises ValueError.
    """
    match model_info:
        case None:
            return None
        case {"name": str(model_name)}:
            return model_name
        case _:
            raise ValueError(
                "the model info of the detail file is neither null nor an object with a text `name`"
            )


def _reward_from_verifier_result(verifier_result: object) -> float | None:
    """Give the reward of the verifier result of a detail file as a float, or None when the file has no verifier result.

    A reward written as a whole number, e.g. `0`, becomes `0.0`. A reward written as text or as true or false raises ValueError, since turning it into a number would give a value that the file does not hold. A whole number too large for a float raises ValueError too.
    """
    match verifier_result:
        case None:
            return None
        case {"rewards": {"reward": bool()}}:
            # `bool` is a subclass of `int`, so it must be ruled out before the next case.
            raise ValueError("the reward of the detail file is true or false")
        case {"rewards": {"reward": int() | float() as reward}}:
            try:
                return float(reward)
            except OverflowError as error:
                raise ValueError(
                    "the reward of the detail file is too large for a float"
                ) from error
        case _:
            raise ValueError(
                "the verifier result of the detail file has no `rewards.reward` that is a number"
            )
