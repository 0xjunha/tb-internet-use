"""Find the request rule of a command's program, passing through programs that run the next program, such as npx, to the program they run."""

from dataclasses import dataclass

from tb_internet_use.network.model import PrintingProgram
from tb_internet_use.program.arguments import ParsedArguments
from tb_internet_use.program.catalog_rows import matched_catalog_rows
from tb_internet_use.program.model import RequestRule


@dataclass(frozen=True, slots=True)
class MatchedRequestRule:
    """Request rule that a command's program matched, with the arguments that the request's targets and option facts come from."""

    program_name: str
    rule: RequestRule
    subcommand_words: tuple[str, ...]
    parsed_arguments: ParsedArguments
    # Plain arguments after the subcommand, e.g. requests in `pip install requests`, or the program that npx runs, e.g. tsc in `npx tsc`.
    target_words: tuple[str, ...]
    # Printing programs of the rows of the programs that run this one, e.g. npm for playwright in `npx playwright install`.
    printing_programs_of_programs_running_it: frozenset[PrintingProgram]


def matched_request_rule(words: tuple[str, ...]) -> MatchedRequestRule | None:
    """Find the request rule that a program's words match, from the last matched row with a rule.

    A program such as npx gives way to the request of the program it runs, e.g. playwright in `npx playwright install`.
    When that program has no rule, the request of npx names it as its target, e.g. tsc in `npx tsc`.
    """
    rows = matched_catalog_rows(words)
    rules = [
        (position, m.row.request_rule)
        for position, m in enumerate(rows)
        if m.row.request_rule is not None
    ]
    if not rules:
        return None
    position, rule = rules[-1]
    matched = rows[position]
    subcommand_words = matched.row.subcommand_words
    target_words = (
        matched.next_program_words[:1]
        if matched.next_program_words
        else matched.parsed_arguments.plain_arguments[len(subcommand_words) :]
    )
    return MatchedRequestRule(
        program_name=matched.program_name,
        rule=rule,
        subcommand_words=subcommand_words,
        parsed_arguments=matched.parsed_arguments,
        target_words=target_words,
        printing_programs_of_programs_running_it=frozenset(
            program
            for _, running_rule in rules[:-1]
            for program in running_rule.printing_programs
        ),
    )
