"""The declared result formats of every harness agree with the harness tool catalog, with their own order, and with the names that tie a converted result to its catalog and audit rows."""

import csv
import json
from collections import Counter, defaultdict
from typing import Any

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
from tb_internet_use.tool_call.harnesses import converter_for
from tb_internet_use.tool_call.model import (
    HarnessTool,
    HarnessToolCall,
    MatchedFormat,
    ToolCallKey,
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

# A made-up result per format that converter code builds instead of a declared list, by (harness, tool).
# A new such format also shows up as a `special` row of the audit CSV.
_RESULT_BY_SPECIAL_FORMAT_TOOL = {
    ("claude-code", "Read"): {"content": json.dumps({"type": "image", "source": {}})},
    ("codex", "web_search_call"): {"content": None},
}


def _special_formats() -> dict[tuple[str, str], set[str]]:
    """Convert the made-up result of each tool and give the name of the format its converter built, so that a renamed format is seen."""
    names: dict[tuple[str, str], set[str]] = {}
    for (harness, tool), result in _RESULT_BY_SPECIAL_FORMAT_TOOL.items():
        harness_tool_call = HarnessToolCall(
            ToolCallKey("t", "main", 1, 0), HarnessTool(harness, tool), "id", {}, result
        )
        tool_call_result = converter_for(harness).convert_result(
            harness_tool_call,
            result,
            knowledge=ToolCallKnowledge(),
            judgment_rule_use_counts=Counter(),
        )
        assert isinstance(tool_call_result.harness_result_format, MatchedFormat)
        names[harness, tool] = {str(tool_call_result.harness_result_format)}
    return names


SPECIAL_FORMATS = _special_formats()


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


def test_no_declared_or_special_name_is_a_reserved_value():
    # The types keep them apart, but CSV rows hold names as text.
    reserved = {str(member) for member in UnmatchedFormat}
    declared = {name for by_name in _declared().values() for name in by_name}
    special = set().union(*SPECIAL_FORMATS.values())
    assert not (declared | special) & reserved


def test_special_names_do_not_reuse_a_declared_name_of_their_tool():
    declared = _declared()
    for key, names in SPECIAL_FORMATS.items():
        assert not names & set(declared[key]), key


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
