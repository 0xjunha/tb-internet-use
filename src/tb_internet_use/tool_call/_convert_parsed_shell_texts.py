"""Split the command string of each `RunCommandAction` in the action of one tool call into commands, filling its `parsed_shell_text`."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import replace

from tb_internet_use.tool_call.model import (
    ParsedShellText,
    RunCommandAction,
    RunToolScriptAction,
    ToolCallAction,
)
from tb_internet_use.tool_call.parse_shell_text import parse_shell_text


def convert_parsed_shell_texts(
    action: ToolCallAction, *, judgment_rule_use_counts: Counter[str]
) -> ToolCallAction:
    """Split the command string of each `RunCommandAction` in the action of one call into commands, returning the action with each `parsed_shell_text` filled.

    A `RunCommandAction` without a command string keeps `parsed_shell_text` None.
    A `RunToolScriptAction` can run several command strings, one per `RunCommandAction` step, e.g. a Codex `exec` script that calls `tools.exec_command` with `a; b` and then with `c`.
    The command ids then go on across its steps, 0 and 1 for a and b and 2 for c, so that they stay unique within the call.
    Any other action is returned as it is.
    """
    if isinstance(action, RunCommandAction):
        (run_command_action,) = _fill_parsed_shell_texts_of_actions(
            (action,), judgment_rule_use_counts=judgment_rule_use_counts
        )
        return run_command_action
    if isinstance(action, RunToolScriptAction):
        steps = _fill_parsed_shell_texts_of_actions(
            action.steps, judgment_rule_use_counts=judgment_rule_use_counts
        )
        return replace(action, steps=steps)
    return action


def _fill_parsed_shell_texts_of_actions(
    actions: Sequence[ToolCallAction], *, judgment_rule_use_counts: Counter[str]
) -> tuple[ToolCallAction, ...]:
    """Fill the `parsed_shell_text` of each `RunCommandAction` with a command string among the actions of one call, numbering the commands of all actions from 0 in their order.

    The actions are the action of the call alone or the steps of its tool script.
    """
    filled_actions: list[ToolCallAction] = []
    first_command_id = 0
    for action in actions:
        if isinstance(action, RunCommandAction) and action.command_str is not None:
            parsed_shell_text = parse_shell_text(
                action.command_str,
                judgment_rule_use_counts=judgment_rule_use_counts,
                first_command_id=first_command_id,
            )
            # An `UnreadableShellText` has no command, so it takes no id.
            if isinstance(parsed_shell_text, ParsedShellText):
                first_command_id += len(parsed_shell_text.commands)
            action = replace(action, parsed_shell_text=parsed_shell_text)
        filled_actions.append(action)
    return tuple(filled_actions)
