"""Decide what the trajectory and the program catalogs do not settle about what a tool call ran, one named rule per situation, e.g. how to read a command word that holds `$OPTS`.

Each rule is a judgment, not a reading of the trajectory or a fact of a catalog, so it lives here where it can be found and changed.
For example, `curl $OPTS u` shows only the word `$OPTS`, which may stand for several options or none when the command runs, and only a rule says how `expand_tool_calls` reads it.

Each rule adds one to `use_counts` under its own function name every time it decides something, so that audits can show how much of the output leans on each rule.
The counts are for tracking and never go into an `ExpandedToolCall`.

A rule is provisional until the user decides it. The last paragraph of each docstring marks it `Provisional.` or `Decided.`
"""

from collections import Counter


def treat_word_with_expansion_as_one_argument(
    word: str, *, use_counts: Counter[str]
) -> bool:
    """Read a command word that holds an expansion as one word where it is written, i.e. one argument or one option value, e.g. `$OPTS` in `curl $OPTS u`, `$PKGS` in `pip install $PKGS` or `$F` in `curl -o $F u`.

    The words of a command are as written in the trajectory, so such a word can stand for several options, several arguments or none when the command runs.
    `expand_program_invocations` asks it for each word of `ShellCommand.expansion_word_indexes` that ends as an argument or as the value of an option, once all words of its program are placed.
    It does not ask it for the program word, which is an `UnknownProgramInvocation`, for a skipped `NAME=value` word, or for a word whose place makes it a cluster of one-letter options, which is unread.
    On `True` the word is one argument or one value, and on `False` it and the words after it are unread words, from the word of the option for a value.
    A use is such a word.

    Provisional. It keeps the choice of the earlier code, which read such a word as one argument.
    """
    use_counts[treat_word_with_expansion_as_one_argument.__name__] += 1
    return True
