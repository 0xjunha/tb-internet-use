"""Find the program catalog rows that a program's words match, following programs that run the next program, such as npx.

A program such as npx or `uv run` runs the program named after it, e.g. tsx in `npx tsx get.ts`, so its own row is not the whole story.
"""

from dataclasses import dataclass

from tb_internet_use.program.arguments import ParsedArguments, parse_arguments
from tb_internet_use.program.catalog_loader import program_catalog
from tb_internet_use.program.model import ProgramCatalogRow
from tb_internet_use.shell.programs import program_words_from


@dataclass(frozen=True, slots=True)
class MatchedCatalogRow:
    """Catalog row that a program's words match, with its own arguments, read when finding candidate requests and the code a command runs."""

    program_name: str
    row: ProgramCatalogRow
    # The arguments before the next program it runs, e.g. -y in `npx -y tsc --version`, or else all of them.
    parsed_arguments: ParsedArguments
    # The next program it runs and that program's arguments, as written, e.g. ("playwright@1.49", "install") for `npx playwright@1.49 install`.
    # Empty when it runs none.
    next_program_words: tuple[str, ...]


def matched_catalog_rows(words: tuple[str, ...]) -> tuple[MatchedCatalogRow, ...]:
    """List the catalog rows that a program's words match, the row of a program that runs the next program first, e.g. npx then playwright install."""
    matched = matched_catalog_row(words)
    if matched is None:
        return ()
    return (
        matched,
        *matched_catalog_rows(program_words_from(matched.next_program_words)),
    )


def last_program_words(words: tuple[str, ...]) -> tuple[str, ...]:
    """Follow programs that run the next program to the words of the last one, e.g. tsx get.ts for `npx tsx get.ts` or python get.py for `uv run python get.py`."""
    matched = matched_catalog_row(words)
    if matched is None or not matched.next_program_words:
        return words
    return last_program_words(program_words_from(matched.next_program_words))


def matched_catalog_row(words: tuple[str, ...]) -> MatchedCatalogRow | None:
    """Find the catalog row of a program whose subcommand starts its plain arguments, the longest subcommand first.

    The words start with the program as `normalized_program_name` gives it, as `program_words` returns them.
    """
    if not words:
        return None
    program_name, arguments = words[0], words[1:]
    parsed = parse_arguments(program_name, arguments)
    for row in program_catalog().get(program_name, ()):
        subcommand_length = len(row.subcommand_words)
        if parsed.plain_arguments[:subcommand_length] != row.subcommand_words:
            continue
        if (
            not row.runs_next_program
            or len(parsed.plain_arguments) == subcommand_length
        ):
            return MatchedCatalogRow(program_name, row, parsed, ())
        next_program_index = parsed.plain_argument_indexes[subcommand_length]
        return MatchedCatalogRow(
            program_name,
            row,
            parse_arguments(program_name, arguments[:next_program_index]),
            arguments[next_program_index:],
        )
    return None
