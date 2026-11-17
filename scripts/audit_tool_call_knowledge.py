"""Run `convert_tool_calls` on raw trials and list which rows of the harness tool catalog and which declared result formats were used, which harness tools have no row, which results have no format, which arguments the tool calls have and how often each judgment rule was used.

It writes four CSVs under `out/tool_call_knowledge/`, which `.gitignore` keeps out of the repo, since tool and argument names come from trajectories and can hold hidden task content.
They hold counts and names only, never result text.

| File | One row |
|---|---|
| `row_uses.csv` | A catalog row or a declared result format that answered a lookup, with its lookups and trials |
| `unknown_inputs.csv` | A key that a lookup found no row for, e.g. a harness tool without a row or the `unknown_format` results of a tool |
| `harness_tool_arguments_in_data.csv` | An argument of a harness tool in the trajectories, with its calls, trials, value types and the action field the catalog maps it to |
| `judgment_rule_uses.csv` | A judgment rule of `tool_call/judgment_rules.py`, with its uses and trials, and 0 for a rule that was never used |

A lookup of a harness tool is one tool call or one step of a Codex `exec` script, and a lookup of a result format is one tool call with a result whose format the converter asks for.
An argument row counts once for every lookup of its tool by a call or a script step that has that argument, so its count is the third file's `call_count` of the argument plus the Codex `exec` script steps that have it.
The `source` column of the first two files names the catalog file or the declarations folder that the row belongs to, e.g. `harness_tools.csv` or `harness_result_formats`.
A row key is written as a JSON array of its key column values.
The first two files list the keys of the most trials first, and a row that no lookup used is in neither.

Run it as `nice -n 10 uv run python -I scripts/audit_tool_call_knowledge.py <raw_trials_dir> [--limit N]`.
"""

import argparse
import csv
import inspect
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from tb_internet_use.knowledge.catalog import (
    KnowledgeLookupKey,
    KnowledgeUses,
    KnowledgeUsesTotal,
)
from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge
from tb_internet_use.pipeline import read_trajectory
from tb_internet_use.tool_call import convert_tool_calls, judgment_rules
from tb_internet_use.tool_call.model import (
    HarnessTool,
    HarnessToolCall,
    HarnessToolLabel,
    UnreadableTrajectory,
)

OUT_DIR = Path(__file__).resolve().parents[1] / "out" / "tool_call_knowledge"
# Data runs use at most 4 processes, to leave the machine usable.
_PROCESS_COUNT = 4
_JSON_TYPE_NAMES = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
    type(None): "null",
}

# (harness, tool, argument name, JSON type name of its value)
type ArgumentValueKey = tuple[str, str, str, str]
# (harness, tool, argument name)
type ArgumentKey = tuple[str, str, str]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("raw_trials_dir", type=Path)
    parser.add_argument(
        "--limit", type=int, help="only the first N trial folders by name"
    )
    arguments = parser.parse_args()

    trial_dirs = sorted(p for p in arguments.raw_trials_dir.iterdir() if p.is_dir())
    if arguments.limit is not None:
        trial_dirs = trial_dirs[: arguments.limit]
    total = TrialAuditTotal()
    with ProcessPoolExecutor(_PROCESS_COUNT) as pool:
        for trial_audit in pool.map(audit_trial, trial_dirs, chunksize=20):
            total.add_trial(trial_audit)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_csv(
        OUT_DIR / "row_uses.csv",
        ("source", "row_key", "lookup_count", "trial_count"),
        _lookup_rows(
            total.knowledge_uses_total.row_use_counts,
            total.knowledge_uses_total.row_trial_counts,
        ),
    )
    _write_csv(
        OUT_DIR / "unknown_inputs.csv",
        ("source", "key_asked", "lookup_count", "trial_count"),
        _lookup_rows(
            total.knowledge_uses_total.unknown_input_counts,
            total.knowledge_uses_total.unknown_input_trial_counts,
        ),
    )
    _write_csv(
        OUT_DIR / "harness_tool_arguments_in_data.csv",
        (
            "harness",
            "tool",
            "argument",
            "call_count",
            "trial_count",
            "value_types",
            "action_field",
        ),
        _argument_rows(total.argument_value_call_counts, total.argument_trial_counts),
    )
    _write_csv(
        OUT_DIR / "judgment_rule_uses.csv",
        ("judgment_rule", "use_count", "trial_count"),
        judgment_rule_rows(
            total.judgment_rule_use_counts, total.judgment_rule_trial_counts
        ),
    )
    print(f"trials: {dict(sorted(total.outcome_counts.items()))}")
    print(
        f"rows used: {len(total.knowledge_uses_total.row_use_counts)}, "
        f"unknown inputs: {len(total.knowledge_uses_total.unknown_input_counts)}, "
        f"arguments in data: {len(total.argument_trial_counts)}"
    )
    print(f"written under {OUT_DIR}")


