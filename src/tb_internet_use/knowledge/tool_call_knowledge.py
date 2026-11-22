"""Answer the questions of `convert_tool_calls` about harness tools from the harness tool catalog and the harness result format declarations, counting every use of a row and every input without one, apart from an argument without a row."""

import functools
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, fields
from pathlib import Path

from tb_internet_use.knowledge.catalog import (
    Catalog,
    KnowledgeRowKey,
    KnowledgeUses,
    load_catalog,
)
from tb_internet_use.knowledge.declarations.tool_call.harness_result_format_declaration import (
    HarnessToolResultDeclaration,
    JsonObject,
    MatchedHarnessResultFormat,
)
from tb_internet_use.knowledge.declarations.tool_call.harness_result_formats import (
    RESULT_FORMATS_BY_HARNESS,
)
from tb_internet_use.tool_call.model import (
    DEFERRED,
    TOOL_CALL_ACTION_CLASSES,
    ExecutionHandleKind,
    HarnessTool,
    HarnessToolLabel,
    PollAction,
    UnknownHarnessReturnCodeInterpretation,
    UnknownHarnessToolLabel,
    UnmatchedFormat,
)

TOOL_CALL_CATALOGS_DIR = Path(__file__).parent / "catalogs" / "tool_call"
HARNESS_TOOLS_CSV = "harness_tools.csv"
HARNESS_TOOL_ARGUMENTS_CSV = "harness_tool_arguments.csv"
HARNESS_RETURN_CODE_INTERPRETATIONS_CSV = "harness_return_code_interpretations.csv"
# The name of the folder of the harness result format declarations, which the counts of their uses carry.
HARNESS_RESULT_FORMATS_DECLARATIONS = "harness_result_formats"
_HANDLES_FIELD = "handles"
# The last word of the key of an unmatched result of a message that the harness wrote, the name of the field `HarnessToolCall.is_harness_message`.
_HARNESS_MESSAGE_KEY_WORD = "is_harness_message"
# The answer for a tool without declared result formats.
_NO_RESULT_FORMATS = HarnessToolResultDeclaration()


