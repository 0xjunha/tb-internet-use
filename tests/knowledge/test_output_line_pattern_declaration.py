"""Tests for knowledge/output_line_pattern_declaration.py, with made-up patterns.

The meanings that the declared patterns give lines are tested through the door in test_network_request_result_knowledge.py.
"""

import pytest

from tb_internet_use.knowledge.output_line_pattern_declaration import (
    OutputLinePattern,
    OutputLinePatternTable,
)
from tb_internet_use.network_request_result.model import (
    OutputLineKind,
    PrintingProgram,
)

_STATUS = OutputLinePattern(
    "status",
    OutputLineKind.HTTP_STATUS,
    frozenset({PrintingProgram.CURL}),
    False,
    (r"status (?P<status_code>\d\d\d)",),
)
_REFUSED = OutputLinePattern(
    "refused", OutputLineKind.CONNECTION_FAILED, frozenset(), True, (r"refused",)
)


@pytest.mark.parametrize(
    ("patterns", "first_name"),
    [((_STATUS, _REFUSED), "status"), ((_REFUSED, _STATUS), "refused")],
)
def test_first_pattern_in_the_table_that_matches_a_line_wins(
    patterns: tuple[OutputLinePattern, ...], first_name: str
):
    table = OutputLinePatternTable("t", patterns)

    matched = table.matched_output_line_pattern_of("status 503 refused")

    assert matched is not None
    assert matched.output_line_pattern.name == first_name


def test_two_patterns_of_one_table_cannot_share_a_name():
    with pytest.raises(ValueError, match="two patterns of t have the same name"):
        OutputLinePatternTable("t", (_STATUS, _STATUS))
