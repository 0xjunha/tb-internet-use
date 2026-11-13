"""Define the option syntax of each program, which `arguments` reads to tell options and their values from plain arguments.

`docs/behavior-tables.md` shows it for review.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OptionSyntax:
    """Option syntax of one program, used to tell its options and their values from its plain arguments."""

    # Letters of short options that take a value, either the rest of the word or the next word, e.g. o in `-o out` or `-oout`.
    short_options_with_value: str = ""
    # Long options that take the next word as their value unless written as `--name=value`, e.g. `--output out`.
    long_options_with_value: frozenset[str] = frozenset()
    # Options written with one dash that are one option, not a cluster of letters, e.g. node's -pe.
    one_dash_long_options: frozenset[str] = frozenset()
    # The words after the first plain argument belong to the code or program it names, e.g. -c in `python get.py -c cfg`.
    options_end_at_first_plain_argument: bool = False
    # Options that give the script or pattern, e.g. -e in `sed -e s/a/b/ f`. Without one of them the first plain argument is the script.
    # Empty for a program that takes no script.
    script_options: frozenset[str] = frozenset()


_HEAD_OR_TAIL_SYNTAX = OptionSyntax(short_options_with_value="nc")
# Syntax of the programs whose options decide a file, a script, a target or code, by the name `normalized_program_name` gives.
# A program without one has no option with a value.
OPTION_SYNTAX_OF_PROGRAM = {
    "curl": OptionSyntax(
        short_options_with_value="oDrmcbFTAuwXHd",
        long_options_with_value=frozenset(
            [
                "--output",
                "--data",
                "--data-raw",
                "--data-binary",
                "--data-urlencode",
                "--header",
                "--request",
                "--write-out",
                "--user",
                "--max-time",
                "--connect-timeout",
                "--retry",
                "--retry-delay",
                "--upload-file",
                "--range",
                "--url-query",
            ]
        ),
    ),
    "wget": OptionSyntax(short_options_with_value="O"),
    "pip": OptionSyntax(
        short_options_with_value="reitfd",
        long_options_with_value=frozenset(
            [
                "--index-url",
                "--extra-index-url",
                "--target",
                "--find-links",
                "--python-version",
                "--platform",
                "--implementation",
                "--only-binary",
                "--no-binary",
                "--progress-bar",
                "--dest",
                "--python",
                "--report",
                "--timeout",
            ]
        ),
    ),
    "uv": OptionSyntax(
        short_options_with_value="e",
        long_options_with_value=frozenset(
            {"--index-url", "--extra-index-url", "--python", "--with"}
        ),
    ),
    "npm": OptionSyntax(long_options_with_value=frozenset({"--prefix", "--package"})),
    "pnpm": OptionSyntax(
        short_options_with_value="p", long_options_with_value=frozenset({"--dir"})
    ),
    "npx": OptionSyntax(
        short_options_with_value="p",
        long_options_with_value=frozenset({"--prefix", "--package"}),
    ),
    "bun": OptionSyntax(
        short_options_with_value="pe", long_options_with_value=frozenset({"--eval"})
    ),
    "apt-get": OptionSyntax(short_options_with_value="o"),
    "git": OptionSyntax(
        short_options_with_value="Cboc",
        long_options_with_value=frozenset({"--depth", "--branch", "--filter"}),
    ),
    "rsync": OptionSyntax(long_options_with_value=frozenset({"--exclude"})),
    "ping": OptionSyntax(short_options_with_value="ciW"),
    "nc": OptionSyntax(short_options_with_value="wq"),
    "gh": OptionSyntax(long_options_with_value=frozenset({"--jq"})),
    "conda": OptionSyntax(short_options_with_value="nc"),
    "huggingface-cli": OptionSyntax(
        long_options_with_value=frozenset({"--local-dir", "--revision"})
    ),
    "python": OptionSyntax(
        short_options_with_value="cmWX", options_end_at_first_plain_argument=True
    ),
    # node writes -p -e as `-pe 'code'`, whose value is the code.
    "node": OptionSyntax(
        short_options_with_value="epr",
        long_options_with_value=frozenset({"-pe"}),
        one_dash_long_options=frozenset({"-pe"}),
        options_end_at_first_plain_argument=True,
    ),
    "tsx": OptionSyntax(
        short_options_with_value="e",
        long_options_with_value=frozenset({"--eval"}),
        options_end_at_first_plain_argument=True,
    ),
    "head": _HEAD_OR_TAIL_SYNTAX,
    "tail": _HEAD_OR_TAIL_SYNTAX,
    "grep": OptionSyntax(
        short_options_with_value="efmABC",
        long_options_with_value=frozenset({"--include", "--exclude", "--exclude-dir"}),
        script_options=frozenset({"-e", "--regexp", "-f", "--file"}),
    ),
    "egrep": OptionSyntax(script_options=frozenset({"-e", "--regexp", "-f", "--file"})),
    "rg": OptionSyntax(
        short_options_with_value="egmABCr",
        long_options_with_value=frozenset(
            {"--glob", "--type", "--max-count", "--context"}
        ),
        script_options=frozenset({"-e", "--regexp", "-f", "--file"}),
    ),
    "sed": OptionSyntax(
        short_options_with_value="e",
        script_options=frozenset({"-e", "--expression", "-f", "--file"}),
    ),
    "awk": OptionSyntax(
        short_options_with_value="Fvf",
        script_options=frozenset({"-f", "--file", "-e", "--source"}),
    ),
    "jq": OptionSyntax(
        short_options_with_value="f",
        script_options=frozenset({"-f", "--from-file"}),
    ),
    "cut": OptionSyntax(short_options_with_value="dfc"),
    "sort": OptionSyntax(short_options_with_value="ktoST"),
}
