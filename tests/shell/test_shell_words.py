"""Tests for shell/words.py."""

import pytest
import tree_sitter_bash
from tree_sitter import Language, Node, Parser

from tb_internet_use.shell.words import word_has_expansion, word_value

PARSER = Parser(Language(tree_sitter_bash.language()))


def _word_node(word: str) -> Node:
    """The node of `word` as the only argument of a command."""
    tree = PARSER.parse(f"echo {word}".encode())
    (command,) = tree.root_node.children
    (argument,) = command.children_by_field_name("argument")
    return argument


@pytest.mark.parametrize(
    ("word", "value", "has_expansion"),
    [
        ("plain", "plain", False),
        ("'a b'", "a b", False),
        ("''", "", False),
        ("'$A'", "$A", False),
        ('""', "", False),
        ('"a $B c"', "a $B c", True),
        ('"${A}b"', "${A}b", True),
        # In double quotes, \ escapes only $ ` " \ and a line break.
        ('"a \\"b\\" \\$c \\\\ d"', 'a "b" $c \\ d', False),
        ('"a \\`b\\`"', "a `b`", False),
        ('"\\$A"', "$A", False),
        ('"a\\nb"', "a\\nb", False),
        ('"a\\\nb"', "ab", False),
        ('"a\nb"', "a\nb", False),
        # An expansion inside double quotes is kept as written, escapes included.
        ('"$(echo \\"x\\")"', '$(echo \\"x\\")', True),
        ('"é $(a) ü"', "é $(a) ü", True),
        ("$'a\\tb'", "a\\tb", False),
        ("a\"b\"'c'$D", "abc$D", True),
        ("'it'\\''s'", "it's", False),
        ("a$", "a$", False),
        ("$A", "$A", True),
        ("${A:-x}", "${A:-x}", True),
        ("$(ls)", "$(ls)", True),
        ("$(echo a\\ b)", "$(echo a\\ b)", True),
        ("`ls`", "`ls`", True),
        ("<(ls)", "<(ls)", True),
        ("$((1+2))", "$((1+2))", True),
        ("a\\ b", "a b", False),
        ("\\$A", "$A", False),
        ("\\;", ";", False),
        ("a\\\\b", "a\\b", False),
        ("~/x", "~/x", False),
        ("*.py", "*.py", False),
        ("{a,b}", "{a,b}", False),
        ("{1..3}", "{1..3}", False),
    ],
)
def test_word_value_and_expansion(word: str, value: str, has_expansion: bool):
    node = _word_node(word)
    assert word_value(node) == value
    assert word_has_expansion(node) == has_expansion
