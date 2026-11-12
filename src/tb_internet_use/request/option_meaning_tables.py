"""Define what the options of each program with a request row mean for its request, which `program_options` reads.

`docs/behavior-tables.md` shows them for review.
"""

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class OptionMeanings:
    """Meanings of a program's options, used to read the facts about its request."""

    # Options that make the run send no request, e.g. --help and --version.
    no_request_options: frozenset[str] = frozenset({"--help", "--version"})
    # Options that keep the run off the network or make it prefer local copies.
    offline_options: frozenset[str] = frozenset()
    # Options that hide progress lines.
    quiet_progress_options: frozenset[str] = frozenset()
    # Options that hide error lines and progress lines.
    quiet_error_options: frozenset[str] = frozenset()
    # Options that show error lines again after a quiet error option, e.g. curl's -S after -s.
    error_showing_options: frozenset[str] = frozenset()
    # Options whose value names a package index, e.g. `--index-url`.
    index_options: frozenset[str] = frozenset()
    # Options that name packages in a file or a local project, e.g. -r of `pip install -r reqs.txt`.
    package_file_options: frozenset[str] = frozenset()


_PIP_OPTION_MEANINGS = OptionMeanings(
    no_request_options=frozenset({"-h", "--help", "-V", "--version"}),
    offline_options=frozenset({"--no-index"}),
    quiet_progress_options=frozenset({"-q", "--quiet"}),
    index_options=frozenset({"-i", "--index-url", "--extra-index-url"}),
    package_file_options=frozenset(
        {"-r", "--requirement", "-e", "--editable", "-c", "--constraint"}
    ),
)
_NODE_PACKAGE_MANAGER_OPTION_MEANINGS = OptionMeanings(
    offline_options=frozenset({"--offline", "--prefer-offline"}),
    quiet_progress_options=frozenset({"--quiet"}),
    quiet_error_options=frozenset({"-s", "--silent"}),
    index_options=frozenset({"--registry"}),
)
_APT_OPTION_MEANINGS = OptionMeanings(
    no_request_options=frozenset({"-h", "--help", "-v", "--version"}),
    quiet_progress_options=frozenset({"-q", "--quiet"}),
)
# Option meanings of the programs with a request row in the program catalog, by the name `normalized_program_name` gives.
# A program without a row sends no request only with --help or --version, and its other options change nothing.
OPTION_MEANINGS_OF_PROGRAM = {
    "curl": OptionMeanings(
        no_request_options=frozenset({"-h", "--help", "-V", "--version"}),
        quiet_error_options=frozenset({"-s", "--silent"}),
        error_showing_options=frozenset({"-S", "--show-error"}),
    ),
    "wget": OptionMeanings(
        no_request_options=frozenset({"-h", "--help", "-V", "--version"}),
        quiet_progress_options=frozenset({"-nv", "--no-verbose"}),
        quiet_error_options=frozenset({"-q", "--quiet"}),
    ),
    "pip": _PIP_OPTION_MEANINGS,
    "uv": OptionMeanings(
        no_request_options=frozenset({"-h", "--help", "-V", "--version"}),
        offline_options=frozenset({"--offline"}),
        quiet_progress_options=frozenset({"-q", "--quiet"}),
        index_options=_PIP_OPTION_MEANINGS.index_options
        | {"--index", "--default-index"},
        package_file_options=_PIP_OPTION_MEANINGS.package_file_options,
    ),
    "npm": _NODE_PACKAGE_MANAGER_OPTION_MEANINGS,
    "pnpm": _NODE_PACKAGE_MANAGER_OPTION_MEANINGS,
    "bun": _NODE_PACKAGE_MANAGER_OPTION_MEANINGS,
    # `npx --no-install` runs only a package that is already there.
    "npx": replace(
        _NODE_PACKAGE_MANAGER_OPTION_MEANINGS,
        offline_options=_NODE_PACKAGE_MANAGER_OPTION_MEANINGS.offline_options
        | {"--no-install"},
    ),
    "apt": _APT_OPTION_MEANINGS,
    "apt-get": _APT_OPTION_MEANINGS,
    # -h is no help option, since it means --heads in `git ls-remote -h`.
    "git": OptionMeanings(quiet_progress_options=frozenset({"-q", "--quiet"})),
    "nc": OptionMeanings(no_request_options=frozenset({"-h", "-l", "--listen"})),
}
