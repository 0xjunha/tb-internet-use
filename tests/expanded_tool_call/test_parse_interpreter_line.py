"""Tests for expanded_tool_call/parse_interpreter_line.py."""

import pytest

from tb_internet_use.expanded_tool_call.model import (
    InterpreterLine,
    UnreadableInterpreterLine,
)
from tb_internet_use.expanded_tool_call.parse_interpreter_line import (
    parse_interpreter_line,
)


@pytest.mark.parametrize(
    ("line", "interpreter_line"),
    [
        ("#!/bin/bash", InterpreterLine("bash", ())),
        ("#!/bin/bash -e", InterpreterLine("bash", ("-e",))),
        ("#! /usr/bin/python3", InterpreterLine("python3", ())),
        ("#!/usr/bin/env python3", InterpreterLine("python3", ())),
        ("#!/usr/bin/env -S python3 -u", InterpreterLine("python3", ("-u",))),
        (
            "#!/usr/bin/env PYTHONUNBUFFERED=1 python3",
            InterpreterLine("python3", ()),
        ),
        ("#!python", InterpreterLine("python", ())),
        ("import requests", None),
        (" #!/bin/bash", None),
    ],
)
def test_interpreter_of_a_first_line(
    line: str, interpreter_line: InterpreterLine | None
):
    assert parse_interpreter_line(line) == interpreter_line


@pytest.mark.parametrize(
    "line", ["#!", "#!/usr/bin/env", "#!/usr/bin/env -S", "#!/usr/bin/"]
)
def test_a_line_that_names_no_interpreter_is_unreadable(line: str):
    assert parse_interpreter_line(line) == UnreadableInterpreterLine()
