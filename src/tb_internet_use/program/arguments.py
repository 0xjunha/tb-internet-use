"""Split a program's arguments into options with their values and plain arguments, by the option syntax of each program.

One option letter takes a value in one program and not in another, e.g. `-o out` names curl's output file, while `-n 5` gives tail a line count.
Reading every word that does not start with a dash as a plain argument would take 5 in `tail -n 5 fetch.log` for a file.
"""

from dataclasses import dataclass


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


@dataclass(frozen=True, slots=True)
class _OptionSyntax:
    """Option syntax of one program, used to tell its options and their values from its plain arguments."""

    # Letters of short options that take a value, either the rest of the word or the next word, e.g. o in `-o out` or `-oout`.
    short_options_with_value: str = ""
    # Long options that take the next word as their value unless written as `--name=value`, e.g. `--output out`.
    long_options_with_value: frozenset[str] = frozenset()
    # Options written with one dash that are one option, not a cluster of letters, e.g. wget's -nv.
    one_dash_long_options: frozenset[str] = frozenset()
    # The words after the first plain argument belong to the code or program it names, e.g. -c in `python get.py -c cfg`.
    options_end_at_first_plain_argument: bool = False
    # Options that give the script or pattern, e.g. -e in `sed -e s/a/b/ f`. Without one of them the first plain argument is the script.
    # Empty for a program that takes no script.
    script_options: frozenset[str] = frozenset()


