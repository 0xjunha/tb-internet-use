"""Tests for the declarations of program output line patterns in program_output.py, beyond the meanings that `NetworkRequestResultKnowledge` gives example lines."""

import pytest

from tb_internet_use.knowledge.declarations.network_request_result.output_line_patterns import (
    program_output,
)
from tb_internet_use.network_request_result.model import (
    OutputLineKind,
    PrintingProgram,
)


def test_pattern_printed_only_by_one_program_cannot_name_other_printing_programs():
    with pytest.raises(ValueError, match="pattern x gives both"):
        program_output._make_program_output_pattern(
            "x",
            OutputLineKind.INSTALLED,
            r"x",
            printed_only_by=PrintingProgram.PIP,
            printed_also_by=(PrintingProgram.UV,),
        )


@pytest.mark.parametrize(
    ("printed_only_by", "printed_also_by"),
    [
        (PrintingProgram.UNNAMED_PROGRAM, ()),
        (None, (PrintingProgram.CURL, PrintingProgram.UNNAMED_PROGRAM)),
    ],
)
def test_pattern_cannot_name_the_program_that_no_pattern_names(
    printed_only_by: PrintingProgram | None,
    printed_also_by: tuple[PrintingProgram, ...],
):
    with pytest.raises(ValueError, match="pattern x names unnamed_program"):
        program_output._make_program_output_pattern(
            "x",
            OutputLineKind.INSTALLED,
            r"x",
            printed_only_by=printed_only_by,
            printed_also_by=printed_also_by,
        )
