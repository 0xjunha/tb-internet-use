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
    # Options written with one dash that are one option, not a cluster of letters, e.g. wget's -nv.
    one_dash_long_options: frozenset[str] = frozenset()
    # The words after the first plain argument belong to the code or program it names, e.g. -c in `python get.py -c cfg`.
    options_end_at_first_plain_argument: bool = False
    # Options that give the script or pattern, e.g. -e in `sed -e s/a/b/ f`. Without one of them the first plain argument is the script.
    # Empty for a program that takes no script.
    script_options: frozenset[str] = frozenset()


_PIP_SYNTAX = OptionSyntax(
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
_NODE_PACKAGE_MANAGER_SYNTAX = OptionSyntax(
    short_options_with_value="Cwp",
    long_options_with_value=_NODE_PACKAGE_MANAGER_LONG_OPTIONS_WITH_VALUE,
)
_APT_SYNTAX = OptionSyntax(
    short_options_with_value="ot",
    long_options_with_value=frozenset({"--option", "--target-release"}),
)
_GREP_SYNTAX = OptionSyntax(
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
_HEAD_OR_TAIL_SYNTAX = OptionSyntax(
    short_options_with_value="nc",
    long_options_with_value=frozenset({"--lines", "--bytes"}),
)
_TYPESCRIPT_RUNNER_SYNTAX = OptionSyntax(
    short_options_with_value="e",
    long_options_with_value=frozenset({"--eval"}),
    options_end_at_first_plain_argument=True,
)
# Syntax of the programs whose options decide a file, a script, a target or code, by the name `normalized_program_name` gives.
# A program without one has no option with a value.
OPTION_SYNTAX_OF_PROGRAM = {
    "curl": OptionSyntax(
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
    "wget": OptionSyntax(
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
    "uv": OptionSyntax(
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
    "bun": OptionSyntax(
        short_options_with_value="Cwpe",
        long_options_with_value=_NODE_PACKAGE_MANAGER_LONG_OPTIONS_WITH_VALUE
        | {"--eval"},
    ),
    "deno": OptionSyntax(
        short_options_with_value="e", long_options_with_value=frozenset({"--eval"})
    ),
    "apt": _APT_SYNTAX,
    "apt-get": _APT_SYNTAX,
    "git": OptionSyntax(
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
    "rsync": OptionSyntax(
        short_options_with_value="eT",
        long_options_with_value=frozenset({"--exclude", "--include"}),
    ),
    "ping": OptionSyntax(short_options_with_value="ciWws"),
    "nc": OptionSyntax(short_options_with_value="pwsiq"),
    # The word after dig's -q or -x is the name to look up, so it stays a plain argument, e.g. a.org in `dig -q a.org`.
    "dig": OptionSyntax(short_options_with_value="tcpfbky"),
    "host": OptionSyntax(short_options_with_value="tcNRWm"),
    "gh": OptionSyntax(
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
    "conda": OptionSyntax(
        short_options_with_value="ncp",
        long_options_with_value=frozenset({"--name", "--channel", "--prefix"}),
    ),
    "huggingface-cli": OptionSyntax(
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
    "python": OptionSyntax(
        short_options_with_value="cmWX", options_end_at_first_plain_argument=True
    ),
    # node writes -p -e as `-pe 'code'`, whose value is the code.
    "node": OptionSyntax(
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
    "rg": OptionSyntax(
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
    "sed": OptionSyntax(
        short_options_with_value="efl",
        long_options_with_value=frozenset({"--expression", "--file"}),
        script_options=frozenset({"-e", "--expression", "-f", "--file"}),
    ),
    "awk": OptionSyntax(
        short_options_with_value="Fvfe",
        long_options_with_value=frozenset(
            {"--field-separator", "--assign", "--file", "--source"}
        ),
        script_options=frozenset({"-f", "--file", "-e", "--source"}),
    ),
    "jq": OptionSyntax(
        short_options_with_value="f",
        long_options_with_value=frozenset({"--from-file", "--indent"}),
        script_options=frozenset({"-f", "--from-file"}),
    ),
    "cut": OptionSyntax(
        short_options_with_value="dfcb",
        long_options_with_value=frozenset(
            {"--delimiter", "--fields", "--characters", "--bytes"}
        ),
    ),
    "sort": OptionSyntax(
        short_options_with_value="ktoST",
        long_options_with_value=frozenset(
            {"--key", "--field-separator", "--output", "--buffer-size"}
        ),
    ),
}
