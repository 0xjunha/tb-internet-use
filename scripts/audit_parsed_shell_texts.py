"""Run `convert_tool_calls` on raw trials, check that every `parsed_shell_text` it fills holds together, and count the split shell texts per harness.

A check holds for every value whatever the shell text, so each violation is a bug of the split and never a property of the data.
A shell text is the command string of one `RunCommandAction`, a step of a Codex `exec` script included.

| Check | What must hold |
|---|---|
| `parsed_shell_text_is_none_exactly_when_command_str_is_none` | A `RunCommandAction` without a command string has `parsed_shell_text` None and one with a command string has a `ParsedShellText` or an `UnreadableShellText`, so the actions add up to those without a command string plus the parsed and the unreadable shell texts |
| `command_ids_continue_within_call` | The command ids of all shell texts of one call, in step and command order, are 0, 1, 2 and so on |
| `pipe_reader_and_deciding_command_ids_are_commands_of_shell_text` | Each `PipeDestination.reader_id` and each `deciding_command_ids` names a command of the same shell text, and a deciding command comes before the one it decides |
| `expansion_word_indexes_point_at_expansions` | The `expansion_word_indexes` of a command rise, stay below the number of its words and point at words that hold `$`, a backtick, `<(` or `>(` |
| `structure_marks_agree_within_shell_text` | The commands of one shell text are all marked `structure_may_be_wrong` or none is |
| `assignment_positions_are_in_shell_text` | A `next_command_id` lies from the first id of its shell text to one past its last, and a for loop item's is at most its `next_command_id_after_for_loop` |

A check looks at one value at a time, i.e. one action, one shell text, one command or one variable assignment, and `checks.csv` counts those values.
A trial that raises breaks none of the checks and shows in `trial_outcomes.csv` instead.
The output types do not say why a shell text is marked `structure_may_be_wrong`, e.g. a syntax error, a brace list or lines left joined, so the counts do not split the marks by reason.

It writes five CSVs under `out/parsed_shell_texts/`, which `.gitignore` keeps out of the repo.
They hold counts, harness names, trial ids and masked shapes only, never text from a trajectory.

| File | One row |
|---|---|
| `trial_outcomes.csv` | An outcome of a trial, e.g. `converted`, `converted without tool calls`, `unreadable` with its reason or `exception` with its type name, with its trials and the first 20 trial ids |
| `checks.csv` | A check, with the values it looked at and the values that broke it |
| `check_violation_examples.csv` | A call that broke a check, at most one row per check and call and the first 20 calls per check, beside the number of values that broke the check in all |
| `counts_by_harness.csv` | A harness, with the counts of `ShellTextCounts` |
| `unreadable_shell_text_shape_examples.csv` | An `UnreadableShellText`, as its harness, the length of its shell text and the kind of its first character, the first 20 in all |

Run it as `nice -n 10 uv run python -I scripts/audit_parsed_shell_texts.py <raw_trials_dir> [--limit N | --trial-ids FILE]`.
"""

import argparse
import itertools
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import astuple, dataclass, field, fields
from enum import StrEnum
from pathlib import Path

from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge
from tb_internet_use.pipeline import read_trajectory
from tb_internet_use.tool_call import convert_tool_calls
from tb_internet_use.tool_call.judgment_rules import (
    treat_lines_joined_after_three_repairs_as_left_joined,
)
from tb_internet_use.tool_call.model import (
    ParsedShellText,
    PipeDestination,
    RunCommandAction,
    ShellCommand,
    ToolCall,
    ToolCallAction,
    ToolCallKey,
    UnreadableShellText,
    indexed_action_steps_of,
)
from tb_internet_use.trial.model import UnreadableTrajectory

# `python -I` leaves the folder of this script off `sys.path`, so the script puts it there to import the module beside it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from trial_folders_and_csv_files import (
    PROCESS_COUNT,
    add_trial_choice_arguments,
    chosen_trial_dirs_from,
    # This script does not use it. It stays until tests/tool_call/test_audit_parsed_shell_texts.py stops testing it through this script.
    trial_ids_from_file_text,  # noqa: F401
    write_csv,
)

OUT_DIR = Path(__file__).resolve().parents[1] / "out" / "parsed_shell_texts"
# The examples kept per check, per trial outcome and of unreadable shell texts in all, so that the CSVs stay short.
_EXAMPLE_LIMIT = 20
# The parts of a word that `expansion_word_indexes` may point at, i.e. what `$A`, `${A}`, `$(...)`, `$((...))`, backticks, `<(...)` and `>(...)` start with.
_EXPANSION_MARKS = ("$", "`", "<(", ">(")


