"""Format names tie a converted result to its catalog and audit rows, so they must not collide."""

from collections import defaultdict
from typing import Any

from tb_internet_use.toolcall.harnesses import CONVERTERS
from tb_internet_use.toolcall.model import UnmatchedFormat

# Formats built by converter code instead of a declared list, by (harness, tool).
SPECIAL_FORMATS = {
    ("claude-code", "Read"): {"image"},
    ("codex", "web_search_call"): {"no_content"},
}


def _declared() -> dict[tuple[str, str], dict[str, list[Any]]]:
    """Distinct declared formats by (harness, tool) and name; one tool may have several lists."""
    names: dict[tuple[str, str], dict[str, list[Any]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for harness, converter in CONVERTERS.items():
        for tool, formats in converter.declared_formats():
            for fmt in formats.formats:
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