class ToolCallKnowledge:
    """Outside knowledge of `convert_tool_calls`, made for one trial and passed to it as `knowledge`, which it asks one question per method.

    An answer is a value or an unknown, never a default.
    `uses` counts every catalog row and every declared result format that answered, and every input without one apart from an argument without a row, as `harness_tool_label` says.
    The loaded catalogs are cached per process, so making one per trial is cheap.
    """

    def __init__(
        self,
        *,
        catalogs_dir: Path = TOOL_CALL_CATALOGS_DIR,
        result_formats_by_harness: Mapping[
            str, Mapping[str, HarnessToolResultDeclaration]
        ] = RESULT_FORMATS_BY_HARNESS,
    ) -> None:
        self.uses = KnowledgeUses()
        self._catalogs = _load_tool_call_catalogs(catalogs_dir)
        self._result_formats_by_harness = result_formats_by_harness

    def harness_tool_label(
        self, tool: HarnessTool, argument_names: Collection[str]
    ) -> HarnessToolLabel | UnknownHarnessToolLabel:
        """Answer what a harness tool does and which action field each argument that one call of it has fills, or `UnknownHarnessToolLabel` for a tool without a row.

        `argument_names` are the names of the arguments of the call in the trajectory.
        A lookup counts the tool row once and the row of each argument the call has, so the count of an argument row is the number of calls that carried that argument.
        An argument without a row fills no field and is not counted as an unknown input.
        """
        catalogs = self._catalogs
        tool_row = catalogs.harness_tools.lookup((tool.harness, tool.name), self.uses)
        if tool_row is None:
            return UnknownHarnessToolLabel()
        argument_rows = [
            (row_key[-1], row)
            for row_key in catalogs.argument_row_keys_by_tool.get(tool, ())
            if row_key[-1] in argument_names
            and (row := catalogs.harness_tool_arguments.lookup(row_key, self.uses))
            is not None
        ]
        return HarnessToolLabel(
            action_type=tool_row.action_type,
            action_field_by_argument_name={
                name: row.action_field for name, row in argument_rows
            },
            stops_execution=tool_row.stops_execution,
            # The `handles` arguments of one tool agree on the kind, which loading checks.
            argument_handle_kind=next(
                (row.handle_kind for _, row in argument_rows if row.handle_kind), None
            ),
        )

    def exit_code_of_harness_return_code_interpretation(
        self, tool: HarnessTool, return_code_interpretation: str
    ) -> int | UnknownHarnessReturnCodeInterpretation:
        """Answer which exit code a text that a harness tool writes in place of an exit code stands for, or `UnknownHarnessReturnCodeInterpretation` for a text without a row.

        Such a text is e.g. `No matches found`, which Claude Code writes in the structured result of a `Bash` call for the exit code 1 of grep.
        A lookup counts the row `(harness, tool, text)`, or the same key as an unknown input.
        """
        row = self._catalogs.harness_return_code_interpretations.lookup(
            (tool.harness, tool.name, return_code_interpretation), self.uses
        )
        if row is None:
            return UnknownHarnessReturnCodeInterpretation()
        return row.exit_code

    def has_json_result_formats(self, tool: HarnessTool) -> bool:
        """Tell whether a harness tool has declared formats for results that are JSON objects, so that a converter reads a JSON object out of the trajectory only for such a tool.

        It counts nothing in `uses`, since `harness_result_format` counts the format that the result then has.
        """
        harness_tool_result_declaration = harness_tool_result_declaration_of(
            tool, result_formats_by_harness=self._result_formats_by_harness
        )
        return harness_tool_result_declaration.json_formats is not None

    def harness_result_format(
        self,
        tool: HarnessTool,
        tool_result_raw_text: str | None,
        tool_result_json: JsonObject | None,
        *,
        is_marked_as_error: bool,
        is_harness_message: bool,
    ) -> MatchedHarnessResultFormat | UnmatchedFormat:
        """Answer which declared format a result of a harness tool has, or the `UnmatchedFormat` of a result that matches no format or has none to try.

        A matched format counts as a use of the row `(harness, tool, format name)` and an unmatched result as an unknown input `(harness, tool, "unknown_format")` or `(harness, tool, "skipped_format")`, both under `HARNESS_RESULT_FORMATS_DECLARATIONS`.
        The key of an unmatched message that the harness wrote ends with `"is_harness_message"`, e.g. `(harness, "SYSTEM_MESSAGE", "unknown_format", "is_harness_message")`, since such a message is often no end of a task at all, e.g. the prompt of an Antigravity CLI `schedule` timer, and lists of unknown inputs should not rank it as a tool result to declare.
        """
        harness_tool_result_declaration = harness_tool_result_declaration_of(
            tool, result_formats_by_harness=self._result_formats_by_harness
        )
        matched_or_unmatched_format = (
            harness_tool_result_declaration.harness_result_format_of(
                tool_result_raw_text,
                tool_result_json,
                is_marked_as_error=is_marked_as_error,
            )
        )
        if isinstance(matched_or_unmatched_format, UnmatchedFormat):
            row_key = (tool.harness, tool.name, str(matched_or_unmatched_format))
            if is_harness_message:
                row_key = (*row_key, _HARNESS_MESSAGE_KEY_WORD)
            self.uses.unknown_input_counts[
                HARNESS_RESULT_FORMATS_DECLARATIONS, row_key
            ] += 1
        else:
            row_key = (tool.harness, tool.name, matched_or_unmatched_format.format.name)
            self.uses.row_use_counts[HARNESS_RESULT_FORMATS_DECLARATIONS, row_key] += 1
        return matched_or_unmatched_format


