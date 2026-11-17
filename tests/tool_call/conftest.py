"""Fixtures shared by the tests of the tool_call package."""

import pytest


@pytest.fixture
def shell_text_joined_after_three_repairs() -> str:
    """Give a made-up shell text whose lines tree-sitter-bash still joins after three repairs, e.g. `f j` from the lines `d 2>/dev/null | e | f` and `j 2>&1`, while the tree has no syntax error."""
    return (
        "d 2>/dev/null | e | f\n"
        "v | w\n"
        "{ a | b | c\n"
        "d 2>/dev/null | e | f\n"
        "v | w\n"
        "}\n"
        "d 2>/dev/null | e | f\n"
        "j 2>&1\n"
        "x 2>&1 | y | z | w\n"
        "a 2>&1 | b | c\n"
        "}\n"
        "j 2>&1\n"
        "z"
    )
