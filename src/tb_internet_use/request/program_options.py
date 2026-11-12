"""Read what a command's options say about its request, e.g. a help run, an offline run, hidden lines or a changed exit code meaning.

One option name means different things in different programs, e.g. `-i` is pip's index URL but curl's header switch, so each program has its own option meanings.
"""

from dataclasses import dataclass, replace

from tb_internet_use.network.model import PrintingProgram
from tb_internet_use.program.arguments import ParsedArguments
from tb_internet_use.program.model import ExitZeroMeans, RequestRule
from tb_internet_use.request.option_meaning_tables import (
    OPTION_MEANINGS_OF_PROGRAM,
    OptionMeanings,
)

# The option meanings of a program without a row in `OPTION_MEANINGS_OF_PROGRAM`.
_NO_OPTION_MEANINGS = OptionMeanings()


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


def option_facts(
    program_name: str, parsed: ParsedArguments, rule: RequestRule
) -> OptionFacts:
    """Read the facts that a command's options give about its request, by the option meanings of its program."""
    meanings = OPTION_MEANINGS_OF_PROGRAM.get(program_name, _NO_OPTION_MEANINGS)
    hides_errors = parsed.has_option(*meanings.quiet_error_options)
    return OptionFacts(
        rule=_rule_after_options(program_name, parsed, rule),
        sends_no_request=parsed.has_option(*meanings.no_request_options),
        has_offline_option=parsed.has_option(*meanings.offline_options),
        index_urls=parsed.option_values(*meanings.index_options),
        names_packages_in_files=parsed.has_option(*meanings.package_file_options),
        prints_status_code=program_name == "curl"
        and any(
            "%{http_code}" in value or "%{response_code}" in value
            for value in parsed.option_values("-w", "--write-out")
        ),
        quiet_progress_lines=hides_errors
        or parsed.has_option(*meanings.quiet_progress_options),
        quiet_error_lines=hides_errors
        and not parsed.has_option(*meanings.error_showing_options),
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
