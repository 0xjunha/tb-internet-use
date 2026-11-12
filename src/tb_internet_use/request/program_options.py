"""Read what a command's options say about its request, e.g. a help run, an offline run, hidden lines or a changed exit code meaning.

One option name means different things in different programs, e.g. `-i` is pip's index URL but curl's header switch, so each program has its own rules.
"""

from dataclasses import dataclass, replace

from tb_internet_use.network.model import PrintingProgram
from tb_internet_use.program.arguments import ParsedArguments
from tb_internet_use.program.model import ExitZeroMeans, RequestRule


@dataclass(frozen=True, slots=True)
class OptionFacts:
    """Facts that the options of one command give about its request, read by `extract_candidate_requests` beside the matched catalog row."""

    # The catalog row's request rule after the options that change it, e.g. REQUEST_SUCCEEDED as exit_zero_means for `curl -f`.
    rule: RequestRule
    # An option makes the run send no request, e.g. `--help`, `--version` or `nc -l`, which listens.
    sends_no_request: bool
    has_offline_option: bool
    # Package index URLs that options name, e.g. the value of `pip --index-url`.
    index_urls: tuple[str, ...]
    # An option names packages in a file or a local project, e.g. `pip install -r reqs.txt` or `pip install -e .`.
    names_packages_in_files: bool
    prints_status_code: bool
    quiet_progress_lines: bool
    quiet_error_lines: bool


@dataclass(frozen=True, slots=True)
class _OptionRules:
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


_PIP_RULES = _OptionRules(
    no_request_options=frozenset({"-h", "--help", "-V", "--version"}),
    offline_options=frozenset({"--no-index"}),
    quiet_progress_options=frozenset({"-q", "--quiet"}),
    index_options=frozenset({"-i", "--index-url", "--extra-index-url"}),
    package_file_options=frozenset(
        {"-r", "--requirement", "-e", "--editable", "-c", "--constraint"}
    ),
)
_NODE_PACKAGE_MANAGER_RULES = _OptionRules(
    offline_options=frozenset({"--offline", "--prefer-offline"}),
    quiet_progress_options=frozenset({"--quiet"}),
    quiet_error_options=frozenset({"-s", "--silent"}),
    index_options=frozenset({"--registry"}),
)
_APT_RULES = _OptionRules(
    no_request_options=frozenset({"-h", "--help", "-v", "--version"}),
    quiet_progress_options=frozenset({"-q", "--quiet"}),
)
# Rules of the programs with a request row in the program catalog, by the name `normalized_program_name` gives.
# A program without rules sends no request only with --help or --version, and its other options change nothing.
_RULES_OF_PROGRAM = {
    "curl": _OptionRules(
        no_request_options=frozenset({"-h", "--help", "-V", "--version"}),
        quiet_error_options=frozenset({"-s", "--silent"}),
        error_showing_options=frozenset({"-S", "--show-error"}),
    ),
    "wget": _OptionRules(
        no_request_options=frozenset({"-h", "--help", "-V", "--version"}),
        quiet_progress_options=frozenset({"-nv", "--no-verbose"}),
        quiet_error_options=frozenset({"-q", "--quiet"}),
    ),
    "pip": _PIP_RULES,
    "uv": _OptionRules(
        no_request_options=frozenset({"-h", "--help", "-V", "--version"}),
        offline_options=frozenset({"--offline"}),
        quiet_progress_options=frozenset({"-q", "--quiet"}),
        index_options=_PIP_RULES.index_options | {"--index", "--default-index"},
        package_file_options=_PIP_RULES.package_file_options,
    ),
    "npm": _NODE_PACKAGE_MANAGER_RULES,
    "pnpm": _NODE_PACKAGE_MANAGER_RULES,
    "bun": _NODE_PACKAGE_MANAGER_RULES,
    # `npx --no-install` runs only a package that is already there.
    "npx": replace(
        _NODE_PACKAGE_MANAGER_RULES,
        offline_options=_NODE_PACKAGE_MANAGER_RULES.offline_options | {"--no-install"},
    ),
    "apt": _APT_RULES,
    "apt-get": _APT_RULES,
    # -h is no help option, since it means --heads in `git ls-remote -h`.
    "git": _OptionRules(quiet_progress_options=frozenset({"-q", "--quiet"})),
    "nc": _OptionRules(no_request_options=frozenset({"-h", "-l", "--listen"})),
}
_NO_RULES = _OptionRules()


def option_facts(
    program_name: str, parsed: ParsedArguments, rule: RequestRule
) -> OptionFacts:
    """Read the facts that a command's options give about its request, by the rules of its program."""
    rules = _RULES_OF_PROGRAM.get(program_name, _NO_RULES)
    hides_errors = parsed.has_option(*rules.quiet_error_options)
    return OptionFacts(
        rule=_rule_after_options(program_name, parsed, rule),
        sends_no_request=parsed.has_option(*rules.no_request_options),
        has_offline_option=parsed.has_option(*rules.offline_options),
        index_urls=parsed.option_values(*rules.index_options),
        names_packages_in_files=parsed.has_option(*rules.package_file_options),
        prints_status_code=program_name == "curl"
        and any(
            "%{http_code}" in value or "%{response_code}" in value
            for value in parsed.option_values("-w", "--write-out")
        ),
        quiet_progress_lines=hides_errors
        or parsed.has_option(*rules.quiet_progress_options),
        quiet_error_lines=hides_errors
        and not parsed.has_option(*rules.error_showing_options),
    )


def _rule_after_options(
    program_name: str, parsed: ParsedArguments, rule: RequestRule
) -> RequestRule:
    """Change a request rule by the curl or wget options that change what a run prints and what its exit code 0 means."""
    if program_name == "curl":
        fails_on_http_error = parsed.has_option("-f", "--fail", "--fail-with-body")
        asks_for_no_content = parsed.has_option("-I", "--head") or any(
            method.upper() == "HEAD"
            for method in parsed.option_values("-X", "--request")
        )
        writes_file = parsed.has_option(
            "-O", "--remote-name", "--remote-name-all"
        ) or any(value != "-" for value in parsed.option_values("-o", "--output"))
        prints_headers = parsed.has_option(
            "-i", "--include", "-I", "--head", "-v", "--verbose"
        ) or "-" in parsed.option_values("-D", "--dump-header")
        return replace(
            rule,
            printing_programs=rule.printing_programs
            | ({PrintingProgram.HTTP_HEADERS} if prints_headers else set())
            | ({PrintingProgram.HTTP_FAILURE} if fails_on_http_error else set()),
            exit_zero_means=ExitZeroMeans.REQUEST_SUCCEEDED
            if fails_on_http_error
            else rule.exit_zero_means,
            asks_for_no_content=rule.asks_for_no_content or asks_for_no_content,
            prints_response_body=not writes_file and not asks_for_no_content,
        )
    if program_name == "wget":
        prints_headers = parsed.has_option("-S", "--server-response", "-d", "--debug")
        return replace(
            rule,
            printing_programs=rule.printing_programs
            | ({PrintingProgram.HTTP_HEADERS} if prints_headers else set()),
            asks_for_no_content=rule.asks_for_no_content
            or parsed.has_option("--spider"),
            prints_response_body="-" in parsed.option_values("-O", "--output-document"),
        )
    return rule
