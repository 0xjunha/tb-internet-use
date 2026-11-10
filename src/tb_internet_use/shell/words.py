"""Read one word of a shell text, as the shell passes it to the command."""

import re

from tree_sitter import Node

# Node types whose value is known only when the text runs.
_EXPANSION_NODE_TYPES = frozenset(
    {
        "simple_expansion",  # `$A`
        "expansion",  # `${A:-x}`
        "command_substitution",  # `$(ls)` or `` `ls` ``
        "process_substitution",  # `<(ls)` or `>(ls)`
        "arithmetic_expansion",  # `$((1 + 2))`
    }
)
# Outside quotes, a backslash keeps the next character as is.
# Before a line break, it joins the two lines.
_UNQUOTED_ESCAPE = re.compile(r"\\(.)", re.DOTALL)
# Inside double quotes, a backslash escapes only these characters.
_DOUBLE_QUOTED_ESCAPE = re.compile(r'\\([$`"\\\n])')


def word_value(word_node: Node) -> str:
    """Strip a word's quotes and escapes as the shell does, e.g. `a b` for `'a b'` or `a\\ b`.

    An expansion is kept as written, e.g. `$A/x` for `"$A/x"`.
    So are tilde, glob and brace words such as `~/x`, `*.py` and `{a,b}`, and escapes in `$'...'`.
    """
    text = node_text(word_node)
    if word_node.type in _EXPANSION_NODE_TYPES:
        return text
    if word_node.type == "raw_string":  # `'a'`
        return text[1:-1]
    if word_node.type == "ansi_c_string":  # `$'a'`
        return text[2:-1]
    if word_node.type == "string":  # `"a"`
        return _double_quoted_value(word_node)
    if word_node.type == "concatenation":  # `a"b"'c'`
        return "".join(word_value(part) for part in word_node.children)
    return _UNQUOTED_ESCAPE.sub(_character_after_backslash, text)


def _double_quoted_value(string_node: Node) -> str:
    """Strip the quotes of a double-quoted word and undo its escapes outside its expansions."""
    source = string_node.text or b""
    start = string_node.start_byte
    parts: list[str] = []
    position = start + 1  # after the opening quote
    for child in string_node.named_children:
        if child.type in _EXPANSION_NODE_TYPES:
            parts.append(
                _unescaped_in_double_quotes(
                    source[position - start : child.start_byte - start]
                )
            )
            parts.append(node_text(child))
            position = child.end_byte
    parts.append(
        _unescaped_in_double_quotes(source[position - start : len(source) - 1])
    )
    return "".join(parts)


def node_text(node: Node) -> str:
    """Decode a tree-sitter node's text as written."""
    return node.text.decode("utf-8", "replace") if node.text else ""


def _unescaped_in_double_quotes(text: bytes) -> str:
    decoded = text.decode("utf-8", "replace")
    return _DOUBLE_QUOTED_ESCAPE.sub(_character_after_backslash, decoded)


def _character_after_backslash(match: re.Match[str]) -> str:
    """Replace `\\x` with x, and drop an escaped line break."""
    character = match.group(1)
    return "" if character == "\n" else character


def word_has_expansion(word_node: Node) -> bool:
    """Check whether a word holds `$A`, `${A}`, `$(...)`, backticks, `<(...)` or `$((...))`."""
    return word_node.type in _EXPANSION_NODE_TYPES or any(
        word_has_expansion(child) for child in word_node.children
    )
