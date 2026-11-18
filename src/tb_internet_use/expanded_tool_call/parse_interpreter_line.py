"""Read the interpreter of a file that a command runs by its path from the first line of the file, e.g. python3 from `#!/usr/bin/env python3`.

A file run as `./run` names the program that runs its text only in its `#!` line, so the language of the text and the options its shell starts with come from that line, e.g. `-e` of `#!/bin/bash -e`.
"""

import re

from tb_internet_use.expanded_tool_call.model import (
    InterpreterLine,
    UnreadableInterpreterLine,
)

# The mark that starts an interpreter line.
_INTERPRETER_LINE_MARK = "#!"
# The program that finds the interpreter by the name after it, e.g. env in `#!/usr/bin/env python3`.
_PROGRAM_FINDING_INTERPRETER = "env"
# A word after env that sets a variable, e.g. `PYTHONUNBUFFERED=1`, which env skips before the interpreter name.
_ASSIGNMENT_WORD = re.compile(r"[^=]+=")


def parse_interpreter_line(
    line: str,
) -> InterpreterLine | UnreadableInterpreterLine | None:
    """Read the interpreter name of a `#!` line, without its folder, and the words after it, e.g. bash and `("-e",)` for `#!/bin/bash -e`.

    When the line names env, the name is the first word after env that is neither an option nor `NAME=value`, e.g. python3 for `#!/usr/bin/env python3`.
    It is None for a line that does not start with `#!`, which names no interpreter.
    """
    if not line.startswith(_INTERPRETER_LINE_MARK):
        return None
    words = line[len(_INTERPRETER_LINE_MARK) :].split()
    if not words:
        return UnreadableInterpreterLine()
    interpreter_word_index = 0
    if _name_without_folder_of(words[0]) == _PROGRAM_FINDING_INTERPRETER:
        interpreter_word_index = next(
            (
                word_index
                for word_index, word in enumerate(words)
                if word_index > 0
                and not word.startswith("-")
                and _ASSIGNMENT_WORD.match(word) is None
            ),
            len(words),
        )
    if interpreter_word_index == len(words):
        return UnreadableInterpreterLine()
    interpreter_name = _name_without_folder_of(words[interpreter_word_index])
    if not interpreter_name:
        return UnreadableInterpreterLine()
    return InterpreterLine(interpreter_name, tuple(words[interpreter_word_index + 1 :]))


def _name_without_folder_of(word: str) -> str:
    """Give the part of a path after its last `/`, e.g. python3 for /usr/bin/python3."""
    return word.rsplit("/", 1)[-1]