class ParsedShellTextCheck(StrEnum):
    """Check that the `parsed_shell_text` of every `RunCommandAction` must pass, named in the CSVs of this script."""

    PARSED_SHELL_TEXT_IS_NONE_EXACTLY_WHEN_COMMAND_STR_IS_NONE = (
        "parsed_shell_text_is_none_exactly_when_command_str_is_none"
    )
    COMMAND_IDS_CONTINUE_WITHIN_CALL = "command_ids_continue_within_call"
    PIPE_READER_AND_DECIDING_COMMAND_IDS_ARE_COMMANDS_OF_SHELL_TEXT = (
        "pipe_reader_and_deciding_command_ids_are_commands_of_shell_text"
    )
    EXPANSION_WORD_INDEXES_POINT_AT_EXPANSIONS = (
        "expansion_word_indexes_point_at_expansions"
    )
    STRUCTURE_MARKS_AGREE_WITHIN_SHELL_TEXT = "structure_marks_agree_within_shell_text"
    ASSIGNMENT_POSITIONS_ARE_IN_SHELL_TEXT = "assignment_positions_are_in_shell_text"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    add_trial_choice_arguments(parser)
    arguments = parser.parse_args()

    total = TrialAuditTotal()
    with ProcessPoolExecutor(PROCESS_COUNT) as pool:
        for trial_audit in pool.map(
            audit_trial, chosen_trial_dirs_from(arguments), chunksize=5
        ):
            total.add_trial(trial_audit)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(
        OUT_DIR / "trial_outcomes.csv",
        ("outcome", "trial_count", "first_trial_ids"),
        (
            (
                outcome,
                trial_count,
                " ".join(total.trial_id_examples_by_outcome[outcome]),
            )
            for outcome, trial_count in sorted(total.outcome_counts.items())
        ),
    )
    write_csv(
        OUT_DIR / "checks.csv",
        ("check", "checked_count", "violation_count"),
        (
            (check, total.checked_counts[check], total.violation_counts[check])
            for check in ParsedShellTextCheck
        ),
    )
    write_csv(
        OUT_DIR / "check_violation_examples.csv",
        ("check", "trial_id", "tool_call_key", "violation_count"),
        (
            (check, trial_id, tool_call_key, total.violation_counts[check])
            for check, trial_id, tool_call_key in total.violation_examples
        ),
    )
    write_csv(
        OUT_DIR / "counts_by_harness.csv",
        ("harness", *(column.name for column in fields(ShellTextCounts))),
        (
            (harness, *astuple(shell_text_counts))
            for harness, shell_text_counts in sorted(
                total.shell_text_counts_by_harness.items()
            )
        ),
    )
    write_csv(
        OUT_DIR / "unreadable_shell_text_shape_examples.csv",
        ("harness", "shell_text_length", "first_character_kind"),
        total.unreadable_shell_text_shapes,
    )
    print(f"trials: {dict(sorted(total.outcome_counts.items()))}")
    for check in ParsedShellTextCheck:
        print(
            f"{check}: {total.violation_counts[check]} violations"
            f" of {total.checked_counts[check]} checked"
        )
    print(f"written under {OUT_DIR}")


def audit_trial(trial_dir: Path) -> TrialAudit:
    """Run `convert_tool_calls` on one trial and check and count the parsed shell texts of its calls, with an exception named instead of raised."""
    judgment_rule_use_counts: Counter[str] = Counter()
    try:
        harness_tool_calls = read_trajectory(trial_dir)
        if isinstance(harness_tool_calls, UnreadableTrajectory):
            return TrialAudit(trial_dir.name, f"unreadable {harness_tool_calls.reason}")
        tool_calls = convert_tool_calls(
            harness_tool_calls,
            knowledge=ToolCallKnowledge(),
            judgment_rule_use_counts=judgment_rule_use_counts,
        )
    except Exception as error:  # noqa: BLE001, one trial must not stop the run
        return TrialAudit(trial_dir.name, f"exception {type(error).__name__}")
    if not tool_calls:
        return TrialAudit(trial_dir.name, "converted without tool calls")
    trial_audit = TrialAudit(trial_dir.name, "converted")
    for tool_call in tool_calls:
        trial_audit.add_tool_call(tool_call)
    # The rule is counted per trial, since the counter of `convert_tool_calls` sums every call of the trial.
    harness_names = {
        tool_call.harness_tool_call.tool.harness for tool_call in tool_calls
    }
    harness = "|".join(sorted(harness_names))
    trial_audit.shell_text_counts_by_harness.setdefault(
        harness, ShellTextCounts()
    ).judgment_rule_use_count += judgment_rule_use_counts[
        treat_lines_joined_after_three_repairs_as_left_joined.__name__
    ]
    return trial_audit


