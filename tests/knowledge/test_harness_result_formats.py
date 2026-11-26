"""The declared result formats of every harness agree with the harness tool catalog, with their review record, with their own order, with a hand-written table of the judgment rule each names, and with the names that tie a converted result to its rows in the table of declared result formats and in the result format audit, and a tool has no format for results it never returned."""

import csv
import importlib.util
import inspect
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest

from tb_internet_use.knowledge.declarations.tool_call import harness_result_formats
from tb_internet_use.knowledge.declarations.tool_call.harness_result_format_declaration import (
    PLACEHOLDER_REGEX,
    HarnessTextResultFormat,
)
from tb_internet_use.knowledge.tool_call_knowledge import (
    HARNESS_TOOLS_CSV,
    TOOL_CALL_CATALOGS_DIR,
    ToolCallKnowledge,
)
from tb_internet_use.tool_call import judgment_rules
from tb_internet_use.tool_call.model import (
    HarnessTool,
    UnmatchedFormat,
)

_SPEC = importlib.util.spec_from_file_location(
    "harness_result_format_audit",
    Path(__file__).parents[2] / "scripts/harness_result_format_audit.py",
)
assert _SPEC is not None and _SPEC.loader is not None
harness_result_format_audit = importlib.util.module_from_spec(_SPEC)
# Registered as an import would do, so that the audit scripts loaded by other tests share it.
sys.modules[_SPEC.name] = harness_result_format_audit
_SPEC.loader.exec_module(harness_result_format_audit)


def _catalog_tools() -> set[HarnessTool]:
    """List the tools with a row in the committed catalog, read from the CSV itself since a knowledge class only answers lookups."""
    with (TOOL_CALL_CATALOGS_DIR / HARNESS_TOOLS_CSV).open(newline="") as f:
        return {HarnessTool(row["harness"], row["tool"]) for row in csv.DictReader(f)}


# The hand-filled review record of the declared result formats, one row per format.
_REVIEWS_CSV = (
    Path(harness_result_formats.__file__).parent / "harness_result_format_reviews.csv"
)
_REVIEWS_COLUMNS = ["harness", "tool", "format", "checked_against", "reviewed", "note"]


# One simple value per placeholder type, to render a template into a result.
_SAMPLE_BY_TYPE = {
    "int": "1",
    "uint": "1",
    "negative_int": "-1",
    "id": "a1",
    "word": "w",
    "line": "l",
    "rest_of_line": "r",
    "line_without_brackets": "b",
    "text": "t\nu",
    "numbered_tab": "1\tx\n2\ty",
    "numbered_pipe": "1|x\n2|y",
    "partly_numbered_arrow": "1→x\n2→y",
}


# Made-up results of formats that tools of other harnesses or other tools of the same harness have, but that these tools never returned in the trajectories, as (harness, tool, raw text, JSON object).
_RESULTS_OF_FORMATS_NEVER_SEEN = (
    ("claude-code", "Write", "Refusing to write through symlink: /a hint", None),
    ("codex", "exec_command", "write_stdin failed: no session", None),
    ("codex", "write_stdin", "exec_command failed: no shell", None),
    ("cursor-cli", "awaitToolCall", None, {"error": {"message": "m"}}),
    ("cursor-cli", "mcpToolCall", None, {"error": {"message": "m"}}),
    ("muse-code", "write_file", "tool failed: denied", None),
    ("muse-code", "bash", None, {"terminal_status": "cancelled", "output": ""}),
)


