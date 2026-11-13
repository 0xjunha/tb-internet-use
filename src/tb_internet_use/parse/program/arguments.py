"""Split a program's arguments into options with their values and plain arguments, by the option syntax of each program.

One option letter takes a value in one program and not in another, e.g. `-o out` names curl's output file, while `-n 5` gives tail a line count.
Reading every word that does not start with a dash as a plain argument would take 5 in `tail -n 5 fetch.log` for a file.
"""

from dataclasses import dataclass

from tb_internet_use.parse.program.option_syntax_tables import (
    OPTION_SYNTAX_OF_PROGRAM,
    OptionSyntax,
)

# The syntax of a program without a row in `OPTION_SYNTAX_OF_PROGRAM`, which has no option with a value.
_NO_OPTIONS_WITH_VALUE = OptionSyntax()


@dataclass(frozen=True, slots=True)
class ParsedArguments:
    """Arguments of one run of a program, split into its options and its plain arguments."""

    # Each option as written without its value, e.g. -o for `-o out` or `-oout`, with its value, or None when it takes none.
    options: tuple[tuple[str, str | None], ...]
    # Arguments that are neither options nor option values, e.g. install and requests in `pip install -q requests`.
    plain_arguments: tuple[str, ...]
    # The 0-based index of each plain argument among all the arguments, so the words from one on can be taken as written.
    plain_argument_indexes: tuple[int, ...]

    def has_option(self, *names: str) -> bool:
        """Check whether one of the named options was given, e.g. `-s` or `--silent`."""
        return any(name in names for name, _ in self.options)

    def option_values(self, *names: str) -> tuple[str, ...]:
        """List the values of the named options in order, e.g. the URL of `--index-url u`."""
        return tuple(
            value for name, value in self.options if name in names and value is not None
        )


def parse_arguments(program_name: str, arguments: tuple[str, ...]) -> ParsedArguments:
    """Split a program's arguments into options with their values and plain arguments, by the program's option syntax.

    A short option cluster such as `-fsSL` gives one option per letter. Words after `--` are plain.
    """
    syntax = OPTION_SYNTAX_OF_PROGRAM.get(program_name, _NO_OPTIONS_WITH_VALUE)
    options: list[tuple[str, str | None]] = []
    plain_argument_indexes: list[int] = []
    index = 0
    while index < len(arguments):
        word = arguments[index]
        following = arguments[index + 1] if index + 1 < len(arguments) else None
        if word == "--":
            plain_argument_indexes += range(index + 1, len(arguments))
            break
        if word.startswith("--") or word in syntax.one_dash_long_options:
            name, has_value, value = word.partition("=")
            if has_value:
                options.append((name, value))
            elif name in syntax.long_options_with_value:
                options.append((name, following))
                index += 1
            else:
                options.append((name, None))
        elif word.startswith("-$"):
            # The letters come from a variable when the command runs, e.g. `head -$n f`, so the option takes no value here.
            options.append((word, None))
        elif word.startswith("-") and len(word) > 1:
            index += _read_short_option_cluster(word, following, syntax, options)
        elif syntax.options_end_at_first_plain_argument:
            plain_argument_indexes += range(index, len(arguments))
            break
        else:
            plain_argument_indexes.append(index)
        index += 1
    return ParsedArguments(
        tuple(options),
        tuple(arguments[i] for i in plain_argument_indexes),
        tuple(plain_argument_indexes),
    )


def file_arguments(program_name: str, parsed: ParsedArguments) -> tuple[str, ...]:
    """List the plain arguments that name files, leaving out a script or pattern, e.g. f in `sed -i 's/a/b/' f` or `grep error f`."""
    syntax = OPTION_SYNTAX_OF_PROGRAM.get(program_name, _NO_OPTIONS_WITH_VALUE)
    takes_script_argument = bool(syntax.script_options) and not parsed.has_option(
        *syntax.script_options
    )
    return (
        parsed.plain_arguments[1:] if takes_script_argument else parsed.plain_arguments
    )


def _read_short_option_cluster(
    word: str,
    following: str | None,
    syntax: OptionSyntax,
    options: list[tuple[str, str | None]],
) -> int:
    """Add the options of a short option cluster such as `-fsSL` or `-oout`, and return 1 when the next word was its value, else 0."""
    letters = word[1:]
    for position, letter in enumerate(letters):
        if letter in syntax.short_options_with_value:
            rest = letters[position + 1 :]
            options.append((f"-{letter}", rest or following))
            return 0 if rest else 1
        options.append((f"-{letter}", None))
    return 0