@dataclass(slots=True)
class TrialAudit:
    """Result of auditing one trial, sent from a worker process to the main process that sums the trials."""

    trial_id: str
    # `converted`, `converted without tool calls`, `unreadable` with the reason, or `exception` with the type name.
    outcome: str
    checked_counts: Counter[ParsedShellTextCheck] = field(default_factory=Counter)
    violation_counts: Counter[ParsedShellTextCheck] = field(default_factory=Counter)
    # (check, trial id, tool call key) of each call that broke a check, once per check and call.
    violations: list[tuple[ParsedShellTextCheck, str, str]] = field(
        default_factory=list
    )
    shell_text_counts_by_harness: dict[str, ShellTextCounts] = field(
        default_factory=dict
    )
    # (harness, shell text length, kind of first character) of each `UnreadableShellText`.
    unreadable_shell_text_shapes: list[tuple[str, int, str]] = field(
        default_factory=list
    )

    def add_tool_call(self, tool_call: ToolCall) -> None:
        """Check and count the shell texts of one call."""
        harness = tool_call.harness_tool_call.tool.harness
        shell_text_counts = self.shell_text_counts_by_harness.setdefault(
            harness, ShellTextCounts()
        )
        shell_text_counts.trial_count = 1
        checked_counts, violation_counts = checked_and_violation_counts_of_action(
            tool_call.action
        )
        self.checked_counts.update(checked_counts)
        self.violation_counts.update(violation_counts)
        for check in violation_counts:
            self.violations.append(
                (
                    check,
                    self.trial_id,
                    _text_of_tool_call_key(tool_call.harness_tool_call.key),
                )
            )
        for _step_index, step in indexed_action_steps_of(tool_call.action):
            if isinstance(step, RunCommandAction):
                shell_text_counts.add_run_command_action(step)
                command_str = step.command_str
                if command_str is not None and isinstance(
                    step.parsed_shell_text, UnreadableShellText
                ):
                    self.unreadable_shell_text_shapes.append(
                        (
                            harness,
                            len(command_str),
                            first_character_kind_of(command_str),
                        )
                    )


@dataclass(slots=True)
class TrialAuditTotal:
    """Sum of the `TrialAudit` of many trials, built by `main` to write the CSVs."""

    # The number of trials of each outcome, e.g. `converted`.
    outcome_counts: Counter[str] = field(default_factory=Counter)
    # The first trial ids of each outcome.
    trial_id_examples_by_outcome: dict[str, list[str]] = field(default_factory=dict)
    checked_counts: Counter[ParsedShellTextCheck] = field(default_factory=Counter)
    violation_counts: Counter[ParsedShellTextCheck] = field(default_factory=Counter)
    violation_examples: list[tuple[ParsedShellTextCheck, str, str]] = field(
        default_factory=list
    )
    shell_text_counts_by_harness: dict[str, ShellTextCounts] = field(
        default_factory=dict
    )
    unreadable_shell_text_shapes: list[tuple[str, int, str]] = field(
        default_factory=list
    )

    def add_trial(self, trial_audit: TrialAudit) -> None:
        """Add what one trial counted, keeping the first examples of each outcome, of each check and of the unreadable shell texts."""
        self.outcome_counts[trial_audit.outcome] += 1
        trial_ids = self.trial_id_examples_by_outcome.setdefault(
            trial_audit.outcome, []
        )
        if len(trial_ids) < _EXAMPLE_LIMIT:
            trial_ids.append(trial_audit.trial_id)
        self.checked_counts.update(trial_audit.checked_counts)
        self.violation_counts.update(trial_audit.violation_counts)
        for violation in trial_audit.violations:
            check = violation[0]
            kept = sum(1 for example in self.violation_examples if example[0] == check)
            if kept < _EXAMPLE_LIMIT:
                self.violation_examples.append(violation)
        for (
            harness,
            shell_text_counts,
        ) in trial_audit.shell_text_counts_by_harness.items():
            self.shell_text_counts_by_harness.setdefault(
                harness, ShellTextCounts()
            ).add_shell_text_counts(shell_text_counts)
        room = _EXAMPLE_LIMIT - len(self.unreadable_shell_text_shapes)
        self.unreadable_shell_text_shapes += trial_audit.unreadable_shell_text_shapes[
            : max(room, 0)
        ]