def audit_trial(trial_dir: Path) -> TrialAudit:
    """Run `convert_tool_calls` on one trial and return what its door and its judgment rules counted and the arguments of its calls, with an exception named instead of raised."""
    knowledge = ToolCallKnowledge()
    judgment_rule_use_counts: Counter[str] = Counter()
    try:
        harness_tool_calls = read_trajectory(trial_dir)
        if isinstance(harness_tool_calls, UnreadableTrajectory):
            return TrialAudit(f"unreadable {harness_tool_calls.reason}")
        convert_tool_calls(
            harness_tool_calls,
            knowledge=knowledge,
            judgment_rule_use_counts=judgment_rule_use_counts,
        )
    except Exception as error:  # noqa: BLE001, one trial must not stop the run
        return TrialAudit(f"exception {type(error).__name__}")
    return TrialAudit(
        "converted",
        knowledge.uses,
        _argument_value_call_counts(harness_tool_calls),
        judgment_rule_use_counts,
    )


@dataclass(slots=True)
class TrialAudit:
    """Result of auditing one trial, sent from a worker process to the main process that sums the trials."""

    # `converted`, `unreadable` with the reason, or `exception` with the type name.
    outcome: str
    knowledge_uses: KnowledgeUses = field(default_factory=KnowledgeUses)
    # The number of calls that had the argument with a value of the type.
    argument_value_call_counts: Counter[ArgumentValueKey] = field(
        default_factory=Counter
    )
    # The number of uses of each judgment rule, by its function name.
    judgment_rule_use_counts: Counter[str] = field(default_factory=Counter)


@dataclass(slots=True)
class TrialAuditTotal:
    """Sum of the `TrialAudit` of many trials, built by `main` to write the CSVs."""

    # The number of trials of each outcome, e.g. `converted`.
    outcome_counts: Counter[str] = field(default_factory=Counter)
    knowledge_uses_total: KnowledgeUsesTotal = field(default_factory=KnowledgeUsesTotal)
    argument_value_call_counts: Counter[ArgumentValueKey] = field(
        default_factory=Counter
    )
    # The number of trials that have a call with the argument.
    argument_trial_counts: Counter[ArgumentKey] = field(default_factory=Counter)
    judgment_rule_use_counts: Counter[str] = field(default_factory=Counter)
    # The number of trials that used the judgment rule at least once.
    judgment_rule_trial_counts: Counter[str] = field(default_factory=Counter)

    def add_trial(self, trial_audit: TrialAudit) -> None:
        """Add what one trial counted, counting the trial once for each argument and each judgment rule it has."""
        self.outcome_counts[trial_audit.outcome] += 1
        self.knowledge_uses_total.add_trial(trial_audit.knowledge_uses)
        self.judgment_rule_use_counts.update(trial_audit.judgment_rule_use_counts)
        # keys() adds one per rule, so this counts trials and not uses.
        self.judgment_rule_trial_counts.update(
            trial_audit.judgment_rule_use_counts.keys()
        )
        self.argument_value_call_counts.update(trial_audit.argument_value_call_counts)
        # A set adds one per argument, so this counts trials and not calls.
        self.argument_trial_counts.update(
            {key[:3] for key in trial_audit.argument_value_call_counts}
        )