_PIP_SYNTAX = _OptionSyntax(
    short_options_with_value="rceitfbd",
    long_options_with_value=frozenset(
        [
            "--requirement",
            "--constraint",
            "--editable",
            "--index-url",
            "--extra-index-url",
            "--target",
            "--find-links",
            "--prefix",
            "--root",
            "--cache-dir",
            "--python-version",
            "--platform",
            "--implementation",
            "--abi",
            "--only-binary",
            "--no-binary",
            "--upgrade-strategy",
            "--src",
            "--progress-bar",
            "--log",
            "--trusted-host",
            "--dest",
            "--python",
            "--report",
            "--timeout",
        ]
    ),
)
_NODE_PACKAGE_MANAGER_LONG_OPTIONS_WITH_VALUE = frozenset(
    [
        "--prefix",
        "--registry",
        "--cache",
        "--workspace",
        "--dir",
        "--filter",
        "--package",
        "--userconfig",
    ]
)
_NODE_PACKAGE_MANAGER_SYNTAX = _OptionSyntax(
    short_options_with_value="Cwp",
    long_options_with_value=_NODE_PACKAGE_MANAGER_LONG_OPTIONS_WITH_VALUE,
)
_APT_SYNTAX = _OptionSyntax(
    short_options_with_value="ot",
    long_options_with_value=frozenset({"--option", "--target-release"}),
)
_GREP_SYNTAX = _OptionSyntax(
    short_options_with_value="efmABCdD",
    long_options_with_value=frozenset(
        [
            "--regexp",
            "--file",
            "--max-count",
            "--after-context",
            "--before-context",
            "--context",
            "--include",
            "--exclude",
            "--exclude-dir",
        ]
    ),
    script_options=frozenset({"-e", "--regexp", "-f", "--file"}),
)
_HEAD_OR_TAIL_SYNTAX = _OptionSyntax(
    short_options_with_value="nc",
    long_options_with_value=frozenset({"--lines", "--bytes"}),
)
_TYPESCRIPT_RUNNER_SYNTAX = _OptionSyntax(
    short_options_with_value="e",
    long_options_with_value=frozenset({"--eval"}),
    options_end_at_first_plain_argument=True,
)
# Syntax of the programs whose options decide a file, a script, a target or code, by the name `normalized_program_name` gives.
# A program without one has no option with a value.
_SYNTAX_OF_PROGRAM = {
    "curl": _OptionSyntax(
        short_options_with_value="oDCEYyzKrxmcbFTeAuwXHdU",
        long_options_with_value=frozenset(
            [
                "--output",
                "--data",
                "--data-raw",
                "--data-binary",
                "--data-urlencode",
                "--data-ascii",
                "--header",
                "--request",
                "--write-out",
                "--user",
                "--user-agent",
                "--max-time",
                "--connect-timeout",
                "--proxy",
                "--retry",
                "--retry-delay",
                "--retry-max-time",
                "--cookie",
                "--cookie-jar",
                "--form",
                "--upload-file",
                "--range",
                "--referer",
                "--config",
                "--cacert",
                "--cert",
                "--key",
                "--resolve",
                "--dump-header",
                "--continue-at",
                "--limit-rate",
                "--output-dir",
                "--proto",
                "--max-redirs",
                "--url-query",
            ]
        ),
    ),
    "wget": _OptionSyntax(
        short_options_with_value="OoaPtTwUeiQlARBDIX",
        long_options_with_value=frozenset(
            [
                "--output-document",
                "--output-file",
                "--directory-prefix",
                "--tries",
                "--timeout",
                "--user-agent",
                "--header",
                "--post-data",
                "--post-file",
                "--input-file",
                "--user",
                "--password",
                "--load-cookies",
                "--save-cookies",
                "--limit-rate",
                "--wait",
            ]
        ),
        one_dash_long_options=frozenset({"-nv"}),
    ),
    "pip": _PIP_SYNTAX,
    "uv": _OptionSyntax(
        short_options_with_value="rcepi",
        long_options_with_value=_PIP_SYNTAX.long_options_with_value
        | {
            "--index",
            "--default-index",
            "--with",
            "--directory",
            "--project",
            "--from",
            "--group",
            "--extra",
        },
    ),
    "npm": _NODE_PACKAGE_MANAGER_SYNTAX,
    "pnpm": _NODE_PACKAGE_MANAGER_SYNTAX,
    "npx": _NODE_PACKAGE_MANAGER_SYNTAX,
    "bun": _OptionSyntax(
        short_options_with_value="Cwpe",
        long_options_with_value=_NODE_PACKAGE_MANAGER_LONG_OPTIONS_WITH_VALUE
        | {"--eval"},
    ),
    "deno": _OptionSyntax(
        short_options_with_value="e", long_options_with_value=frozenset({"--eval"})
    ),
    "apt": _APT_SYNTAX,
    "apt-get": _APT_SYNTAX,
    "git": _OptionSyntax(
        short_options_with_value="Cbojc",
        long_options_with_value=frozenset(
            [
                "--depth",
                "--branch",
                "--origin",
                "--reference",
                "--config",
                "--jobs",
                "--filter",
                "--shallow-since",
                "--upload-pack",
            ]
        ),
    ),
    "rsync": _OptionSyntax(
        short_options_with_value="eT",
        long_options_with_value=frozenset({"--exclude", "--include"}),
    ),
    "ping": _OptionSyntax(short_options_with_value="ciWws"),
    "nc": _OptionSyntax(short_options_with_value="pwsiq"),
    # The word after dig's -q or -x is the name to look up, so it stays a plain argument, e.g. a.org in `dig -q a.org`.
    "dig": _OptionSyntax(short_options_with_value="tcpfbky"),
    "host": _OptionSyntax(short_options_with_value="tcNRWm"),
    "gh": _OptionSyntax(
        short_options_with_value="XHfFRpDq",
        long_options_with_value=frozenset(
            {
                "--method",
                "--header",
                "--field",
                "--raw-field",
                "--jq",
                "--repo",
                "--pattern",
                "--dir",
            }
        ),
    ),
    "conda": _OptionSyntax(
        short_options_with_value="ncp",
        long_options_with_value=frozenset({"--name", "--channel", "--prefix"}),
    ),
    "huggingface-cli": _OptionSyntax(
        long_options_with_value=frozenset(
            [
                "--local-dir",
                "--repo-type",
                "--revision",
                "--cache-dir",
                "--token",
                "--include",
                "--exclude",
            ]
        )
    ),
    "python": _OptionSyntax(
        short_options_with_value="cmWX", options_end_at_first_plain_argument=True
    ),
    # node writes -p -e as `-pe 'code'`, whose value is the code.
    "node": _OptionSyntax(
        short_options_with_value="epr",
        long_options_with_value=frozenset({"--eval", "--print", "--require", "-pe"}),
        one_dash_long_options=frozenset({"-pe"}),
        options_end_at_first_plain_argument=True,
    ),
    "tsx": _TYPESCRIPT_RUNNER_SYNTAX,
    "ts-node": _TYPESCRIPT_RUNNER_SYNTAX,
    "head": _HEAD_OR_TAIL_SYNTAX,
    "tail": _HEAD_OR_TAIL_SYNTAX,
    "grep": _GREP_SYNTAX,
    "egrep": _GREP_SYNTAX,
    "rg": _OptionSyntax(
        short_options_with_value="efgtTmABCrj",
        long_options_with_value=frozenset(
            [
                "--regexp",
                "--file",
                "--glob",
                "--type",
                "--type-not",
                "--max-count",
                "--after-context",
                "--before-context",
                "--context",
                "--replace",
                "--threads",
            ]
        ),
        script_options=frozenset({"-e", "--regexp", "-f", "--file"}),
    ),
    "sed": _OptionSyntax(
        short_options_with_value="efl",
        long_options_with_value=frozenset({"--expression", "--file"}),
        script_options=frozenset({"-e", "--expression", "-f", "--file"}),
    ),
    "awk": _OptionSyntax(
        short_options_with_value="Fvfe",
        long_options_with_value=frozenset(
            {"--field-separator", "--assign", "--file", "--source"}
        ),
        script_options=frozenset({"-f", "--file", "-e", "--source"}),
    ),
    "jq": _OptionSyntax(
        short_options_with_value="f",
        long_options_with_value=frozenset({"--from-file", "--indent"}),
        script_options=frozenset({"-f", "--from-file"}),
    ),
    "cut": _OptionSyntax(
        short_options_with_value="dfcb",
        long_options_with_value=frozenset(
            {"--delimiter", "--fields", "--characters", "--bytes"}
        ),
    ),
    "sort": _OptionSyntax(
        short_options_with_value="ktoST",
        long_options_with_value=frozenset(
            {"--key", "--field-separator", "--output", "--buffer-size"}
        ),
    ),
}
_NO_OPTIONS_WITH_VALUE = _OptionSyntax()


def parse_arguments(program_name: str, arguments: tuple[str, ...]) -> ParsedArguments:
    """Split a program's arguments into options with their values and plain arguments, by the program's option syntax.

    A short option cluster such as `-fsSL` gives one option per letter. Words after `--` are plain.
    """
    syntax = _SYNTAX_OF_PROGRAM.get(program_name, _NO_OPTIONS_WITH_VALUE)
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
    syntax = _SYNTAX_OF_PROGRAM.get(program_name, _NO_OPTIONS_WITH_VALUE)
    takes_script_argument = bool(syntax.script_options) and not parsed.has_option(
        *syntax.script_options
    )
    return (
        parsed.plain_arguments[1:] if takes_script_argument else parsed.plain_arguments
    )


def _read_short_option_cluster(
    word: str,
    following: str | None,
    syntax: _OptionSyntax,
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