@dataclass(slots=True)
class ShellTextCounts:
    """Counts of the shell texts and their commands of one harness, kept per trial by `TrialAudit` and summed by `TrialAuditTotal` into a row of `counts_by_harness.csv`.

    They give the numbers that the expected counts of a full run are held against, e.g. the shell texts with a non-whitespace character, and the parts that must add up, i.e. the `RunCommandAction`s are those without a command string plus the shell texts.
    """

    trial_count: int = 0
    run_command_action_count: int = 0
    run_command_action_without_command_str_count: int = 0
    # The command strings, i.e. the `RunCommandAction`s with one, empty ones included.
    shell_text_count: int = 0
    # The shell texts with a character other than whitespace.
    non_whitespace_shell_text_count: int = 0
    unreadable_shell_text_count: int = 0
    # The `ParsedShellText`s without commands whose shell text is empty or only whitespace, e.g. an empty command string.
    empty_or_whitespace_shell_text_without_commands_count: int = 0
    # The `ParsedShellText`s without commands whose shell text has another character, e.g. `# note` or `> f`.
    non_whitespace_shell_text_without_commands_count: int = 0
    command_count: int = 0
    command_with_structure_may_be_wrong_count: int = 0
    shell_text_with_structure_may_be_wrong_count: int = 0
    # The uses of `treat_lines_joined_after_three_repairs_as_left_joined`.
    judgment_rule_use_count: int = 0

    def add_run_command_action(self, run_command_action: RunCommandAction) -> None:
        """Count one `RunCommandAction`, its shell text and the commands of its `parsed_shell_text`."""
        self.run_command_action_count += 1
        command_str = run_command_action.command_str
        if command_str is None:
            self.run_command_action_without_command_str_count += 1
            return
        self.shell_text_count += 1
        has_non_whitespace = bool(command_str.strip())
        self.non_whitespace_shell_text_count += has_non_whitespace
        parsed_shell_text = run_command_action.parsed_shell_text
        if isinstance(parsed_shell_text, UnreadableShellText):
            self.unreadable_shell_text_count += 1
        elif isinstance(parsed_shell_text, ParsedShellText):
            commands = parsed_shell_text.commands
            if not commands:
                if has_non_whitespace:
                    self.non_whitespace_shell_text_without_commands_count += 1
                else:
                    self.empty_or_whitespace_shell_text_without_commands_count += 1
            self.command_count += len(commands)
            marked_command_count = sum(
                command.structure_may_be_wrong for command in commands
            )
            self.command_with_structure_may_be_wrong_count += marked_command_count
            self.shell_text_with_structure_may_be_wrong_count += (
                marked_command_count > 0
            )

    def add_shell_text_counts(self, shell_text_counts: ShellTextCounts) -> None:
        """Add the counts of another `ShellTextCounts`, e.g. those of one more trial."""
        for column in fields(self):
            setattr(
                self,
                column.name,
                getattr(self, column.name) + getattr(shell_text_counts, column.name),
            )


