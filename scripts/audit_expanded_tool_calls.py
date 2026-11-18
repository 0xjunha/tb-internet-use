"""Run `convert_tool_calls` and `expand_tool_calls` on raw trials, count what the expansion holds per harness and check the equations that the expansion must meet.

An equation sets a count of the output beside a count that this script takes another way, e.g. from the `ToolCall`s, from the words of the commands or from the counts of the door, so that a text, a command or a use that the expansion dropped or made twice shows as a difference.
An equation whose right side is 0 counts values that break a rule that holds whatever the data, e.g. an `OutputPlace` that points at a call outside the trial.
Every equation starts at 0 for every trial, so that one the trials never reach still shows.

| Equation | Left | Right |
|---|---|---|
| `expanded_calls_equal_tool_calls` | `ExpandedToolCall`s | Those equal in place to a `ToolCall` of a second run of `convert_tool_calls` |
| `expanded_calls_equal_tool_calls_in_number` | `ExpandedToolCall`s | `ToolCall`s of a second run of `convert_tool_calls` |
| `ran_commands_equal_commands_of_call_texts` | `ShellCommand`s of the `parsed_shell_text` of each `RunCommandAction`, script steps included | `RanCommand`s of the texts whose source is `CallCommandText` or `ScriptStepText` |
| `missing_texts_equal_command_actions_without_text` | `RunCommandAction`s without a command string | `UnknownRanText`s of reason `MISSING_FROM_TRAJECTORY` |
| `unreadable_texts_equal_unreadable_call_texts` | `UnreadableShellText`s of the `RunCommandAction`s | `UnknownRanText`s of reason `UNREADABLE_SHELL_TEXT` whose source is `CallCommandText` or `ScriptStepText` |
| `commands_of_runner_names_fall_in_a_branch` | Commands whose first word, without its folder, is one of `RUNNER_NAMES` | Those with a ran text whose runner is the command, plus four branches, i.e. unread words, a next program, no argument and no stdin, a program without a row |
| `program_invocations_hold_the_words_of_their_command` | Commands | Commands whose words and program invocations hold the same characters, `-` and `=` left out |
| `cat_arguments_equal_file_uses` | Arguments of `cat`, with variables of one sure value filled, or its stdin file when no argument names a file, that are no glob, no `-`, no repeat of the file of an earlier one and no harness output file | Uses of a file without a known writer plus groups of `FileUse`s of the same command, i.e. of written files that can name one file or that one argument fits when the path fits several |
| `unknown_program_invocations_equal_unknown_program_lookups` | `UnknownProgramInvocation`s | Unknown inputs of `program_behaviors.csv` plus program words that are expansions |
| `unread_words_equal_unknown_option_lookups` | `ProgramInvocation`s with unread words, plus those whose unread option cluster word without a row comes after an unread option without a row, which give a second unknown input | Unknown inputs of `program_option_behaviors.csv` plus blank `options_end_at_first_argument` cells that left a word unread, i.e. unknown inputs under `BLANK_PROGRAM_BEHAVIOR_CELLS`, plus options with a row that take a value and are the last word, which give none |
| `pointers_stay_inside_trial` | `OutputPlace`s and `FileUse`s | Those whose call is in the trial and whose command ids are commands of that call |
| `routes_without_pipe_reader_are_whole` | `OutputRoute`s without a pipe reader | Those that are `WHOLE` |
| `route_visibility_follows_pipe_readers` | `OutputRoute`s with a pipe reader | Those whose visibility this script gets again from the rows of the readers |
| `values_in_turn_only_in_loops` | `VariableValues` taken in turn | Those of a command in a loop body |
| `tool_written_files_equal_tool_paths` | `WrittenFile`s written by a tool argument | Distinct paths of the `WriteFileAction`s and `EditFileAction`s of the same call |
| `file_text_writers_hold_the_file` | `FileText`s | Those whose writer is of the same trajectory and holds a written file of that path |
| `calls_not_run_reach_nothing` | Values that tie a call that did not run to its output or to a later call | 0 |
| `harness_output_file_reads_are_output_places` | Later calls of the same trajectory that read an `output_path` | `OutputPlace`s of such reading calls |
| `harness_output_file_reads_are_no_uses_without_writer` | Uses of a file without a known writer that read an earlier `output_path` | 0 |
| `poll_inputs_fall_in_a_branch` | `PollAction`s with an input | Uses of `treat_input_of_key_presses_only_as_no_text`, plus texts from a poll input, plus inputs typed into a program whose row gives its stdin a known role other than `run_text` |
| `other_trajectory_rule_uses_equal_recount` | Uses of `treat_calls_of_other_trajectory_as_not_linked` | Runs and uses that only another trajectory fits, counted again here |
| `pointers_stay_inside_trajectory` | `FileUse`s, `FileText`s, `PollInputText`s and `OutputPlace`s | Those that point at a call of the same trajectory |
| `judgment_rule_names_are_of_this_step` | Names counted in the counter of `expand_tool_calls` | Those of `expanded_tool_call/judgment_rules.py` and `treat_lines_joined_after_three_repairs_as_left_joined` |

It writes these CSVs under the output folder, `out/expanded_tool_call/` unless `--out-dir` names another, which `.gitignore` keeps out of the repo.
They hold counts, harness names, trial ids, exception type names, program and option names of the catalogs and of the commands, never other text from a trajectory.

| File | One row |
|---|---|
| `trial_outcomes.csv` | An outcome of a trial, e.g. `expanded`, `not found` or `exception` with its type name, with its trials and the first 20 trial ids, or the trial ids given more than once, which run once |
| `trials_not_expanded.csv` | A trial that was not expanded, with its outcome |
| `counts_by_harness.csv` | A harness, or `all`, with a count of the output, e.g. ran texts by source |
| `equations.csv` | An equation of the table, with its two sides and whether they are equal |
| `equation_examples.csv` | A call where an equation differs, the first 20 per equation |
| `judgment_rule_uses.csv` | A judgment rule, with its uses and trials |
| `knowledge_row_uses.csv` | A row of a catalog of `ExpandedToolCallKnowledge`, with its uses and trials |
| `unknown_inputs.csv` | A program or option without a row, or a blank cell of a program row that left a word unread, with its lookups, i.e. commands, its trials and its tasks, most lookups first |
| `unknown_touch_programs.csv` | A program whose commands made a file use of unknown kind, changed a followed file text so that it is unknown, or read a pipe whose visibility is unknown, with those commands, their trials and their tasks. A tool that made a use of unknown kind counts as one command of its call |

The script ends with exit code 1 when a trial raised an exception or an equation differs.
Run it as `nice -n 10 uv run python -I scripts/audit_expanded_tool_calls.py <raw_trials_dir> [--limit N | --trial-ids FILE] [--out-dir DIR]`.
"""

import argparse
import functools
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from tb_internet_use.expanded_tool_call import judgment_rules
from tb_internet_use.expanded_tool_call.model import (
    ArgumentText,
    CallCommandText,
    ExpandedToolCall,
    FileText,
    FileTextWithoutKnownWriter,
    FileUseKind,
    FileWriteChannel,
    OutputRoute,
    OutputVisibility,
    PollInputText,
    ProgramBehavior,
    ProgramInvocation,
    ProgramOptionWord,
    ProgramWordRole,
    RanCodeText,
    RanCommand,
    RanShellText,
    ScriptStepText,
    StdinText,
    UnknownOptionsEndAtFirstArgument,
    UnknownProgramBehavior,
    UnknownProgramInvocation,
    UnknownProgramOptionWord,
    UnknownProgramWordRole,
    UnknownRanText,
    UnknownRanTextReason,
)
from tb_internet_use.knowledge.catalog import KnowledgeUses, KnowledgeUsesTotal
from tb_internet_use.knowledge.expanded_tool_call_knowledge import (
    BLANK_PROGRAM_BEHAVIOR_CELLS,
    PROGRAM_BEHAVIORS_CSV,
    PROGRAM_OPTION_BEHAVIORS_CSV,
    ExpandedToolCallKnowledge,
)
from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge
from tb_internet_use.pipeline import (
    KnowledgeDoors,
    read_trajectory,
    read_trial_file_texts,
    run_steps_to_expanded_tool_calls,
)
from tb_internet_use.tool_call import convert_tool_calls
from tb_internet_use.tool_call.judgment_rules import (
    treat_lines_joined_after_three_repairs_as_left_joined,
)
from tb_internet_use.tool_call.model import (
    EditFileAction,
    ExecutionHandle,
    ExecutionStatus,
    PipeDestination,
    PollAction,
    ReadFileAction,
    ResultDestination,
    RunCommandAction,
    SearchFilesAction,
    ShellCommand,
    ToolCall,
    ToolCallKey,
    UnreadableShellText,
    WriteFileAction,
    indexed_action_steps_of,
)
from tb_internet_use.trial import collect_trials
from tb_internet_use.trial.model import UnreadableTrajectory

# `python -I` leaves the folder of this script off `sys.path`, so the script puts it there to import the module beside it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from trial_folders_and_csv_files import (
    PROCESS_COUNT,
    add_trial_choice_arguments,
    chosen_trial_dirs_from,
    write_csv,
)