# The judgment rule that each declared format names in place of a status, written by hand so that a format cannot gain, lose or change its rule unseen.
# Each judgment rule with the formats that name it, as (harness, tool, format).
FORMATS_BY_JUDGMENT_RULE: dict[str, list[tuple[str, str, str]]] = {
    "treat_bash_output_without_exit_code_line_as_finished": [
        ("claude-code", "Bash", "persisted_output_cut_preview"),
        ("claude-code", "Bash", "persisted_output"),
        ("claude-code", "Bash", "persisted_output_partial"),
        ("claude-code", "Bash", "bare_output"),
    ],
    "treat_failed_file_tool_call_as_not_run": [
        ("claude-code", "Read", "unchanged"),
        ("claude-code", "Read", "pdf_tool_missing"),
        ("claude-code", "Read", "pdf_too_many_pages"),
        ("claude-code", "Read", "pdf_too_large"),
        ("claude-code", "Read", "image_too_large"),
        ("claude-code", "Read", "directory"),
        ("claude-code", "Read", "missing"),
        ("claude-code", "Read", "too_large"),
        ("copilot-cli", "view", "missing"),
        ("copilot-cli", "view", "invalid_range"),
        ("copilot-cli", "create", "exists"),
        ("copilot-cli", "create", "parent_missing"),
        ("copilot-cli", "edit", "failed"),
        ("copilot-cli", "view", "too_large"),
        ("cursor-cli", "readToolCall", "too_large"),
        ("cursor-cli", "readToolCall", "error"),
        ("cursor-cli", "editToolCall", "error"),
        ("grok-build", "read_file", "missing"),
        ("grok-build", "read_file", "directory"),
        ("grok-build", "read_file", "binary"),
        ("grok-build", "read_file", "too_large"),
        ("grok-build", "read_file", "range_too_large"),
        ("grok-build", "search_replace", "not_found"),
        ("grok-build", "search_replace", "not_unique"),
        ("grok-build", "search_replace", "same_strings"),
        ("grok-build", "search_replace", "missing"),
    ],
    "treat_tool_failure_message_as_not_run": [
        ("antigravity-cli", "run_command", "failed"),
        ("antigravity-cli", "manage_task", "rejected_arguments"),
        ("antigravity-cli", "manage_task", "failed"),
        ("antigravity-cli", "read_file", "failed"),
        ("antigravity-cli", "write_file", "failed"),
        ("antigravity-cli", "edit_file", "failed"),
        ("antigravity-cli", "search_web", "failed"),
        ("claude-code", "Bash", "tool_use_error"),
        ("claude-code", "Read", "tool_use_error"),
        ("claude-code", "Write", "tool_use_error"),
        ("claude-code", "Edit", "tool_use_error"),
        ("claude-code", "WebFetch", "tool_use_error"),
        ("claude-code", "Monitor", "tool_use_error"),
        ("claude-code", "TaskStop", "tool_use_error"),
        ("codex", "exec_command", "rejected"),
        ("codex", "exec_command", "rejected_command"),
        ("codex", "write_stdin", "rejected_stdin"),
        ("copilot-cli", "read_bash", "invalid_delay"),
        ("copilot-cli", "create", "invalid_input"),
        ("copilot-cli", "edit", "invalid_input"),
        ("copilot-cli", "read_agent", "invalid_input"),
        ("devin", "exec", "rejected"),
        ("devin", "get_output", "rejected"),
        ("devin", "get_output", "failed_monitoring"),
        ("devin", "kill_shell", "rejected"),
        ("devin", "read", "rejected"),
        ("devin", "write", "rejected"),
        ("devin", "edit", "rejected"),
        ("devin", "webfetch", "rejected"),
        ("grok-build", "run_terminal_command", "rejected"),
        ("grok-build", "run_terminal_command", "rejected_arguments"),
        ("grok-build", "get_command_or_subagent_output", "rejected"),
        ("grok-build", "search_replace", "rejected_arguments"),
        ("muse-code", "bash", "rejected"),
        ("muse-code", "bash_input", "rejected"),
        ("muse-code", "read_file", "rejected"),
        ("muse-code", "edit_file", "rejected"),
    ],
    "treat_web_fetch_text_as_finished": [
        ("claude-code", "WebFetch", "page"),
        ("muse-code", "web_fetch", "page"),
    ],
    "treat_cut_off_web_search_as_finished": [("claude-code", "WebSearch", "cut_off")],
    "treat_script_syntax_error_as_not_run": [("codex", "exec", "failed_syntax")],
    "treat_web_search_call_without_content_as_finished": [
        ("codex", "web_search_call", "no_content")
    ],
    "treat_shell_id_with_exit_code_as_running": [
        ("cursor-cli", "shellToolCall", "background"),
        ("cursor-cli", "shellToolCall", "background_requested"),
    ],
    "treat_negative_exit_code_as_killed": [
        ("devin", "exec", "killed"),
        ("devin", "get_output", "killed_silent_twice"),
    ],
    "treat_get_output_without_exit_code_as_running": [
        ("devin", "get_output", "running_incremental"),
        ("devin", "get_output", "running"),
    ],
    "treat_written_input_as_running_target": [
        ("antigravity-cli", "manage_task", "input_sent"),
        ("devin", "write_to_process", "written"),
    ],
    "treat_failed_task_without_exit_code_as_killed": [
        ("grok-build", "get_command_or_subagent_output", "failed_signaled_empty"),
        ("grok-build", "get_command_or_subagent_output", "failed_signaled"),
    ],
    "treat_accepted_stop_request_as_killed": [("muse-code", "work_stop", "accepted")],
    "treat_idle_subagent_as_unknown_status": [("copilot-cli", "read_agent", "idle")],
    "treat_stop_request_for_ended_work_as_finished": [
        ("muse-code", "work_stop", "already_ended")
    ],
}


