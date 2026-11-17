"""The declared result formats of every harness agree with the harness tool catalog, with their own order, and with the names that tie a converted result to its catalog and audit rows, and a tool has no format for a form it never returned."""

import csv
import inspect
from collections import defaultdict
from typing import Any

import pytest

from tb_internet_use.knowledge.harness_result_format_audit import (
    iter_declared_format_lists,
    iter_declared_formats,
    render_text_format,
)
from tb_internet_use.knowledge.harness_result_format_declaration import (
    PLACEHOLDER_REGEX,
    PLACEHOLDER_TYPE_PATTERNS,
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


def _catalog_tools() -> set[HarnessTool]:
    """List the tools with a row in the committed catalog, read from the CSV itself since a door only answers lookups."""
    with (TOOL_CALL_CATALOGS_DIR / HARNESS_TOOLS_CSV).open(newline="") as f:
        return {HarnessTool(row["harness"], row["tool"]) for row in csv.DictReader(f)}


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


# Made-up results of forms that tools of other harnesses or other tools of the same harness have, but that these tools never returned in the trajectories, as (harness, tool, raw text, JSON object).
_RESULTS_OF_FORMS_NEVER_SEEN = (
    ("claude-code", "Write", "Refusing to write through symlink: /a hint", None),
    ("codex", "exec_command", "write_stdin failed: no session", None),
    ("codex", "write_stdin", "exec_command failed: no shell", None),
    ("cursor-cli", "awaitToolCall", None, {"error": {"message": "m"}}),
    ("cursor-cli", "mcpToolCall", None, {"error": {"message": "m"}}),
    ("muse-code", "write_file", "tool failed: denied", None),
    ("muse-code", "bash", None, {"terminal_status": "cancelled", "output": ""}),
)


def _declared() -> dict[tuple[str, str], dict[str, list[Any]]]:
    """Distinct declared formats by (harness, tool) and name. One tool may have several lists."""
    names: dict[tuple[str, str], dict[str, list[Any]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for harness, tool, fmt in iter_declared_formats():
        same_name = names[(harness, tool)][fmt.name]
        if fmt not in same_name:  # a format shared by two lists is one format
            same_name.append(fmt)
    return names


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
        (harness, tool, fmt.name, fmt.judgment_rule)
        for harness, tool, fmt in iter_declared_formats()
        if fmt.judgment_rule is not None
        and not inspect.isfunction(getattr(judgment_rules, fmt.judgment_rule, None))
    ]
    assert not unknown_rules


def test_every_placeholder_type_has_a_sample():
    assert set(_SAMPLE_BY_TYPE) == set(PLACEHOLDER_TYPE_PATTERNS)


def test_tools_with_declared_formats_are_in_the_catalog():
    # A harness or tool name that the catalog does not have would leave its formats unused.
    declared = {
        HarnessTool(harness, tool) for harness, tool, _ in iter_declared_format_lists()
    }
    assert declared - _catalog_tools() == set()


def _rendered(fmt: HarnessTextResultFormat) -> str:
    values = {
        p[1]: _SAMPLE_BY_TYPE[p[2]] for p in PLACEHOLDER_REGEX.finditer(fmt.template)
    }
    return render_text_format(fmt, values)


def test_every_text_format_is_the_first_match_of_its_own_template():
    # A general format before a more specific one would take its results.
    shadowed: list[tuple[str, str, str, Any]] = []
    for harness, tool, formats in iter_declared_format_lists():
        for fmt in formats.formats:
            if not isinstance(fmt, HarnessTextResultFormat):
                continue
            found = formats.match(_rendered(fmt))
            if found is None or found[0].name != fmt.name:
                shadowed.append((harness, tool, fmt.name, found and found[0].name))
    assert not shadowed


@pytest.mark.parametrize(
    ("harness", "tool", "raw_text", "tool_result_json"), _RESULTS_OF_FORMS_NEVER_SEEN
)
def test_a_form_that_a_tool_never_returned_in_the_trajectories_is_not_declared_for_it(
    harness: str, tool: str, raw_text: str | None, tool_result_json: Any
):
    # Only formats that occur in the data are declared, so such a result is unknown and not a guess.
    harness_result_format = ToolCallKnowledge().harness_result_format(
        HarnessTool(harness, tool),
        raw_text,
        tool_result_json,
        is_marked_as_error=False,
    )
    assert harness_result_format is UnmatchedFormat.UNKNOWN