OUT_DIR = Path(__file__).resolve().parents[1] / "out" / "expanded_tool_call"
# Every equation of the module docstring, in its order, which is also the order of the output.
EQUATIONS = (
    "expanded_calls_equal_tool_calls",
    "expanded_calls_equal_tool_calls_in_number",
    "ran_commands_equal_commands_of_call_texts",
    "missing_texts_equal_command_actions_without_text",
    "unreadable_texts_equal_unreadable_call_texts",
    "commands_of_runner_names_fall_in_a_branch",
    "program_invocations_hold_the_words_of_their_command",
    "cat_arguments_equal_file_uses",
    "unknown_program_invocations_equal_unknown_program_lookups",
    "unread_words_equal_unknown_option_lookups",
    "pointers_stay_inside_trial",
    "routes_without_pipe_reader_are_whole",
    "route_visibility_follows_pipe_readers",
    "values_in_turn_only_in_loops",
    "tool_written_files_equal_tool_paths",
    "file_text_writers_hold_the_file",
    "calls_not_run_reach_nothing",
    "harness_output_file_reads_are_output_places",
    "harness_output_file_reads_are_no_uses_without_writer",
    "poll_inputs_fall_in_a_branch",
    "other_trajectory_rule_uses_equal_recount",
    "pointers_stay_inside_trajectory",
    "judgment_rule_names_are_of_this_step",
)
# The two sides of an equation, as `equations.csv` names them.
_SIDES = ("left", "right")
# The trial outcome of a trial that ran through both steps.
EXPANDED = "expanded"
# The trial outcome of an id that names no folder under the raw trials folder.
NOT_FOUND = "not found"
# The row of `trial_outcomes.csv` that counts the trial ids given more than once.
REPEATED_TRIAL_IDS = "repeated trial id, run once"
# The examples kept per equation and per trial outcome, so that the CSVs stay short.
_EXAMPLE_LIMIT = 20
# The program names that this script counts by their first word without asking the door.
RUNNER_NAMES = frozenset(
    {"bash", "sh", "python", "python3", "node", "make", "source", "."}
)
# The characters that a glob of a word holds, which the expansion does not read as one file.
_GLOB_CHARACTERS = ("*", "?", "[", "{")
# The word that stands for stdin instead of a file, e.g. in `python -` or `cat - log`.
_STDIN_WORD = "-"
# A variable in braces, e.g. `${D}` of `${D}/f.sh`, whose braces make no brace list.
_PARAMETER_IN_BRACES = re.compile(r"\$\{[^}]*\}")
# A variable as `$NAME` or `${NAME}`, filled where it has one sure value.
_PLAIN_VARIABLE = re.compile(r"\$(?:\{(\w+)\}|(\w+))")
# The characters of typed input that only presses keys, i.e. space, Enter, Ctrl-C and Ctrl-D, written again here so that the recount does not go through the code it checks.
_KEY_PRESS_CHARACTERS = " \n\x03\x04"
# The rule names that the counter of `expand_tool_calls` may hold.
JUDGMENT_RULE_NAMES = frozenset(
    {
        name
        for name in dir(judgment_rules)
        if name.startswith("treat_") and callable(getattr(judgment_rules, name))
    }
    | {treat_lines_joined_after_three_repairs_as_left_joined.__name__}
)
_VERSION_AT_END = re.compile(r"-?\d+(?:\.\d+)*$")
# A leading part of a path that stands for a folder the text does not show, i.e. one that starts with `$`, e.g. `$LOG` or `$(dirname "$0")`, `~` or `..`.
_UNSHOWN_FOLDER_PART = re.compile(r"^(?:\$|~|\.\.$)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    add_trial_choice_arguments(parser)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    arguments = parser.parse_args()

    chosen_trial_dirs = chosen_trial_dirs_from(arguments)
    trial_dirs = list(dict.fromkeys(chosen_trial_dirs))
    total = TrialAuditTotal()
    total.add_repeated_trial_ids(chosen_trial_dirs)
    with ProcessPoolExecutor(PROCESS_COUNT) as pool:
        for trial_audit in pool.map(audit_trial, trial_dirs, chunksize=5):
            total.add_trial(trial_audit)
    write_audit_files(total, arguments.out_dir)
    print(f"trials: {dict(sorted(total.outcome_counts.items()))}")
    if total.repeated_trial_ids:
        print(
            f"{REPEATED_TRIAL_IDS}: {len(total.repeated_trial_ids)} ({' '.join(total.repeated_trial_ids[:_EXAMPLE_LIMIT])})"
        )
    for equation, left, right in total.equation_rows():
        print(f"{equation}: {left} = {right} {'holds' if left == right else 'differs'}")
    print(f"written under {arguments.out_dir}")
    if total.has_exception_or_differing_equation():
        sys.exit(1)


def write_audit_files(total: TrialAuditTotal, out_dir: Path) -> None:
    """Write the CSVs of the module docstring from the sum of the trials."""
    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(
        out_dir / "trial_outcomes.csv",
        ("outcome", "trial_count", "first_trial_ids"),
        [
            (outcome, count, " ".join(total.trial_id_examples_by_outcome[outcome]))
            for outcome, count in sorted(total.outcome_counts.items())
        ]
        + (
            [
                (
                    REPEATED_TRIAL_IDS,
                    len(total.repeated_trial_ids),
                    " ".join(total.repeated_trial_ids[:_EXAMPLE_LIMIT]),
                )
            ]
            if total.repeated_trial_ids
            else []
        ),
    )
    write_csv(
        out_dir / "trials_not_expanded.csv",
        ("trial_id", "outcome"),
        total.trials_not_expanded,
    )
    write_csv(
        out_dir / "counts_by_harness.csv",
        ("harness", "count_name", "count"),
        (
            (harness, count_name, count)
            for (harness, count_name), count in sorted(total.counts.items())
        ),
    )
    write_csv(
        out_dir / "equations.csv",
        ("equation", "left", "right", "holds"),
        (
            (equation, left, right, "yes" if left == right else "no")
            for equation, left, right in total.equation_rows()
        ),
    )
    write_csv(
        out_dir / "equation_examples.csv",
        ("equation", "trial_id", "tool_call_key"),
        total.equation_examples,
    )
    write_csv(
        out_dir / "judgment_rule_uses.csv",
        ("judgment_rule", "use_count", "trial_count"),
        (
            (name, count, total.judgment_rule_trial_counts[name])
            for name, count in total.judgment_rule_use_counts.most_common()
        ),
    )
    uses_total = total.knowledge_uses_total
    write_csv(
        out_dir / "knowledge_row_uses.csv",
        ("catalog", "row_key", "use_count", "trial_count"),
        (
            (
                catalog,
                " ".join(row_key),
                count,
                uses_total.row_trial_counts[catalog, row_key],
            )
            for (catalog, row_key), count in uses_total.row_use_counts.most_common()
        ),
    )
    write_csv(
        out_dir / "unknown_inputs.csv",
        (
            "catalog",
            "program_name",
            "subcommand",
            "option_name",
            "command_count",
            "trial_count",
            "task_count",
        ),
        (
            (
                catalog,
                *_cells_of_row_key(row_key, 3),
                count,
                uses_total.unknown_input_trial_counts[catalog, row_key],
                len(total.unknown_input_tasks[catalog, row_key]),
            )
            for (catalog, row_key), count in sorted(
                uses_total.unknown_input_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
    )
    write_csv(
        out_dir / "unknown_touch_programs.csv",
        ("list", "program_name", "command_count", "trial_count", "task_count"),
        (
            (
                list_name,
                program_name,
                count,
                len(total.unknown_touch_trials[list_name, program_name]),
                len(total.unknown_touch_tasks[list_name, program_name]),
            )
            for (list_name, program_name), count in sorted(
                total.unknown_touch_command_counts.items(),
                key=lambda item: (item[0][0], -item[1], item[0][1]),
            )
        ),
    )


def _cells_of_row_key(row_key: Sequence[str], length: int) -> tuple[str, ...]:
    """Give the cells of a row key with empty cells after it up to `length`, e.g. a program key in the option columns."""
    return (*row_key, *([""] * (length - len(row_key))))


def audit_trial(trial_dir: Path) -> TrialAudit:
    """Run the steps up to `expand_tool_calls` on one trial, then count and check its expanded calls, with an exception named instead of raised."""
    if not trial_dir.is_dir():
        return TrialAudit(trial_dir.name, NOT_FOUND)
    try:
        harness_tool_calls = read_trajectory(trial_dir)
        if isinstance(harness_tool_calls, UnreadableTrajectory):
            return TrialAudit(trial_dir.name, f"unreadable {harness_tool_calls.reason}")
        (trial,) = collect_trials([read_trial_file_texts(trial_dir)], {})
        process_doors = process_doors_of_worker()
        knowledge_doors = process_doors.knowledge_doors
        # The doors serve every trial of the worker process, so their uses start empty for each trial.
        knowledge_doors.tool_call_knowledge.uses = KnowledgeUses()
        knowledge_doors.expanded_tool_call_knowledge.uses = KnowledgeUses()
        judgment_rule_use_counts: Counter[str] = Counter()
        expanded_tool_calls = run_steps_to_expanded_tool_calls(
            harness_tool_calls,
            knowledge_doors=knowledge_doors,
            tool_call_judgment_rule_use_counts=Counter(),
            expanded_tool_call_judgment_rule_use_counts=judgment_rule_use_counts,
        )
        tool_calls = convert_tool_calls(
            harness_tool_calls,
            knowledge=process_doors.second_tool_call_knowledge,
            judgment_rule_use_counts=Counter(),
        )
        trial_audit = TrialAudit(
            trial_dir.name,
            EXPANDED,
            harness=trial.harness,
            task=f"{trial.benchmark_version} {trial.task_name}",
            judgment_rule_use_counts=judgment_rule_use_counts,
            knowledge_uses=knowledge_doors.expanded_tool_call_knowledge.uses,
        )
        TrialChecker(
            trial_audit,
            tool_calls,
            expanded_tool_calls,
            process_doors.own_expanded_tool_call_knowledge,
        ).check()
    except Exception as error:  # noqa: BLE001, one trial must not stop the run
        return TrialAudit(trial_dir.name, f"exception {type(error).__name__}")
    return trial_audit


@dataclass(frozen=True, slots=True)
class ProcessDoors:
    """Doors of outside knowledge made once in each worker process and used for each of its trials, since reading the catalogs again for each trial is slow."""

    # The doors that the steps ask.
    knowledge_doors: KnowledgeDoors = field(default_factory=KnowledgeDoors)
    # The door of the second run of `convert_tool_calls`, whose lookups count nowhere.
    second_tool_call_knowledge: ToolCallKnowledge = field(
        default_factory=ToolCallKnowledge
    )
    # The door that `TrialChecker` asks for the rows of pipe readers and of the programs that typed text goes to, so that its lookups do not count as lookups of the step.
    own_expanded_tool_call_knowledge: ExpandedToolCallKnowledge = field(
        default_factory=ExpandedToolCallKnowledge
    )


@functools.cache
def process_doors_of_worker() -> ProcessDoors:
    """Give the doors of this worker process, made at its first trial."""
    return ProcessDoors()


@dataclass(slots=True)
class TrialAudit:
    """Result of auditing one trial, sent from a worker process to the main process that sums the trials."""

    trial_id: str
    # `expanded`, `not found`, `unreadable` with the reason, or `exception` with the type name.
    outcome: str
    harness: str = ""
    # The benchmark version and the task name, which together name a task.
    task: str = ""
    # By (harness or `all`, count name).
    counts: Counter[tuple[str, str]] = field(default_factory=Counter)
    # By (equation, `left` or `right`), every side at 0 before the trial adds to it.
    equation_sides: Counter[tuple[str, str]] = field(
        default_factory=lambda: Counter(
            dict.fromkeys(
                ((equation, side) for equation in EQUATIONS for side in _SIDES), 0
            )
        )
    )
    # (equation, tool call key) of each call where an equation differs.
    equation_examples: list[tuple[str, str]] = field(default_factory=list)
    judgment_rule_use_counts: Counter[str] = field(default_factory=Counter)
    knowledge_uses: KnowledgeUses = field(default_factory=KnowledgeUses)
    # By (list, program name), the commands that made an unknown touch, each as the text of its tool call key and its command id.
    unknown_touch_commands: dict[tuple[str, str], set[str]] = field(
        default_factory=dict
    )

    def count(self, count_name: str, amount: int = 1) -> None:
        """Add to a count of the trial's harness and of all harnesses."""
        self.counts[self.harness, count_name] += amount
        self.counts["all", count_name] += amount

    def add_sides(
        self, equation: str, left: int, right: int, tool_call_key: ToolCallKey | None
    ) -> None:
        """Add the two sides of an equation for one call or one trial, keeping the call as an example when they differ."""
        if equation not in EQUATIONS:
            raise ValueError(f"no equation {equation}")
        self.equation_sides[equation, "left"] += left
        self.equation_sides[equation, "right"] += right
        if left != right:
            self.equation_examples.append(
                (
                    equation,
                    ""
                    if tool_call_key is None
                    else _text_of_tool_call_key(tool_call_key),
                )
            )

    def add_unknown_touch(
        self,
        list_name: str,
        program_name: str,
        tool_call_key: ToolCallKey,
        command_id: int | None,
    ) -> None:
        """Record the command, or the tool of a call when `command_id` is None, that made one unknown touch of a list."""
        self.unknown_touch_commands.setdefault((list_name, program_name), set()).add(
            f"{_text_of_tool_call_key(tool_call_key)}:{command_id}"
        )


@dataclass(slots=True)
class TrialAuditTotal:
    """Sum of the `TrialAudit` of many trials, built by `main` to write the CSVs."""

    outcome_counts: Counter[str] = field(default_factory=Counter)
    trial_id_examples_by_outcome: dict[str, list[str]] = field(default_factory=dict)
    # (trial id, outcome) of each trial whose outcome is not `expanded`.
    trials_not_expanded: list[tuple[str, str]] = field(default_factory=list)
    # The trial ids given more than once, once each.
    repeated_trial_ids: list[str] = field(default_factory=list)
    counts: Counter[tuple[str, str]] = field(default_factory=Counter)
    equation_sides: Counter[tuple[str, str]] = field(default_factory=Counter)
    equation_examples: list[tuple[str, str, str]] = field(default_factory=list)
    judgment_rule_use_counts: Counter[str] = field(default_factory=Counter)
    judgment_rule_trial_counts: Counter[str] = field(default_factory=Counter)
    knowledge_uses_total: KnowledgeUsesTotal = field(default_factory=KnowledgeUsesTotal)
    unknown_input_tasks: dict[tuple[str, tuple[str, ...]], set[str]] = field(
        default_factory=dict
    )
    unknown_touch_command_counts: Counter[tuple[str, str]] = field(
        default_factory=Counter
    )
    unknown_touch_trials: dict[tuple[str, str], set[str]] = field(default_factory=dict)
    unknown_touch_tasks: dict[tuple[str, str], set[str]] = field(default_factory=dict)

    def add_repeated_trial_ids(self, trial_dirs: Sequence[Path]) -> None:
        """Note each trial folder that the chosen folders hold more than once, which `main` runs once."""
        self.repeated_trial_ids += [
            trial_dir.name
            for trial_dir, count in Counter(trial_dirs).items()
            if count > 1
        ]

    def add_trial(self, trial_audit: TrialAudit) -> None:
        """Add what one trial counted, keeping the first examples of each outcome and equation."""
        self.outcome_counts[trial_audit.outcome] += 1
        trial_ids = self.trial_id_examples_by_outcome.setdefault(
            trial_audit.outcome, []
        )
        if len(trial_ids) < _EXAMPLE_LIMIT:
            trial_ids.append(trial_audit.trial_id)
        if trial_audit.outcome != EXPANDED:
            self.trials_not_expanded.append((trial_audit.trial_id, trial_audit.outcome))
        self.counts.update(trial_audit.counts)
        self.equation_sides.update(trial_audit.equation_sides)
        for equation, tool_call_key in trial_audit.equation_examples:
            kept = sum(
                1 for example in self.equation_examples if example[0] == equation
            )
            if kept < _EXAMPLE_LIMIT:
                self.equation_examples.append(
                    (equation, trial_audit.trial_id, tool_call_key)
                )
        self.judgment_rule_use_counts.update(trial_audit.judgment_rule_use_counts)
        self.judgment_rule_trial_counts.update(
            trial_audit.judgment_rule_use_counts.keys()
        )
        self.knowledge_uses_total.add_trial(trial_audit.knowledge_uses)
        for lookup_key in trial_audit.knowledge_uses.unknown_input_counts:
            self.unknown_input_tasks.setdefault(lookup_key, set()).add(trial_audit.task)
        for touch_key, commands in trial_audit.unknown_touch_commands.items():
            self.unknown_touch_command_counts[touch_key] += len(commands)
            self.unknown_touch_trials.setdefault(touch_key, set()).add(
                trial_audit.trial_id
            )
            self.unknown_touch_tasks.setdefault(touch_key, set()).add(trial_audit.task)

    def equation_rows(self) -> list[tuple[str, int, int]]:
        """List each equation with its two sides, in the order of `EQUATIONS`."""
        return [
            (
                equation,
                self.equation_sides[equation, "left"],
                self.equation_sides[equation, "right"],
            )
            for equation in EQUATIONS
        ]

    def has_exception_or_differing_equation(self) -> bool:
        """Tell whether a trial raised an exception or the two sides of an equation differ, which makes `main` end with exit code 1."""
        return any(
            outcome.startswith("exception") for outcome in self.outcome_counts
        ) or any(left != right for _, left, right in self.equation_rows())


class TrialChecker:
    """Checker of the expanded calls of one trial, which adds its counts and the sides of each equation to a `TrialAudit`.

    It reads only the public types of the steps and asks its own door for the rows of pipe readers and of the programs that typed text goes to, so its recounts do not go through the code they check.
    """

    def __init__(
        self,
        trial_audit: TrialAudit,
        tool_calls: Sequence[ToolCall],
        expanded_tool_calls: Sequence[ExpandedToolCall],
        own_knowledge: ExpandedToolCallKnowledge,
    ) -> None:
        self.trial_audit = trial_audit
        self.tool_calls = tool_calls
        self.expanded_tool_calls = expanded_tool_calls
        self.own_knowledge = own_knowledge
        self.expanded_tool_call_by_key = {
            expanded_tool_call.tool_call.harness_tool_call.key: expanded_tool_call
            for expanded_tool_call in expanded_tool_calls
        }
        self.call_index_by_key = {
            tool_call_key: call_index
            for call_index, tool_call_key in enumerate(self.expanded_tool_call_by_key)
        }

    def check(self) -> None:
        """Count the trial and check every equation of `EQUATIONS`."""
        trial_audit = self.trial_audit
        trial_audit.add_sides(
            "expanded_calls_equal_tool_calls",
            len(self.expanded_tool_calls),
            sum(
                expanded_tool_call.tool_call == tool_call
                for expanded_tool_call, tool_call in zip(
                    self.expanded_tool_calls, self.tool_calls, strict=False
                )
            ),
            None,
        )
        trial_audit.add_sides(
            "expanded_calls_equal_tool_calls_in_number",
            len(self.expanded_tool_calls),
            len(self.tool_calls),
            None,
        )
        for call_index, expanded_tool_call in enumerate(self.expanded_tool_calls):
            self.count_call(expanded_tool_call)
            self.check_call_texts(expanded_tool_call)
            self.check_commands(expanded_tool_call)
            self.check_pointers(expanded_tool_call)
            self.check_written_files(expanded_tool_call)
            self.check_call_not_run(expanded_tool_call)
            self.check_poll_inputs(call_index, expanded_tool_call)
        self.check_harness_output_file_reads()
        self.check_other_trajectories()
        # The inputs of key presses only make no text, and the expansion counts each in the use of this rule.
        trial_audit.add_sides(
            "poll_inputs_fall_in_a_branch",
            0,
            trial_audit.judgment_rule_use_counts[
                judgment_rules.treat_input_of_key_presses_only_as_no_text.__name__
            ],
            None,
        )
        trial_audit.add_sides(
            "judgment_rule_names_are_of_this_step",
            len(trial_audit.judgment_rule_use_counts),
            sum(
                name in JUDGMENT_RULE_NAMES
                for name in trial_audit.judgment_rule_use_counts
            ),
            None,
        )
        trial_audit.add_sides(
            "unknown_program_invocations_equal_unknown_program_lookups",
            trial_audit.counts["all", "unknown_program_invocations"],
            sum(
                count
                for (
                    catalog,
                    _,
                ), count in trial_audit.knowledge_uses.unknown_input_counts.items()
                if catalog == PROGRAM_BEHAVIORS_CSV
            )
            + trial_audit.counts["all", "program_words_that_are_expansions"],
            None,
        )
        trial_audit.add_sides(
            "unread_words_equal_unknown_option_lookups",
            trial_audit.counts["all", "program_invocations_with_unread_words"]
            + trial_audit.counts[
                "all", "unread option clusters after an unread option"
            ],
            trial_audit.counts["all", "unread options that take a value written last"]
            + sum(
                count
                for (
                    catalog,
                    _,
                ), count in trial_audit.knowledge_uses.unknown_input_counts.items()
                if catalog
                in (PROGRAM_OPTION_BEHAVIORS_CSV, BLANK_PROGRAM_BEHAVIOR_CELLS)
            ),
            None,
        )

    def count_call(self, expanded_tool_call: ExpandedToolCall) -> None:
        """Count the fields of one expanded call by kind."""
        trial_audit = self.trial_audit
        tool_call_key = expanded_tool_call.tool_call.harness_tool_call.key
        trial_audit.count("calls")
        for ran_text in expanded_tool_call.ran_texts:
            source_name = type(ran_text.source).__name__
            if isinstance(ran_text, RanShellText):
                trial_audit.count(f"ran_texts shell from {source_name}")
                trial_audit.count("commands", len(ran_text.ran_commands))
            elif isinstance(ran_text, RanCodeText):
                trial_audit.count(
                    f"ran_texts {ran_text.code_language} from {source_name}"
                )
            else:
                trial_audit.count(
                    f"ran_texts unknown {ran_text.reason} from {source_name}"
                )
                if ran_text.reason == UnknownRanTextReason.CHANGED_BY_UNREAD_COMMAND:
                    self.count_changing_program(tool_call_key, ran_text)
        for output_place in expanded_tool_call.output_places:
            place_kind = (
                "own result"
                if output_place.showing_tool_call_key == tool_call_key
                else "later call"
            )
            trial_audit.count(f"output_places in {place_kind}")
        for written_file in expanded_tool_call.written_files:
            trial_audit.count("written_files")
            for writer in written_file.writers:
                trial_audit.count(f"written_file_writers {writer.channel}")
            for file_use in written_file.file_uses:
                trial_audit.count(f"file_uses {file_use.kind}")
                trial_audit.count(
                    "file_uses fitting several written files",
                    file_use.fits_several_written_files,
                )
                if file_use.kind == FileUseKind.UNKNOWN:
                    self.add_unknown_touch_of_command(
                        "file use of unknown kind",
                        file_use.using_tool_call_key,
                        file_use.command_id,
                    )
        for file_use in expanded_tool_call.file_uses_without_known_writer:
            trial_audit.count(f"file_uses_without_known_writer {file_use.kind}")
        if expanded_tool_call.command_text_status is not None:
            trial_audit.count(
                f"command_text_status {expanded_tool_call.command_text_status.execution_status}"
            )

    def count_changing_program(
        self, tool_call_key: ToolCallKey, ran_text: UnknownRanText
    ) -> None:
        """Record the command that made a followed file text unknown, i.e. the last writer in the writer's call that changes the file itself, or else the last use of unknown kind of the file, or else the command that ran the text."""
        source = ran_text.source
        if not isinstance(source, FileText) or source.path is None:
            return
        writer_call = self.expanded_tool_call_by_key.get(source.writer_tool_call_key)
        if writer_call is None:
            return
        matching_written_files = [
            written_file
            for written_file in writer_call.written_files
            if _is_same_file(written_file.path, source.path)
        ]
        own_output_writer_command_ids = [
            writer.command_id
            for written_file in matching_written_files
            for writer in written_file.writers
            if writer.channel == FileWriteChannel.OWN_OUTPUT_FILE
        ]
        unknown_uses = [
            file_use
            for written_file in matching_written_files
            for file_use in written_file.file_uses
            if file_use.kind == FileUseKind.UNKNOWN
        ]
        if own_output_writer_command_ids:
            self.add_unknown_touch_of_command(
                "file text changed by command",
                source.writer_tool_call_key,
                own_output_writer_command_ids[-1],
            )
        elif unknown_uses:
            self.add_unknown_touch_of_command(
                "file text changed by command",
                unknown_uses[-1].using_tool_call_key,
                unknown_uses[-1].command_id,
            )
        else:
            self.trial_audit.add_unknown_touch(
                "file text changed by command",
                "(no changing command found)",
                tool_call_key,
                source.runner_command_id,
            )

    def add_unknown_touch_of_command(
        self, list_name: str, tool_call_key: ToolCallKey, command_id: int | None
    ) -> None:
        """Record the command that made one unknown touch of a list under its innermost program, or under `(a tool)` when `command_id` is None."""
        ran_command = self.ran_command_of(tool_call_key, command_id)
        program_name = (
            "(a tool)"
            if ran_command is None
            else _innermost_program_name_of(ran_command)
        )
        self.trial_audit.add_unknown_touch(
            list_name, program_name, tool_call_key, command_id
        )

    def ran_command_of(
        self, tool_call_key: ToolCallKey, command_id: int | None
    ) -> RanCommand | None:
        """Find a command of a call by its id."""
        expanded_tool_call = self.expanded_tool_call_by_key.get(tool_call_key)
        if expanded_tool_call is None or command_id is None:
            return None
        return ran_commands_by_id_of(expanded_tool_call).get(command_id)

    def check_call_texts(self, expanded_tool_call: ExpandedToolCall) -> None:
        """Hold the commands, missing texts and unreadable texts of the call's own action against the texts that start from it."""
        trial_audit = self.trial_audit
        tool_call_key = expanded_tool_call.tool_call.harness_tool_call.key
        command_count = missing_count = unreadable_count = 0
        for _, step in indexed_action_steps_of(expanded_tool_call.tool_call.action):
            if not isinstance(step, RunCommandAction):
                continue
            if step.command_str is None:
                missing_count += 1
            elif isinstance(step.parsed_shell_text, UnreadableShellText):
                unreadable_count += 1
            elif step.parsed_shell_text is not None:
                command_count += len(step.parsed_shell_text.commands)
        own_sources = (CallCommandText, ScriptStepText)
        trial_audit.add_sides(
            "ran_commands_equal_commands_of_call_texts",
            command_count,
            sum(
                len(ran_text.ran_commands)
                for ran_text in expanded_tool_call.ran_texts
                if isinstance(ran_text, RanShellText)
                and isinstance(ran_text.source, own_sources)
            ),
            tool_call_key,
        )
        trial_audit.add_sides(
            "missing_texts_equal_command_actions_without_text",
            missing_count,
            _unknown_ran_text_count_of(
                expanded_tool_call,
                UnknownRanTextReason.MISSING_FROM_TRAJECTORY,
                own_sources,
            ),
            tool_call_key,
        )
        trial_audit.add_sides(
            "unreadable_texts_equal_unreadable_call_texts",
            unreadable_count,
            _unknown_ran_text_count_of(
                expanded_tool_call,
                UnknownRanTextReason.UNREADABLE_SHELL_TEXT,
                own_sources,
            ),
            tool_call_key,
        )

    def check_commands(self, expanded_tool_call: ExpandedToolCall) -> None:
        """Check the words, routes and values of each command of one call."""
        trial_audit = self.trial_audit
        tool_call_key = expanded_tool_call.tool_call.harness_tool_call.key
        ran_commands = list(ran_commands_by_id_of(expanded_tool_call).values())
        runner_command_ids = {
            ran_text.source.runner_command_id
            for ran_text in expanded_tool_call.ran_texts
            if isinstance(
                ran_text.source,
                FileText | FileTextWithoutKnownWriter | StdinText | ArgumentText,
            )
        }
        pipe_reader_ids = {
            destination.reader_id
            for ran_command in ran_commands
            for destination in (
                ran_command.shell_command.stdout,
                ran_command.shell_command.stderr,
            )
            if isinstance(destination, PipeDestination)
        }
        for ran_command in ran_commands:
            shell_command = ran_command.shell_command
            for program_invocation in ran_command.program_invocations:
                if isinstance(program_invocation, UnknownProgramInvocation):
                    trial_audit.count("unknown_program_invocations")
                    if _is_expansion_word(
                        shell_command, program_invocation.program_name
                    ):
                        trial_audit.count("program_words_that_are_expansions")
                elif program_invocation.unread_words:
                    trial_audit.count("program_invocations_with_unread_words")
                    self.count_unread_words_beside_lookups(program_invocation)
            if (
                shell_command.words
                and _file_name_of(shell_command.words[0]) in RUNNER_NAMES
            ):
                branch = _runner_name_branch_of(
                    ran_command,
                    shell_command.id in runner_command_ids,
                    shell_command.id in pipe_reader_ids,
                )
                trial_audit.count(f"commands_of_runner_names {branch}")
                trial_audit.add_sides(
                    "commands_of_runner_names_fall_in_a_branch",
                    1,
                    branch != "in no branch",
                    tool_call_key,
                )
            trial_audit.add_sides(
                "program_invocations_hold_the_words_of_their_command",
                1,
                _has_words_of_its_program_invocations(ran_command),
                tool_call_key,
            )
            for variable_values in ran_command.variable_values:
                if variable_values.takes_each_value_in_turn:
                    trial_audit.add_sides(
                        "values_in_turn_only_in_loops",
                        1,
                        shell_command.in_loop_body,
                        tool_call_key,
                    )
            for route in (*ran_command.stdout_routes, *ran_command.stderr_routes):
                self.check_route(route, ran_commands, tool_call_key)
            if self.is_checked_cat_command(expanded_tool_call, ran_command):
                self.check_cat_arguments(expanded_tool_call, ran_command)

    def count_unread_words_beside_lookups(
        self, program_invocation: ProgramInvocation
    ) -> None:
        """Count, by this script's own door, the two shapes of unread words that do not give one unknown input each.

        An option with a row that takes a value and is the last word leaves the word unread with no unknown input, e.g. `-e` of `node -e`.
        An option cluster word without a row, e.g. `cf` of `tar cf - --exclude=x .`, is read after the words after it, so an option without a row among them gives a second unknown input, e.g. `--exclude`, while the words stay unread from the cluster word. Options with a row before it are read as options, e.g. `-C` of `tar xJf a.tar.xz -C out --strip-components=0`.
        """
        program_behavior = self.own_knowledge.program_behavior(
            program_invocation.program_name, program_invocation.subcommand_words
        )
        if isinstance(program_behavior, UnknownProgramBehavior):
            return
        first_unread_word, *later_unread_words = program_invocation.unread_words
        if (
            first_unread_word.startswith("-")
            and not later_unread_words
            and not (
                program_invocation.arguments
                and isinstance(
                    program_behavior.options_end_at_first_argument,
                    UnknownOptionsEndAtFirstArgument,
                )
            )
        ):
            option_word = self.own_knowledge.program_option_word(
                program_behavior, first_unread_word
            )
            if (
                isinstance(option_word, ProgramOptionWord)
                and option_word.options[-1].program_option_behavior.takes_value
                and option_word.options[-1].attached_value is None
            ):
                self.trial_audit.count("unread options that take a value written last")
            return
        if first_unread_word.startswith("-") or not isinstance(
            self.own_knowledge.program_option_word(
                program_behavior, first_unread_word, is_option_cluster=True
            ),
            UnknownProgramOptionWord,
        ):
            return
        if any(
            word.startswith("-")
            and word not in (_STDIN_WORD, "--")
            and isinstance(
                self.own_knowledge.program_option_word(program_behavior, word),
                UnknownProgramOptionWord,
            )
            for word in later_unread_words
        ):
            self.trial_audit.count("unread option clusters after an unread option")

    def check_route(
        self,
        route: OutputRoute,
        ran_commands: Sequence[RanCommand],
        tool_call_key: ToolCallKey,
    ) -> None:
        """Hold the visibility at the end of one route against the rows of its pipe readers."""
        trial_audit = self.trial_audit
        trial_audit.count(
            f"output_routes {type(route.end).__name__} {route.visibility_at_end}"
        )
        if not route.pipe_reader_command_ids:
            trial_audit.add_sides(
                "routes_without_pipe_reader_are_whole",
                1,
                route.visibility_at_end == OutputVisibility.WHOLE,
                tool_call_key,
            )
            return
        ran_command_by_id = {
            ran_command.shell_command.id: ran_command for ran_command in ran_commands
        }
        visibilities = [
            self.visibility_of_piped_input(ran_command_by_id[reader_id])
            if reader_id in ran_command_by_id
            else OutputVisibility.UNKNOWN
            for reader_id in route.pipe_reader_command_ids
        ]
        if OutputVisibility.NONE in visibilities:
            expected = OutputVisibility.NONE
        elif OutputVisibility.UNKNOWN in visibilities:
            expected = OutputVisibility.UNKNOWN
            for reader_id in route.pipe_reader_command_ids:
                if (
                    reader_id in ran_command_by_id
                    and self.visibility_of_piped_input(ran_command_by_id[reader_id])
                    == OutputVisibility.UNKNOWN
                ):
                    self.add_unknown_touch_of_command(
                        "pipe reader of unknown visibility", tool_call_key, reader_id
                    )
        elif OutputVisibility.PARTIAL in visibilities:
            expected = OutputVisibility.PARTIAL
        else:
            expected = OutputVisibility.WHOLE
        trial_audit.add_sides(
            "route_visibility_follows_pipe_readers",
            1,
            route.visibility_at_end == expected,
            tool_call_key,
        )

    def visibility_of_piped_input(self, ran_command: RanCommand) -> OutputVisibility:
        """Get the share that the innermost program of a pipe reader passes on, from the row this script's own door gives."""
        innermost = ran_command.program_invocations[-1]
        if (
            isinstance(innermost, UnknownProgramInvocation)
            or innermost.gets_more_arguments_at_run_time
        ):
            return OutputVisibility.UNKNOWN
        program_behavior = self.own_knowledge.program_behavior(
            innermost.program_name, innermost.subcommand_words
        )
        if isinstance(program_behavior, UnknownProgramBehavior):
            return OutputVisibility.UNKNOWN
        return program_behavior.visibility_of_piped_input

    def is_checked_cat_command(
        self, expanded_tool_call: ExpandedToolCall, ran_command: RanCommand
    ) -> bool:
        """Tell whether a command is one whose arguments `cat_arguments_equal_file_uses` counts, i.e. its innermost program is cat without unread words in a call that may have run."""
        innermost = ran_command.program_invocations[-1]
        return (
            isinstance(innermost, ProgramInvocation)
            and innermost.program_name == "cat"
            and not innermost.unread_words
            and not _is_not_run(expanded_tool_call.tool_call)
        )

    def check_cat_arguments(
        self, expanded_tool_call: ExpandedToolCall, ran_command: RanCommand
    ) -> None:
        """Hold the files that one cat command reads against its uses of files, grouping the `FileUse`s of written files that name one file.

        The files are its arguments, with each variable of one sure value filled, and its stdin file when no argument names a file, e.g. `/dev/tcp/kafka/9092` of `cat < /dev/tcp/kafka/9092`.
        An argument that names a written file that an earlier argument also names is a repeat, since the expansion records one use of a written file per command, e.g. `out/a.txt` and `a.txt` after a write to `a.txt`.
        """
        innermost = ran_command.program_invocations[-1]
        assert isinstance(innermost, ProgramInvocation)
        tool_call_key = expanded_tool_call.tool_call.harness_tool_call.key
        command_id = ran_command.shell_command.id
        output_paths = self.earlier_output_paths_for(tool_call_key)
        words = [_filled_word_of(word, ran_command) for word in innermost.arguments]
        stdin_file_path = ran_command.shell_command.stdin_file_path
        if stdin_file_path is not None and all(word == _STDIN_WORD for word in words):
            words.append(_filled_word_of(stdin_file_path, ran_command))
        uses_without_writer = sum(
            file_use.command_id == command_id
            for file_use in expanded_tool_call.file_uses_without_known_writer
        )
        uses_of_command = [
            (written_file.path, file_use)
            for writer_expanded_tool_call in self.expanded_tool_calls
            for written_file in writer_expanded_tool_call.written_files
            for file_use in written_file.file_uses
            if file_use.using_tool_call_key == tool_call_key
            and file_use.command_id == command_id
        ]
        used_paths = {path for path, _ in uses_of_command}
        seen: set[str] = set()
        counted = 0
        for word in words:
            if any(
                character in _PARAMETER_IN_BRACES.sub("", word)
                for character in _GLOB_CHARACTERS
            ):
                branch = "glob"
            elif word == _STDIN_WORD:
                branch = "stdin"
            elif word in seen or any(
                _is_same_file(word, used_path) and _is_same_file(seen_word, used_path)
                for seen_word in seen
                for used_path in used_paths
            ):
                branch = "repeat"
            elif any(_is_same_file(word, output_path) for output_path in output_paths):
                branch = "harness output file"
            else:
                branch = "other"
                counted += 1
            seen.add(word)
            self.trial_audit.count(f"cat_arguments {branch}")
        counted_words = [word for word in dict.fromkeys(words) if word != _STDIN_WORD]
        several_paths = {
            path
            for path, file_use in uses_of_command
            if file_use.fits_several_written_files
        }
        group_count = _group_count_of(
            list(dict.fromkeys(path for path, _ in uses_of_command)),
            lambda path, other_path: (
                _is_same_file(path, other_path)
                or (
                    path in several_paths
                    and other_path in several_paths
                    and any(
                        _is_same_file(word, path) and _is_same_file(word, other_path)
                        for word in counted_words
                    )
                )
            ),
        )
        self.trial_audit.add_sides(
            "cat_arguments_equal_file_uses",
            counted,
            uses_without_writer + group_count,
            tool_call_key,
        )

    def earlier_output_paths_for(self, tool_call_key: ToolCallKey) -> list[str]:
        """List the `output_path`s of the results of earlier calls of the same trajectory."""
        call_index = self.call_index_by_key[tool_call_key]
        trajectory = _trajectory_of(self.expanded_tool_calls[call_index].tool_call)
        return [
            earlier.tool_call.result.output_path
            for earlier in self.expanded_tool_calls[:call_index]
            if earlier.tool_call.result is not None
            and earlier.tool_call.result.output_path is not None
            and _trajectory_of(earlier.tool_call) == trajectory
        ]

    def check_pointers(self, expanded_tool_call: ExpandedToolCall) -> None:
        """Check that each `OutputPlace` and `FileUse` points at a call of the trial and at commands of that call, and that every pointer stays in its trajectory."""
        tool_call_key = expanded_tool_call.tool_call.harness_tool_call.key
        own_command_ids = set(ran_commands_by_id_of(expanded_tool_call))
        for output_place in expanded_tool_call.output_places:
            self.trial_audit.add_sides(
                "pointers_stay_inside_trial",
                1,
                output_place.showing_tool_call_key in self.expanded_tool_call_by_key
                and set(output_place.command_ids) <= own_command_ids,
                tool_call_key,
            )
            self.add_trajectory_side(tool_call_key, output_place.showing_tool_call_key)
        for written_file in expanded_tool_call.written_files:
            for file_use in written_file.file_uses:
                using_call = self.expanded_tool_call_by_key.get(
                    file_use.using_tool_call_key
                )
                self.trial_audit.add_sides(
                    "pointers_stay_inside_trial",
                    1,
                    using_call is not None
                    and (
                        file_use.command_id is None
                        or file_use.command_id in ran_commands_by_id_of(using_call)
                    ),
                    tool_call_key,
                )
                self.add_trajectory_side(tool_call_key, file_use.using_tool_call_key)
        for ran_text in expanded_tool_call.ran_texts:
            if isinstance(ran_text.source, FileText):
                self.add_trajectory_side(
                    tool_call_key, ran_text.source.writer_tool_call_key
                )
            if (
                isinstance(ran_text.source, PollInputText)
                and ran_text.source.starter_tool_call_key is not None
            ):
                self.add_trajectory_side(
                    tool_call_key, ran_text.source.starter_tool_call_key
                )

    def add_trajectory_side(
        self, tool_call_key: ToolCallKey, pointed_tool_call_key: ToolCallKey
    ) -> None:
        """Add one pointer of a call to `pointers_stay_inside_trajectory`, which holds when the pointed call is of the same trajectory."""
        pointed_expanded_tool_call = self.expanded_tool_call_by_key.get(
            pointed_tool_call_key
        )
        pointing_expanded_tool_call = self.expanded_tool_call_by_key[tool_call_key]
        self.trial_audit.add_sides(
            "pointers_stay_inside_trajectory",
            1,
            pointed_expanded_tool_call is not None
            and _trajectory_of(pointed_expanded_tool_call.tool_call)
            == _trajectory_of(pointing_expanded_tool_call.tool_call),
            tool_call_key,
        )

    def check_written_files(self, expanded_tool_call: ExpandedToolCall) -> None:
        """Hold the files a tool wrote against the paths of its write and edit actions, and check the writer of each followed file."""
        tool_call_key = expanded_tool_call.tool_call.harness_tool_call.key
        tool_paths = {
            step.path
            for _, step in indexed_action_steps_of(expanded_tool_call.tool_call.action)
            if isinstance(step, WriteFileAction | EditFileAction)
            and step.path is not None
        }
        self.trial_audit.add_sides(
            "tool_written_files_equal_tool_paths",
            sum(
                any(
                    writer.channel == FileWriteChannel.TOOL_ARGUMENT
                    for writer in written_file.writers
                )
                for written_file in expanded_tool_call.written_files
            ),
            len(tool_paths),
            tool_call_key,
        )
        for ran_text in expanded_tool_call.ran_texts:
            source = ran_text.source
            if not isinstance(source, FileText):
                continue
            writer_call = self.expanded_tool_call_by_key.get(
                source.writer_tool_call_key
            )
            holds = (
                writer_call is not None
                and _trajectory_of(writer_call.tool_call)
                == _trajectory_of(expanded_tool_call.tool_call)
                and (
                    source.path is None
                    or any(
                        _is_same_file(written_file.path, source.path)
                        for written_file in writer_call.written_files
                    )
                )
            )
            self.trial_audit.add_sides(
                "file_text_writers_hold_the_file", 1, holds, tool_call_key
            )

    def check_call_not_run(self, expanded_tool_call: ExpandedToolCall) -> None:
        """Count the values that tie a call that did not run to its output or to a later call, which must be none."""
        if not _is_not_run(expanded_tool_call.tool_call):
            return
        tool_call_key = expanded_tool_call.tool_call.harness_tool_call.key
        ties = (
            len(expanded_tool_call.output_places)
            + len(expanded_tool_call.file_uses_without_known_writer)
            + sum(
                len(written_file.file_uses)
                for written_file in expanded_tool_call.written_files
            )
            + sum(
                file_use.using_tool_call_key == tool_call_key
                for writer_expanded_tool_call in self.expanded_tool_calls
                for written_file in writer_expanded_tool_call.written_files
                for file_use in written_file.file_uses
            )
            + sum(
                isinstance(ran_text.source, FileText)
                and ran_text.source.writer_tool_call_key == tool_call_key
                for running_expanded_tool_call in self.expanded_tool_calls
                for ran_text in running_expanded_tool_call.ran_texts
            )
        )
        self.trial_audit.count("calls not run")
        self.trial_audit.add_sides(
            "calls_not_run_reach_nothing", ties, 0, tool_call_key
        )

    def check_poll_inputs(
        self, call_index: int, expanded_tool_call: ExpandedToolCall
    ) -> None:
        """Hold the inputs of the poll actions of one call against the branches they fall in, i.e. a text that starts from the input, key presses only, or a program that runs no text as the reader.

        The key presses only are counted on the right by the uses of their rule in `check`, so here they add to the left only.
        The reader is the innermost program of the last command of the own text of the one call that last started each polled handle, and its row comes from this script's own door.
        """
        trial_audit = self.trial_audit
        tool_call_key = expanded_tool_call.tool_call.harness_tool_call.key
        step_indexes_with_text = {
            ran_text.source.step_index
            for ran_text in expanded_tool_call.ran_texts
            if isinstance(ran_text.source, PollInputText)
        }
        for ran_text in expanded_tool_call.ran_texts:
            if isinstance(ran_text.source, PollInputText):
                trial_audit.count(f"poll input texts {type(ran_text).__name__}")
        for step_index, step in indexed_action_steps_of(
            expanded_tool_call.tool_call.action
        ):
            if not isinstance(step, PollAction) or step.input is None:
                continue
            if step_index in step_indexes_with_text:
                branch, right = "a text starts from it", 1
            elif not step.input.strip(_KEY_PRESS_CHARACTERS):
                branch, right = "key presses only", 0
            elif self.is_typed_into_program_that_runs_no_text(call_index, step):
                branch, right = "typed into a program that runs no text", 1
            else:
                branch, right = "in no branch", 0
            trial_audit.count(f"poll inputs {branch}")
            trial_audit.add_sides(
                "poll_inputs_fall_in_a_branch", 1, right, tool_call_key
            )

    def is_typed_into_program_that_runs_no_text(
        self, poll_index: int, poll_action: PollAction
    ) -> bool:
        """Tell whether the reader of a poll's input is a program whose row gives its stdin a known role other than `run_text`, e.g. `cat > notes.txt`."""
        starters = self.latest_starters_of_handles(poll_index, poll_action.handles)
        if len(starters) != 1:
            return False
        own_texts = [
            ran_text
            for ran_text in starters[0].ran_texts
            if isinstance(ran_text, RanShellText)
            and isinstance(ran_text.source, CallCommandText | ScriptStepText)
            and ran_text.ran_commands
        ]
        if not own_texts:
            return False
        reader = own_texts[-1].ran_commands[-1].program_invocations[-1]
        if isinstance(reader, UnknownProgramInvocation):
            return False
        program_behavior = self.own_knowledge.program_behavior(
            reader.program_name, reader.subcommand_words
        )
        return (
            isinstance(program_behavior, ProgramBehavior)
            and not isinstance(program_behavior.stdin_role, UnknownProgramWordRole)
            and program_behavior.stdin_role != ProgramWordRole.RUN_TEXT
        )

    def latest_starters_of_handles(
        self, poll_index: int, handles: Iterable[ExecutionHandle]
    ) -> list[ExpandedToolCall]:
        """Give the distinct calls that last started each handle before the call at `poll_index`, in the same trajectory and not by a poll."""
        poll_call = self.expanded_tool_calls[poll_index]
        starters: dict[ToolCallKey, ExpandedToolCall] = {}
        for handle in handles:
            latest = None
            for earlier in self.expanded_tool_calls[:poll_index]:
                if (
                    _trajectory_of(earlier.tool_call)
                    == _trajectory_of(poll_call.tool_call)
                    and earlier.tool_call.result is not None
                    and handle in earlier.tool_call.result.handles
                    and not _has_poll_step(earlier.tool_call)
                ):
                    latest = earlier
            if latest is not None:
                starters[latest.tool_call.harness_tool_call.key] = latest
        return list(starters.values())

    def check_harness_output_file_reads(self) -> None:
        """Hold the later calls of a trajectory that read an `output_path` against the `OutputPlace`s of those calls, and check that no such read is a use of a file without a known writer.

        The output file of a poll holds the output of the call that started what it polls, so a read of it is a place of that starter, which this script finds by the handles of the poll.
        A read that is no place is counted by cause, i.e. the reader's result holds no text, the reading words are only in commands whose program or option has no row, which make a use of unknown kind, or another cause.
        The commands of the second cause are counted by their innermost program and its first unread word, e.g. `tail -5`.
        """
        for owner_index, owner in enumerate(self.expanded_tool_calls):
            result = owner.tool_call.result
            if (
                result is None
                or result.output_path is None
                or _is_not_run(owner.tool_call)
            ):
                continue
            output_path = result.output_path
            owners = [owner, *self.starters_of_poll(owner_index)]
            place_keys = {
                output_place.showing_tool_call_key
                for showing_owner in owners
                for output_place in showing_owner.output_places
            }
            for reader in self.expanded_tool_calls[owner_index + 1 :]:
                if _trajectory_of(reader.tool_call) != _trajectory_of(
                    owner.tool_call
                ) or not any(
                    _is_same_file(path, output_path) for path in _read_paths_of(reader)
                ):
                    continue
                reading_key = reader.tool_call.harness_tool_call.key
                if place_keys and self.shows_content_of(reader, output_path):
                    is_place = reading_key in place_keys
                    self.trial_audit.add_sides(
                        "harness_output_file_reads_are_output_places",
                        1,
                        is_place,
                        reading_key,
                    )
                    if not is_place:
                        self.count_read_that_is_no_place(reader, output_path)
                self.trial_audit.add_sides(
                    "harness_output_file_reads_are_no_uses_without_writer",
                    sum(
                        _is_same_file(file_use.path, output_path)
                        for file_use in reader.file_uses_without_known_writer
                    ),
                    0,
                    reading_key,
                )

    def shows_content_of(self, reader: ExpandedToolCall, path: str) -> bool:
        """Tell whether a call may have run, has a result with text and names a path with a read or search tool, or as an argument of a command whose program reads its arguments as files to show, by this script's own door.

        A command reads its arguments as files to show when its program's row gives them the role `read_file` and no option of the command has a row that gives them another role, e.g. `tail out` and not `wc -l out`, `grep -c x out` or `find / -name out`.
        A command whose program or options have no row makes a use of unknown kind, which is no place, and so does a command whose stdout ends anywhere but in the result, e.g. `cat P > /dev/null` or `echo "$(tail -1 P)"`.
        """
        result = reader.tool_call.result
        if (
            _is_not_run(reader.tool_call)
            or result is None
            or result.tool_output_text is None
        ):
            return False
        for _, step in indexed_action_steps_of(reader.tool_call.action):
            tool_paths = (
                [step.path]
                if isinstance(step, ReadFileAction) and step.path is not None
                else step.paths
                if isinstance(step, SearchFilesAction)
                else []
            )
            if any(_is_same_file(tool_path, path) for tool_path in tool_paths):
                return True
        return any(
            any(
                isinstance(route.end, ResultDestination)
                for route in ran_command.stdout_routes
            )
            and self.reads_arguments_to_show(ran_command.program_invocations[-1])
            and any(
                _is_same_file(argument, path)
                for argument in ran_command.program_invocations[-1].arguments  # type: ignore[union-attr]
            )
            for ran_command in ran_commands_by_id_of(reader).values()
        )

    def reads_arguments_to_show(
        self, program_invocation: ProgramInvocation | UnknownProgramInvocation
    ) -> bool:
        """Tell whether a program run reads its arguments as files to show, i.e. its row gives them the role `read_file`, it has no unread words and no option row gives them another role."""
        if (
            isinstance(program_invocation, UnknownProgramInvocation)
            or program_invocation.unread_words
        ):
            return False
        program_behavior = self.own_knowledge.program_behavior(
            program_invocation.program_name, program_invocation.subcommand_words
        )
        if (
            isinstance(program_behavior, UnknownProgramBehavior)
            or program_behavior.argument_role != ProgramWordRole.READ_FILE
        ):
            return False
        for option in program_invocation.options:
            option_word = self.own_knowledge.program_option_word(
                program_behavior, option.name
            )
            if not isinstance(option_word, ProgramOptionWord) or any(
                option_word_option.program_option_behavior.argument_role_with_option
                not in (None, ProgramWordRole.READ_FILE)
                for option_word_option in option_word.options
            ):
                return False
        return True

    def count_read_that_is_no_place(
        self, reader: ExpandedToolCall, output_path: str
    ) -> None:
        """Count a read of a harness output file that is no output place by its cause, and the commands of the cause of commands without a row by program."""
        reader_result = reader.tool_call.result
        naming_commands = _commands_naming_path_of(reader, output_path)
        if reader_result is None or reader_result.tool_output_text is None:
            cause = "the reader's result holds no text"
        elif _is_read_only_by_commands_without_row(reader, output_path):
            cause = "read only by commands without a row"
            for ran_command in naming_commands:
                innermost = ran_command.program_invocations[-1]
                unread_word = (
                    "(no row)"
                    if isinstance(innermost, UnknownProgramInvocation)
                    else innermost.unread_words[0]
                )
                self.trial_audit.count(
                    f"harness output file reads that are no place, naming command {innermost.program_name} {unread_word}"
                )
        else:
            cause = "other cause"
        self.trial_audit.count(f"harness output file reads that are no place, {cause}")

    def starters_of_poll(self, poll_index: int) -> list[ExpandedToolCall]:
        """Give the earlier calls of the same trajectory whose results started a handle that the call at `poll_index` polls."""
        poll_call = self.expanded_tool_calls[poll_index]
        polled_handles = {
            handle
            for _, step in indexed_action_steps_of(poll_call.tool_call.action)
            if isinstance(step, PollAction)
            for handle in step.handles
        }
        if (
            not polled_handles
            and poll_call.tool_call.result is not None
            and _has_poll_step(poll_call.tool_call)
        ):
            polled_handles = set(poll_call.tool_call.result.handles)
        return [
            earlier
            for earlier in self.expanded_tool_calls[:poll_index]
            if _trajectory_of(earlier.tool_call) == _trajectory_of(poll_call.tool_call)
            and earlier.tool_call.result is not None
            and polled_handles & set(earlier.tool_call.result.handles)
            and not _has_poll_step(earlier.tool_call)
        ]

    def check_other_trajectories(self) -> None:
        """Recount the runs and uses that only a call of another trajectory fits, which `treat_calls_of_other_trajectory_as_not_linked` is asked for."""
        written_paths_by_trajectory: dict[tuple[str, bool], list[str]] = {}
        for expanded_tool_call in self.expanded_tool_calls:
            written_paths_by_trajectory.setdefault(
                _trajectory_of(expanded_tool_call.tool_call), []
            ).extend(
                written_file.path
                for written_file in expanded_tool_call.written_files
                if not _is_not_run(expanded_tool_call.tool_call)
            )
        recount = 0
        for expanded_tool_call in self.expanded_tool_calls:
            trajectory = _trajectory_of(expanded_tool_call.tool_call)
            paths = [
                (ran_text.source.runner_command_id, ran_text.source.path)
                for ran_text in expanded_tool_call.ran_texts
                if isinstance(ran_text.source, FileTextWithoutKnownWriter)
                and isinstance(ran_text, UnknownRanText)
                and ran_text.reason == UnknownRanTextReason.NOT_WRITTEN_IN_TRIAL
                and ran_text.source.path is not None
            ] + [
                (file_use.command_id, file_use.path)
                for file_use in expanded_tool_call.file_uses_without_known_writer
            ]
            own_written_paths = written_paths_by_trajectory.get(trajectory, [])
            for _, path in dict.fromkeys(paths):
                if any(
                    _is_same_file(path, written_path)
                    for written_path in own_written_paths
                ):
                    continue
                recount += any(
                    other_trajectory != trajectory
                    and any(
                        _is_same_file(path, written_path)
                        for written_path in written_paths
                    )
                    for other_trajectory, written_paths in written_paths_by_trajectory.items()
                )
        self.trial_audit.add_sides(
            "other_trajectory_rule_uses_equal_recount",
            self.trial_audit.judgment_rule_use_counts[
                judgment_rules.treat_calls_of_other_trajectory_as_not_linked.__name__
            ],
            recount,
            None,
        )


def ran_commands_by_id_of(
    expanded_tool_call: ExpandedToolCall,
) -> dict[int, RanCommand]:
    """Give every command of the shell texts that a call ran, by its id."""
    return {
        ran_command.shell_command.id: ran_command
        for ran_text in expanded_tool_call.ran_texts
        if isinstance(ran_text, RanShellText)
        for ran_command in ran_text.ran_commands
    }


def _unknown_ran_text_count_of(
    expanded_tool_call: ExpandedToolCall,
    reason: UnknownRanTextReason,
    sources: tuple[type, ...],
) -> int:
    """Count the unknown ran texts of a call with a reason and one of the source types."""
    return sum(
        isinstance(ran_text, UnknownRanText)
        and ran_text.reason == reason
        and isinstance(ran_text.source, sources)
        for ran_text in expanded_tool_call.ran_texts
    )


def _runner_name_branch_of(
    ran_command: RanCommand, runs_a_text: bool, reads_a_pipe: bool
) -> str:
    """Name the branch of `commands_of_runner_names_fall_in_a_branch` that a command whose first word is a runner name falls in, the first that fits.

    A first argument `-` names stdin and no file, and the words after it are arguments of the code, so `python3 -` with nothing on its stdin falls in the branch without an argument and stdin, e.g. `python3 - 2>&1 | tail <<'EOF'`, where the heredoc goes to tail.
    """
    first = ran_command.program_invocations[0]
    shell_command = ran_command.shell_command
    if runs_a_text:
        return "runs a text"
    if isinstance(first, UnknownProgramInvocation):
        return "program without a row"
    if first.unread_words:
        return "unread words"
    if len(ran_command.program_invocations) > 1:
        return "runs a next program"
    if (
        first.arguments[:1] in ((), (_STDIN_WORD,))
        and shell_command.stdin_text is None
        and shell_command.stdin_file_path is None
        and not reads_a_pipe
    ):
        return "no argument and no stdin"
    return "in no branch"


def _has_words_of_its_program_invocations(ran_command: RanCommand) -> bool:
    """Tell whether the words of a command and the parts of its program invocations hold the same characters, `-` and `=` left out, with each program word taken as written.

    The program word of each invocation is a word after that of the invocation before it which can name its program, and some choice of them must make the characters equal.
    An assignment or an option value can end with the program name, e.g. `PYTHONPATH=/app/python` before `python` in `env PYTHONPATH=/app/python python -m pytest`, or `/usr/bin/python3` of `uv run --python /usr/bin/python3 python`, while a program whose row skips no assignments reads such a word as its next program, e.g. `time A=/app/python b`.
    """
    words = ran_command.shell_command.words
    word_characters = _characters_of(words)
    program_invocations = ran_command.program_invocations

    def has_choice_from(position: int, after_index: int, parts: Counter[str]) -> bool:
        if position == len(program_invocations):
            return parts == word_characters
        program_invocation = program_invocations[position]
        own_parts = _characters_of(_parts_of(program_invocation))
        return any(
            has_choice_from(
                position + 1, index, parts + own_parts + _characters_of([words[index]])
            )
            for index in range(after_index + 1, len(words))
            if _is_written_program_word(words[index], program_invocation.program_name)
        )

    return has_choice_from(0, -1, Counter())


def _parts_of(
    program_invocation: ProgramInvocation | UnknownProgramInvocation,
) -> list[str]:
    """List the words that a program invocation reads after its program word, i.e. its subcommand words, options with their values, arguments and unread words, or the words of an unknown program."""
    if isinstance(program_invocation, UnknownProgramInvocation):
        return list(program_invocation.words)
    parts = list(program_invocation.subcommand_words)
    for option in program_invocation.options:
        parts += [option.name] if option.value is None else [option.name, option.value]
    return (
        parts
        + list(program_invocation.arguments)
        + list(program_invocation.unread_words)
    )


def _group_count_of(paths: Sequence[str], is_joined: Callable[[str, str], bool]) -> int:
    """Count the groups of paths that pairs joined by `is_joined` make, directly or through other paths of the list.

    A use whose path fits several written files is recorded on each of them, so the written files that one argument fits are one group, e.g. `/a/fetch.log` and `/b/fetch.log` for `cat fetch.log`.
    """
    group_of = list(range(len(paths)))

    def root_of(index: int) -> int:
        while group_of[index] != index:
            index = group_of[index]
        return index

    for index, path in enumerate(paths):
        for other_index in range(index):
            if is_joined(path, paths[other_index]):
                group_of[root_of(index)] = root_of(other_index)
    return len({root_of(index) for index in range(len(paths))})


def _filled_word_of(word: str, ran_command: RanCommand) -> str:
    """Fill each `$NAME` or `${NAME}` of a word whose variable has exactly one value and no value set at run time, e.g. fetch.log for `$F` after `F=fetch.log`, written again here so that the recount does not go through the code it checks."""
    sure_value_of_name = {
        variable_values.name: variable_values.values[0]
        for variable_values in ran_command.variable_values
        if len(variable_values.values) == 1
        and not variable_values.has_value_set_at_run_time
    }
    return _PLAIN_VARIABLE.sub(
        lambda match: sure_value_of_name.get(
            match.group(1) or match.group(2), match.group(0)
        ),
        word,
    )


def _is_written_program_word(word: str, program_name: str) -> bool:
    """Tell whether a word as written can be the program word of a program name, i.e. the name itself, the word without its folder, or that without a version at its end."""
    file_name = _file_name_of(word)
    return program_name in (word, file_name, _VERSION_AT_END.sub("", file_name))


def _characters_of(words: Iterable[str]) -> Counter[str]:
    """Count the characters of words, `-` and `=` left out."""
    return Counter(
        character for word in words for character in word if character not in "-="
    )


def _is_expansion_word(shell_command: ShellCommand, program_name: str) -> bool:
    """Tell whether a program name is a word of the command that holds an expansion, e.g. `$P`, and no word without an expansion can be its program word.

    A word with an expansion can end with the name of a program that a word as written names, e.g. `$D/venv` beside `venv` in `python -m venv $D/venv`.
    """
    expansion_word_indexes = set(shell_command.expansion_word_indexes)
    if any(
        _is_written_program_word(word, program_name)
        for index, word in enumerate(shell_command.words)
        if index not in expansion_word_indexes
    ):
        return False
    return any(
        _is_written_program_word(shell_command.words[index], program_name)
        for index in expansion_word_indexes
        if index < len(shell_command.words)
    )


def _is_read_only_by_commands_without_row(
    expanded_tool_call: ExpandedToolCall, path: str
) -> bool:
    """Tell whether every command of a call that names a path has an innermost program without a row or with unread words, and no tool of the call names it."""
    tool_paths = [
        tool_path
        for _, step in indexed_action_steps_of(expanded_tool_call.tool_call.action)
        for tool_path in (
            [step.path]
            if isinstance(step, ReadFileAction) and step.path is not None
            else step.paths
            if isinstance(step, SearchFilesAction)
            else []
        )
    ]
    if any(_is_same_file(tool_path, path) for tool_path in tool_paths):
        return False
    naming_commands = _commands_naming_path_of(expanded_tool_call, path)
    return bool(naming_commands) and all(
        isinstance(ran_command.program_invocations[-1], UnknownProgramInvocation)
        or bool(ran_command.program_invocations[-1].unread_words)  # type: ignore[union-attr]
        for ran_command in naming_commands
    )


def _commands_naming_path_of(
    expanded_tool_call: ExpandedToolCall, path: str
) -> list[RanCommand]:
    """List the commands of a call with a word after the first that names the same file as a path."""
    return [
        ran_command
        for ran_command in ran_commands_by_id_of(expanded_tool_call).values()
        if any(
            _is_same_file(word, path) for word in ran_command.shell_command.words[1:]
        )
    ]


def _innermost_program_name_of(ran_command: RanCommand) -> str:
    """Give the program name of the last program invocation of a command."""
    return ran_command.program_invocations[-1].program_name


def _read_paths_of(expanded_tool_call: ExpandedToolCall) -> Iterator[str]:
    """Give the paths that a call's read and search tools name and the words of its commands, which may name a file it reads."""
    for _, step in indexed_action_steps_of(expanded_tool_call.tool_call.action):
        if isinstance(step, ReadFileAction) and step.path is not None:
            yield step.path
        elif isinstance(step, SearchFilesAction):
            yield from step.paths
    for ran_command in ran_commands_by_id_of(expanded_tool_call).values():
        yield from ran_command.shell_command.words[1:]


def _is_same_file(path: str, other_path: str) -> bool:
    """Tell whether two path texts name one file, in the way `treat_path_that_ends_another_as_same_file` reads them, written again here so that the recount does not go through the code it checks."""
    if path == other_path:
        return True
    path_parts, other_path_parts = _path_parts_of(path), _path_parts_of(other_path)
    if path_parts is None or other_path_parts is None:
        return False
    (is_absolute, parts), (other_is_absolute, other_parts) = (
        path_parts,
        other_path_parts,
    )
    if not parts or not other_parts:
        return False
    if is_absolute and other_is_absolute:
        return parts == other_parts
    if not is_absolute and not other_is_absolute and len(parts) != len(other_parts):
        shorter, longer = sorted((parts, other_parts), key=len)
        return longer[-len(shorter) :] == shorter
    relative = other_parts if is_absolute else parts
    whole = parts if is_absolute else other_parts
    return len(relative) <= len(whole) and whole[-len(relative) :] == relative


def _path_parts_of(path: str) -> tuple[bool, list[str]] | None:
    """Split a path text into whether it is absolute and its parts without `.` and `x/..`, the leading parts of a relative path that stand for an unshown folder dropped, or None for an empty path.

    A `..` right after the root stays at the root, as in `/../f`, which names `/f`.
    """
    if not path:
        return None
    is_absolute = path.startswith("/")
    parts: list[str] = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == ".." and parts and parts[-1] != "..":
            parts.pop()
        elif not (part == ".." and is_absolute and not parts):
            parts.append(part)
    while not is_absolute and parts and _UNSHOWN_FOLDER_PART.match(parts[0]):
        parts = parts[1:]
    return is_absolute, parts


def _file_name_of(word: str) -> str:
    """Give the last part of a word after its last `/`, e.g. `python3` of `/usr/bin/python3`."""
    return word.rsplit("/", 1)[-1]


def _trajectory_of(tool_call: ToolCall) -> tuple[str, bool]:
    """Give the trajectory of a call, as its trajectory id and whether it is a subagent's."""
    return (
        tool_call.harness_tool_call.key.trajectory_id,
        tool_call.harness_tool_call.is_subagent,
    )


def _is_not_run(tool_call: ToolCall) -> bool:
    """Tell whether the result of a call says the tool did not run it."""
    return (
        tool_call.result is not None
        and tool_call.result.execution_status == ExecutionStatus.NOT_RUN
    )


def _has_poll_step(tool_call: ToolCall) -> bool:
    """Tell whether a call's action or one of its script steps is a `PollAction`."""
    return any(
        isinstance(step, PollAction)
        for _, step in indexed_action_steps_of(tool_call.action)
    )


def _text_of_tool_call_key(tool_call_key: ToolCallKey) -> str:
    """Write a tool call key as one CSV value, its trajectory id, step id and 0-based call index joined by `:`."""
    return f"{tool_call_key.trajectory_id}:{tool_call_key.step_id}:{tool_call_key.call_index}"


if __name__ == "__main__":
    main()