def harness_tool_result_declaration_of(
    tool: HarnessTool,
    *,
    result_formats_by_harness: Mapping[
        str, Mapping[str, HarnessToolResultDeclaration]
    ] = RESULT_FORMATS_BY_HARNESS,
) -> HarnessToolResultDeclaration:
    """Find the declared result formats of a harness tool, with all three lists None for a tool or harness without declared formats.

    It counts nothing, so conversion asks `ToolCallKnowledge`, and only `ToolCallKnowledge` and audits of the declarations call it.
    """
    formats_by_tool = result_formats_by_harness.get(tool.harness, {})
    return formats_by_tool.get(tool.name, _NO_RESULT_FORMATS)


@functools.cache
def _load_tool_call_catalogs(catalogs_dir: Path) -> _ToolCallCatalogs:
    """Load the three harness tool CSVs of a folder once per process, raising ValueError on a row that `convert_tool_calls` cannot use."""
    harness_tools = load_catalog(
        catalogs_dir / HARNESS_TOOLS_CSV,
        key_columns=("harness", "tool"),
        row_from_columns=_harness_tool_row_from_columns,
    )
    harness_tool_arguments = load_catalog(
        catalogs_dir / HARNESS_TOOL_ARGUMENTS_CSV,
        key_columns=("harness", "tool", "argument"),
        row_from_columns=functools.partial(
            _harness_tool_argument_row_from_columns, harness_tools=harness_tools
        ),
    )
    row_keys_by_tool: dict[HarnessTool, list[KnowledgeRowKey]] = {}
    for row_key in harness_tool_arguments.row_keys:
        tool = HarnessTool(row_key[0], row_key[1])
        row_keys_by_tool.setdefault(tool, []).append(row_key)
    _check_handle_kinds_agree(harness_tool_arguments, row_keys_by_tool)
    harness_return_code_interpretations = load_catalog(
        catalogs_dir / HARNESS_RETURN_CODE_INTERPRETATIONS_CSV,
        key_columns=("harness", "tool", "return_code_interpretation"),
        row_from_columns=functools.partial(
            _harness_return_code_interpretation_row_from_columns,
            harness_tools=harness_tools,
        ),
    )
    return _ToolCallCatalogs(
        harness_tools,
        harness_tool_arguments,
        {tool: tuple(row_keys) for tool, row_keys in row_keys_by_tool.items()},
        harness_return_code_interpretations,
    )


@dataclass(frozen=True, slots=True)
class _ToolCallCatalogs:
    """Loaded catalogs of `convert_tool_calls`, shared by every `ToolCallKnowledge` of a process."""

    harness_tools: Catalog[_HarnessToolRow]
    harness_tool_arguments: Catalog[_HarnessToolArgumentRow]
    # The keys of the argument rows of each tool, so `ToolCallKnowledge` can look up the rows of the arguments a call has.
    argument_row_keys_by_tool: Mapping[HarnessTool, tuple[KnowledgeRowKey, ...]]
    harness_return_code_interpretations: Catalog[_HarnessReturnCodeInterpretationRow]


@dataclass(frozen=True, slots=True)
class _HarnessToolRow:
    """Checked values of one row of `harness_tools.csv`, kept in its catalog and merged into a `HarnessToolLabel` when `ToolCallKnowledge` answers."""

    action_type: str  # the name of a `ToolCallAction` member class, or `DEFERRED`
    stops_execution: bool  # False for a tool whose action is no `PollAction`


@dataclass(frozen=True, slots=True)
class _HarnessToolArgumentRow:
    """Checked values of one row of `harness_tool_arguments.csv`, kept in its catalog and merged into a `HarnessToolLabel` when `ToolCallKnowledge` answers."""

    action_field: str  # a field of the action class of the tool
    handle_kind: ExecutionHandleKind | None  # None when the column is empty


@dataclass(frozen=True, slots=True)
class _HarnessReturnCodeInterpretationRow:
    """Checked value of one row of `harness_return_code_interpretations.csv`, kept in its catalog and given by `ToolCallKnowledge` as the answer."""

    exit_code: int


