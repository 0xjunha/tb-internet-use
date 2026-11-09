"""The converters' declarations agree with the tool catalog and with their own order."""

from typing import Any

from tb_internet_use.toolcall.catalog_loader import DEFERRED, load_catalog
from tb_internet_use.toolcall.harnesses import CONVERTERS, converter_for
from tb_internet_use.toolcall.model import HarnessTool, RawToolCall, ToolCallKey
from tb_internet_use.toolcall.result_format_audit import render_text_format
from tb_internet_use.toolcall.result_formats import (
    PLACEHOLDER_REGEX,
    PLACEHOLDER_TYPE_PATTERNS,
    HarnessTextResultFormat,
)

CATALOG = load_catalog()

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


def test_every_placeholder_type_has_a_sample():
    assert set(_SAMPLE_BY_TYPE) == set(PLACEHOLDER_TYPE_PATTERNS)


def test_every_harness_of_the_catalog_has_a_converter():
    assert set(CONVERTERS) == {tool.harness for tool in CATALOG}


def test_tools_named_by_a_converter_are_in_the_catalog_and_polls_where_needed():
    for harness, converter in CONVERTERS.items():
        named = {*converter.text_formats, *converter.json_formats}
        polls = {*converter.stop_tools, *converter.argument_handle_kinds}
        for tool in named | polls:
            assert HarnessTool(harness, tool) in CATALOG, (harness, tool)
        for tool in polls:
            label = CATALOG[HarnessTool(harness, tool)]
            assert label.action_type == "PollAction", (harness, tool)


def test_every_deferred_tool_gets_an_action_even_without_arguments():
    for tool, label in CATALOG.items():
        if label.action_type == DEFERRED:
            raw = RawToolCall(ToolCallKey("t", "main", 1, 0), tool, "id", {}, None)
            assert converter_for(tool.harness).deferred_action(raw, None) is not None


def _rendered(fmt: HarnessTextResultFormat) -> str:
    values = {
        p[1]: _SAMPLE_BY_TYPE[p[2]] for p in PLACEHOLDER_REGEX.finditer(fmt.template)
    }
    return render_text_format(fmt, values)


def test_every_text_format_is_the_first_match_of_its_own_template():
    # A general format before a more specific one would take its results.
    shadowed: list[tuple[str, str, str, Any]] = []
    for harness, converter in CONVERTERS.items():
        for tool, formats in converter.declared_formats():
            for fmt in formats.formats:
                if not isinstance(fmt, HarnessTextResultFormat):
                    continue
                found = formats.match(_rendered(fmt))
                if found is None or found[0].name != fmt.name:
                    shadowed.append((harness, tool, fmt.name, found and found[0].name))
    assert not shadowed