def judgment_rule_rows(
    use_counts: Counter[str], trial_counts: Counter[str]
) -> Iterable[tuple[str, int, int]]:
    """List every judgment rule of `tool_call/judgment_rules.py` as a CSV row with its uses and trials, those of the most uses first, so that a rule never used shows with 0."""
    rule_names = [
        name
        for name, function in inspect.getmembers(judgment_rules, inspect.isfunction)
        if function.__module__ == judgment_rules.__name__ and not name.startswith("_")
    ]
    for name in sorted(rule_names, key=lambda name: (-use_counts[name], name)):
        yield name, use_counts[name], trial_counts[name]


def _argument_value_call_counts(
    harness_tool_calls: Sequence[HarnessToolCall],
) -> Counter[ArgumentValueKey]:
    """Count the calls of one trial per harness tool, argument name and JSON type of the argument value."""
    counts: Counter[ArgumentValueKey] = Counter()
    for harness_tool_call in harness_tool_calls:
        for argument, value in harness_tool_call.args.items():
            type_name = _JSON_TYPE_NAMES[type(value)]
            counts[
                harness_tool_call.tool.harness,
                harness_tool_call.tool.name,
                argument,
                type_name,
            ] += 1
    return counts


def _lookup_rows(
    lookup_counts: Counter[KnowledgeLookupKey],
    trial_counts: Counter[KnowledgeLookupKey],
) -> Iterable[tuple[str, str, int, int]]:
    """List the lookups per source and key as CSV rows, those of the most trials first and then those of the most lookups."""
    for lookup_key in sorted(
        lookup_counts, key=lambda key: (-trial_counts[key], -lookup_counts[key], key)
    ):
        source, row_key = lookup_key
        yield (
            source,
            json.dumps(row_key),
            lookup_counts[lookup_key],
            trial_counts[lookup_key],
        )


def _argument_rows(
    argument_value_call_counts: Counter[ArgumentValueKey],
    argument_trial_counts: Counter[ArgumentKey],
) -> Iterable[tuple[str, str, str, int, int, str, str]]:
    """List the arguments in the data as CSV rows by harness, tool and argument, each with the action field the catalog maps it to."""
    call_counts_by_type: dict[ArgumentKey, Counter[str]] = {}
    for argument_value_key, count in argument_value_call_counts.items():
        harness, tool, argument, type_name = argument_value_key
        type_counts = call_counts_by_type.setdefault(
            (harness, tool, argument), Counter()
        )
        type_counts[type_name] += count
    # The lookups of this door only fill the `action_field` column, so its counts are dropped.
    knowledge = ToolCallKnowledge()
    for argument_key, type_counts in sorted(call_counts_by_type.items()):
        harness, tool, argument = argument_key
        label = knowledge.harness_tool_label(HarnessTool(harness, tool), (argument,))
        action_field = (
            label.action_field_by_argument_name.get(argument, "")
            if isinstance(label, HarnessToolLabel)
            else ""
        )
        yield (
            harness,
            tool,
            argument,
            # A call has each argument once, so the total over the types is the calls with the argument.
            type_counts.total(),
            argument_trial_counts[argument_key],
            "|".join(sorted(type_counts)),
            action_field,
        )


def _write_csv(path: Path, columns: Sequence[str], rows: Iterable[Sequence]) -> None:
    with path.open("w", newline="") as csv_file:
        writer = csv.writer(csv_file, lineterminator="\n")
        writer.writerow(columns)
        writer.writerows(rows)


if __name__ == "__main__":
    main()