def checked_and_violation_counts_of_action(
    action: ToolCallAction,
) -> tuple[Counter[ParsedShellTextCheck], Counter[ParsedShellTextCheck]]:
    """Check the `parsed_shell_text` of each `RunCommandAction` of one call's action, a step of a tool script included, giving how many values each check looked at and how many broke it.

    The first id of a shell text is the number of commands of the earlier shell texts of the call, so that a shell text whose ids start elsewhere breaks `command_ids_continue_within_call`.
    """
    checked_counts: Counter[ParsedShellTextCheck] = Counter()
    violation_counts: Counter[ParsedShellTextCheck] = Counter()

    def count_check(check: ParsedShellTextCheck, holds: bool) -> None:
        checked_counts[check] += 1
        if not holds:
            violation_counts[check] += 1

    first_command_id = 0
    for _step_index, step in indexed_action_steps_of(action):
        if not isinstance(step, RunCommandAction):
            continue
        parsed_shell_text = step.parsed_shell_text
        count_check(
            ParsedShellTextCheck.PARSED_SHELL_TEXT_IS_NONE_EXACTLY_WHEN_COMMAND_STR_IS_NONE,
            parsed_shell_text is None
            if step.command_str is None
            else isinstance(parsed_shell_text, ParsedShellText | UnreadableShellText),
        )
        if not isinstance(parsed_shell_text, ParsedShellText):
            continue
        commands = parsed_shell_text.commands
        command_ids = [command.id for command in commands]
        count_check(
            ParsedShellTextCheck.COMMAND_IDS_CONTINUE_WITHIN_CALL,
            command_ids
            == list(range(first_command_id, first_command_id + len(commands))),
        )
        count_check(
            ParsedShellTextCheck.PIPE_READER_AND_DECIDING_COMMAND_IDS_ARE_COMMANDS_OF_SHELL_TEXT,
            all(
                _has_pipe_reader_and_deciding_command_ids_in(command, set(command_ids))
                for command in commands
            ),
        )
        for command in commands:
            count_check(
                ParsedShellTextCheck.EXPANSION_WORD_INDEXES_POINT_AT_EXPANSIONS,
                _has_expansion_word_indexes_at_expansions(command),
            )
        count_check(
            ParsedShellTextCheck.STRUCTURE_MARKS_AGREE_WITHIN_SHELL_TEXT,
            len({command.structure_may_be_wrong for command in commands}) <= 1,
        )
        first_command_id_after_shell_text = first_command_id + len(commands)
        for variable_assignment in parsed_shell_text.variable_assignments:
            next_command_id = variable_assignment.next_command_id
            next_command_id_after_for_loop = (
                variable_assignment.next_command_id_after_for_loop
            )
            count_check(
                ParsedShellTextCheck.ASSIGNMENT_POSITIONS_ARE_IN_SHELL_TEXT,
                first_command_id <= next_command_id <= first_command_id_after_shell_text
                and (
                    next_command_id_after_for_loop is None
                    or next_command_id <= next_command_id_after_for_loop
                ),
            )
        first_command_id = first_command_id_after_shell_text
    return checked_counts, violation_counts


def first_character_kind_of(text: str) -> str:
    """Name the kind of the first character of a text, i.e. `letter`, `digit`, `whitespace`, `control`, the ASCII punctuation mark itself, `other` or `empty`, which shows no task content.

    A control character such as NUL gets a name, so that no raw control character reaches a CSV.
    """
    if not text:
        return "empty"
    character = text[0]
    if character.isalpha():
        return "letter"
    if character.isdigit():
        return "digit"
    if character.isspace():
        return "whitespace"
    if not character.isprintable():
        return "control"
    if character.isascii():
        return character
    return "other"


def _has_pipe_reader_and_deciding_command_ids_in(
    command: ShellCommand, shell_text_command_ids: set[int]
) -> bool:
    """Tell whether the reader id of each pipe of a command and its deciding command ids are all commands of its shell text, each deciding command before it."""
    reader_ids = [
        destination.reader_id
        for destination in (command.stdout, command.stderr)
        if isinstance(destination, PipeDestination)
    ]
    deciding_command_ids = [
        deciding_command_id
        for run_condition in command.runs_if
        for deciding_command_id in run_condition.deciding_command_ids
    ]
    return all(reader_id in shell_text_command_ids for reader_id in reader_ids) and all(
        deciding_command_id in shell_text_command_ids
        and deciding_command_id < command.id
        for deciding_command_id in deciding_command_ids
    )


def _has_expansion_word_indexes_at_expansions(command: ShellCommand) -> bool:
    """Tell whether the `expansion_word_indexes` of a command rise, stay below its number of words and point at words with an expansion mark."""
    indexes = command.expansion_word_indexes
    return (
        all(earlier < later for earlier, later in itertools.pairwise(indexes))
        and all(0 <= index < len(command.words) for index in indexes)
        and all(
            any(mark in command.words[index] for mark in _EXPANSION_MARKS)
            for index in indexes
            if 0 <= index < len(command.words)
        )
    )


def _text_of_tool_call_key(tool_call_key: ToolCallKey) -> str:
    """Write a tool call key as one CSV value, its trajectory id, step id and 0-based call index joined by `:`."""
    return (
        f"{tool_call_key.trajectory_id}:{tool_call_key.step_id}"
        f":{tool_call_key.call_index}"
    )


if __name__ == "__main__":
    main()
