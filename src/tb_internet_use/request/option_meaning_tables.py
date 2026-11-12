"""Define what the options of each program with a request row mean for its request, which `program_options` reads.

`docs/behavior-tables.md` shows them for review.
"""

from dataclasses import dataclass


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


# Option meanings of the programs with a request row in the program catalog, by the name `normalized_program_name` gives.
# A program without a row sends no request only with --help or --version, and its other options change nothing.
OPTION_MEANINGS_OF_PROGRAM = {
    "curl": OptionMeanings(
        no_request_options=frozenset({"--version"}),
        quiet_error_options=frozenset({"-s", "--silent"}),
        error_showing_options=frozenset({"-S", "--show-error"}),
    ),
    "wget": OptionMeanings(
        no_request_options=frozenset(), quiet_error_options=frozenset({"-q"})
    ),
    "pip": OptionMeanings(
        no_request_options=frozenset({"--help", "--version"}),
        offline_options=frozenset({"--no-index"}),
        quiet_progress_options=frozenset({"-q", "--quiet"}),
        index_options=frozenset({"-i", "--index-url", "--extra-index-url"}),
        package_file_options=frozenset({"-r", "-e"}),
    ),
    "uv": OptionMeanings(
        no_request_options=frozenset({"--help"}),
        quiet_progress_options=frozenset({"-q", "--quiet"}),
        index_options=frozenset({"--index-url", "--extra-index-url"}),
        package_file_options=frozenset({"-e"}),
    ),
    "npm": OptionMeanings(
        no_request_options=frozenset(),
        offline_options=frozenset({"--offline", "--prefer-offline"}),
        quiet_progress_options=frozenset({"--quiet"}),
        quiet_error_options=frozenset({"--silent"}),
    ),
    "pnpm": OptionMeanings(
        no_request_options=frozenset(), offline_options=frozenset({"--offline"})
    ),
    "bun": OptionMeanings(no_request_options=frozenset()),
    "npx": OptionMeanings(
        no_request_options=frozenset({"--version"}),
        offline_options=frozenset({"--no-install"}),
    ),
    "apt": OptionMeanings(
        no_request_options=frozenset(), quiet_progress_options=frozenset({"-q"})
    ),
    "apt-get": OptionMeanings(
        no_request_options=frozenset({"--help"}),
        quiet_progress_options=frozenset({"-q"}),
    ),
    "git": OptionMeanings(
        no_request_options=frozenset(),
        quiet_progress_options=frozenset({"-q", "--quiet"}),
    ),
    "nc": OptionMeanings(no_request_options=frozenset()),
}