def _declared() -> dict[tuple[str, str], dict[str, list[Any]]]:
    """Group the distinct declared formats by (harness, tool) and name. One tool may have several lists."""
    names: dict[tuple[str, str], dict[str, list[Any]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for (
        harness,
        tool,
        harness_result_format,
    ) in harness_result_format_audit.iter_declared_formats():
        same_name = names[(harness, tool)][harness_result_format.name]
        if (
            harness_result_format not in same_name
        ):  # a format shared by two lists is one format
            same_name.append(harness_result_format)
    return names


def _rendered(harness_result_format: HarnessTextResultFormat) -> str:
    matched_values = {
        p[1]: _SAMPLE_BY_TYPE[p[2]]
        for p in PLACEHOLDER_REGEX.finditer(harness_result_format.template)
    }
    return harness_result_format_audit.render_text_format(
        harness_result_format, matched_values
    )


def test_one_name_means_one_format_within_a_tool():
    clashes = {
        (key, name)
        for key, by_name in _declared().items()
        for name, formats in by_name.items()
        if len(formats) > 1
    }
    assert not clashes


def test_no_declared_name_is_a_reserved_value():
    # The types keep them apart, but CSV rows hold names as text.
    reserved = {str(member) for member in UnmatchedFormat}
    declared = {name for by_name in _declared().values() for name in by_name}
    assert not declared & reserved


def test_every_judgment_rule_a_format_names_is_a_function_of_judgment_rules():
    unknown_rules = [
        (harness, tool, harness_result_format.name, harness_result_format.judgment_rule)
        for harness, tool, harness_result_format in harness_result_format_audit.iter_declared_formats()
        if harness_result_format.judgment_rule is not None
        and not inspect.isfunction(
            getattr(judgment_rules, harness_result_format.judgment_rule, None)
        )
    ]
    assert not unknown_rules


def test_each_format_names_the_judgment_rule_of_the_hand_written_table():
    expected = {
        harness_tool_format: judgment_rule
        for judgment_rule, harness_tool_formats in FORMATS_BY_JUDGMENT_RULE.items()
        for harness_tool_format in harness_tool_formats
    }
    assert len(expected) == sum(map(len, FORMATS_BY_JUDGMENT_RULE.values()))
    declared = {
        (harness, tool, harness_result_format.name): harness_result_format.judgment_rule
        for harness, tool, harness_result_format in harness_result_format_audit.iter_declared_formats()
        if harness_result_format.judgment_rule is not None
    }
    assert declared == expected


def test_tools_with_declared_formats_are_in_the_catalog():
    # A declared harness or tool name that the catalog does not have may be misspelled, and a misspelled name matches no call, so its formats would stay unused.
    declared = {
        HarnessTool(harness, tool)
        for harness, tool, _ in harness_result_format_audit.iter_declared_format_lists()
    }
    assert declared - _catalog_tools() == set()


def test_every_text_format_is_the_first_match_of_its_own_template():
    # A general format before a more specific one would take its results.
    shadowed: list[tuple[str, str, str, Any]] = []
    for (
        harness,
        tool,
        format_list,
    ) in harness_result_format_audit.iter_declared_format_lists():
        for harness_result_format in format_list.formats:
            if not isinstance(harness_result_format, HarnessTextResultFormat):
                continue
            found = format_list.match(_rendered(harness_result_format))
            if found is None or found[0].name != harness_result_format.name:
                shadowed.append(
                    (harness, tool, harness_result_format.name, found and found[0].name)
                )
    assert not shadowed


@pytest.mark.parametrize(
    ("harness", "tool", "raw_text", "tool_result_json"), _RESULTS_OF_FORMATS_NEVER_SEEN
)
def test_a_format_that_a_tool_never_returned_in_the_trajectories_is_not_declared_for_it(
    harness: str, tool: str, raw_text: str | None, tool_result_json: Any
):
    # Only formats that occur in the data are declared, so such a result is unknown and not a guess.
    matched_or_unmatched_format = ToolCallKnowledge().harness_result_format(
        HarnessTool(harness, tool),
        raw_text,
        tool_result_json,
        is_marked_as_error=False,
        is_harness_message=False,
    )
    assert matched_or_unmatched_format is UnmatchedFormat.UNKNOWN


def test_review_record_has_one_row_per_declared_format_in_the_declared_order():
    with _REVIEWS_CSV.open(newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert reader.fieldnames == _REVIEWS_COLUMNS
    reviewed = [(r["harness"], r["tool"], r["format"]) for r in rows]
    declared = [
        (harness, tool, harness_result_format.name)
        for harness, tool, harness_result_format in harness_result_format_audit.iter_declared_formats()
    ]
    missing = [key for key in declared if key not in reviewed]
    extra = [key for key in reviewed if key not in declared]
    assert not missing and not extra, (
        f"{_REVIEWS_CSV.name} lacks rows for {missing} and has rows for no declared format {extra}. Add or remove its rows by hand."
    )
    assert reviewed == declared, (
        f"the rows of {_REVIEWS_CSV.name} are not in the order of the declared formats"
    )
    bad_reviewed = [
        (r["harness"], r["tool"], r["format"], r["reviewed"])
        for r in rows
        if r["reviewed"] not in ("", "yes")
    ]
    assert not bad_reviewed, f"`reviewed` is neither empty nor `yes` in {bad_reviewed}"


@pytest.mark.parametrize(
    ("harness", "tool", "result_text", "format_name"),
    [
        ("grok-build", "write", "Wrote file successfully to /app/a.py.", "written"),
        (
            "muse-code",
            "write_file",
            "wrote 12 bytes to /app/a.py; note: created the parent folder",
            "written_note",
        ),
    ],
)
def test_the_path_of_a_write_result_leaves_out_the_text_after_it(
    harness, tool, result_text, format_name
):
    # The harness writes a `.` or a `;` right after the path, which is no part of the path that the call wrote.
    declaration = harness_result_formats.RESULT_FORMATS_BY_HARNESS[harness][tool]

    matched = declaration.harness_result_format_of(
        result_text, None, is_marked_as_error=False
    )

    assert not isinstance(matched, UnmatchedFormat)
    assert matched.format.name == format_name
    assert matched.matched_values["path"] == "/app/a.py"