def _harness_tool_row_from_columns(columns: Mapping[str, str]) -> _HarnessToolRow:
    """Read one row of `harness_tools.csv`, raising ValueError on an action type that names no class and on a `stops_execution` other than `yes` or `no` for a poll tool and empty for any other tool."""
    action_type = columns["action_type"]
    if action_type != DEFERRED and action_type not in TOOL_CALL_ACTION_CLASSES:
        raise ValueError(f"action_type {action_type!r} names no ToolCallAction class")
    stops_execution = columns["stops_execution"]
    # Only a `PollAction` can stop something, and an empty value there would be read as `no`.
    allowed = ("yes", "no") if action_type == PollAction.__name__ else ("",)
    if stops_execution not in allowed:
        raise ValueError(
            f"stops_execution of a {action_type} tool is {stops_execution!r}, not one of {allowed}"
        )
    return _HarnessToolRow(action_type, stops_execution == "yes")


def _harness_tool_argument_row_from_columns(
    columns: Mapping[str, str], *, harness_tools: Catalog[_HarnessToolRow]
) -> _HarnessToolArgumentRow:
    """Read one row of `harness_tool_arguments.csv`, raising ValueError on a tool without a row, on a field that the action class of the tool does not have and on a `handle_kind` that is no `ExecutionHandleKind` value or sits on a field other than `handles`."""
    tool_key = (columns["harness"], columns["tool"])
    # This lookup checks the file and answers no question of a step, so its count is dropped.
    tool_row = harness_tools.lookup(tool_key, KnowledgeUses())
    if tool_row is None:
        raise ValueError(f"the tool {tool_key} has no row in {HARNESS_TOOLS_CSV}")
    # A Deferred tool has no action class, so it can map no field.
    action_class = TOOL_CALL_ACTION_CLASSES.get(tool_row.action_type)
    field_names = {f.name for f in fields(action_class)} if action_class else set()
    action_field = columns["action_field"]
    if action_field not in field_names:
        raise ValueError(f"{tool_row.action_type} has no field {action_field!r}")
    if not columns["handle_kind"]:
        return _HarnessToolArgumentRow(action_field, None)
    if action_field != _HANDLES_FIELD:
        raise ValueError(f"handle_kind on the field {action_field!r}")
    return _HarnessToolArgumentRow(
        action_field, ExecutionHandleKind(columns["handle_kind"])
    )


def _check_handle_kinds_agree(
    harness_tool_arguments: Catalog[_HarnessToolArgumentRow],
    row_keys_by_tool: Mapping[HarnessTool, Sequence[KnowledgeRowKey]],
) -> None:
    """Raise ValueError when two `handles` arguments of one tool differ in `handle_kind`, since a label holds one kind for all handles of the tool."""
    # These lookups check the file and answer no question of a step, so their counts are dropped.
    unused = KnowledgeUses()
    for tool, row_keys in row_keys_by_tool.items():
        rows = (harness_tool_arguments.lookup(key, unused) for key in row_keys)
        handle_kinds = {
            row.handle_kind
            for row in rows
            if row is not None and row.action_field == _HANDLES_FIELD
        }
        if len(handle_kinds) > 1:
            raise ValueError(f"the handles arguments of {tool} differ in handle_kind")


def _harness_return_code_interpretation_row_from_columns(
    columns: Mapping[str, str], *, harness_tools: Catalog[_HarnessToolRow]
) -> _HarnessReturnCodeInterpretationRow:
    """Read one row of `harness_return_code_interpretations.csv`, raising ValueError on a tool without a row and on an `exit_code` that is no integer."""
    tool_key = (columns["harness"], columns["tool"])
    # This lookup checks the file and answers no question of a step, so its count is dropped.
    if harness_tools.lookup(tool_key, KnowledgeUses()) is None:
        raise ValueError(f"the tool {tool_key} has no row in {HARNESS_TOOLS_CSV}")
    return _HarnessReturnCodeInterpretationRow(int(columns["exit_code"]))
