"""List the behavior tables in code with the basis of their rows, and write them as one page for review.

Behavior tables describe how programs, code and servers behave and which naming conventions they follow, e.g. which curl options take a value, which output lines show a download or which extension a Python file has.
Each lives in a `*_tables.py` module beside the code that reads it. This module lists them with the rules that stay in logic modules, so that `docs/behavior-tables.md` shows them all in one place.
"""

import inspect
import re
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum, StrEnum
from pathlib import Path
from types import ModuleType

from tb_internet_use.callrun import (
    code_program_tables,
    file_reads,
    output_routes,
    poll_links,
    written_files,
)
from tb_internet_use.network import hosts, package_names
from tb_internet_use.observation import extract, line_pattern_tables
from tb_internet_use.observation.line_pattern_tables import (
    LinePattern,
    LinePatternTable,
)
from tb_internet_use.program import option_syntax_tables
from tb_internet_use.request import (
    code_request_tables,
    code_requests,
    option_meaning_tables,
    program_options,
    target_tables,
    targets,
)
from tb_internet_use.shell import program_tables, programs

# The page that `behavior_tables_markdown` writes, in the docs folder of the repo.
BEHAVIOR_TABLES_DOC = Path(__file__).parents[2] / "docs" / "behavior-tables.md"


class BehaviorTableBasis(StrEnum):
    """Basis of a behavior table's rows, shown on the page so that a reviewer knows what to check them against."""

    TRAJECTORIES = "trajectories"
    MANUALS = "manuals"
    STANDARDS = "standards"


# What each basis means, shown on the page.
_MEANING_OF_BASIS = {
    BehaviorTableBasis.TRAJECTORIES: "The rows are chosen from what the trajectories hold, e.g. the wrappers that commands use or the lines that programs print.",
    BehaviorTableBasis.MANUALS: "The values follow the programs' documentation, e.g. which curl options take a value.",
    BehaviorTableBasis.STANDARDS: "The rows follow a standard or a common convention, e.g. DNS record types or the `.py` extension.",
}


@dataclass(frozen=True, slots=True)
class BehaviorTable:
    """Entry of `BEHAVIOR_TABLES`, naming one table constant and the basis of its rows."""

    module: ModuleType
    # The constant's name in its module, whose comment above it says what the table holds.
    name: str
    bases: tuple[BehaviorTableBasis, ...]
    # Whether the first matching row decides, so that the order of the rows matters.
    is_ordered: bool = False


@dataclass(frozen=True, slots=True)
class RuleInCode:
    """Entry of `RULES_IN_CODE`, naming a rule about programs, output, hosts or package names that stays in a logic module.

    Such a rule needs code a table cannot hold, e.g. a condition on an option's value in `curl -o -`, or it is a pattern of a format, e.g. a URL.
    """

    module: ModuleType
    # A constant or function of the module, or a method as `Class.method`, whose comment or docstring says what it holds.
    name: str


# Every behavior table, in pipeline order.
BEHAVIOR_TABLES = (
    BehaviorTable(
        program_tables,
        "WRAPPERS",
        (BehaviorTableBasis.TRAJECTORIES, BehaviorTableBasis.MANUALS),
    ),
    BehaviorTable(
        program_tables,
        "PROGRAMS_GIVING_RUN_TIME_ARGUMENTS",
        (BehaviorTableBasis.MANUALS,),
    ),
    BehaviorTable(
        program_tables,
        "PYTHON_OPTIONS_WITH_VALUE_BEFORE_MODULE",
        (BehaviorTableBasis.MANUALS,),
    ),
    BehaviorTable(
        program_tables, "VERSIONED_PROGRAMS", (BehaviorTableBasis.STANDARDS,)
    ),
    BehaviorTable(program_tables, "SHELL_PROGRAMS", (BehaviorTableBasis.MANUALS,)),
    BehaviorTable(
        program_tables, "EXIT_CODE_SHELL_OPTION_NAMES", (BehaviorTableBasis.MANUALS,)
    ),
    BehaviorTable(
        program_tables, "SHELL_LONG_OPTIONS_WITH_VALUE", (BehaviorTableBasis.MANUALS,)
    ),
    BehaviorTable(
        option_syntax_tables,
        "OPTION_SYNTAX_OF_PROGRAM",
        (BehaviorTableBasis.TRAJECTORIES, BehaviorTableBasis.MANUALS),
    ),
    BehaviorTable(
        code_program_tables,
        "CODE_PROGRAMS",
        (BehaviorTableBasis.TRAJECTORIES, BehaviorTableBasis.MANUALS),
    ),
    BehaviorTable(
        code_program_tables,
        "LANGUAGE_OF_FILE_EXTENSION",
        (BehaviorTableBasis.STANDARDS,),
    ),
    BehaviorTable(
        code_program_tables, "SHELL_FILE_EXTENSIONS", (BehaviorTableBasis.STANDARDS,)
    ),
    BehaviorTable(
        option_meaning_tables,
        "OPTION_MEANINGS_OF_PROGRAM",
        (BehaviorTableBasis.TRAJECTORIES, BehaviorTableBasis.MANUALS),
    ),
    BehaviorTable(
        target_tables, "SCHEMELESS_URL_PROGRAMS", (BehaviorTableBasis.MANUALS,)
    ),
    BehaviorTable(
        target_tables,
        "PROGRAMS_WITH_HOST_AS_FIRST_TARGET",
        (BehaviorTableBasis.MANUALS,),
    ),
    BehaviorTable(target_tables, "DNS_LOOKUP_PROGRAMS", (BehaviorTableBasis.MANUALS,)),
    BehaviorTable(
        target_tables, "DNS_RECORD_TYPES_AND_CLASSES", (BehaviorTableBasis.STANDARDS,)
    ),
    BehaviorTable(
        target_tables,
        "PROGRAMS_WITH_HOST_AS_EVERY_TARGET",
        (BehaviorTableBasis.MANUALS,),
    ),
    BehaviorTable(
        code_request_tables,
        "NETWORK_CALL_OF_LANGUAGE",
        (BehaviorTableBasis.TRAJECTORIES, BehaviorTableBasis.MANUALS),
    ),
    BehaviorTable(
        code_request_tables, "PROGRAM_RUN_BY_CODE", (BehaviorTableBasis.MANUALS,)
    ),
    BehaviorTable(
        code_request_tables, "HOST_NAMED_BY_CODE", (BehaviorTableBasis.TRAJECTORIES,)
    ),
    BehaviorTable(
        code_request_tables, "SCHEMA_HOST_NAMES", (BehaviorTableBasis.TRAJECTORIES,)
    ),
    BehaviorTable(
        line_pattern_tables,
        "PROGRAM_OUTPUT_LINE_PATTERNS",
        (BehaviorTableBasis.TRAJECTORIES,),
        is_ordered=True,
    ),
    BehaviorTable(
        line_pattern_tables,
        "WEB_TOOL_RESULT_LINE_PATTERNS",
        (BehaviorTableBasis.TRAJECTORIES,),
        is_ordered=True,
    ),
)
# Rules about programs, output, hosts and package names that stay in logic modules, in pipeline order.
# Shell syntax and parser rules are left out, since they hold no fact about a program.
RULES_IN_CODE = (
    RuleInCode(programs, "_VERSION_SUFFIX"),
    RuleInCode(programs, "_find_exec_words"),
    RuleInCode(programs, "_python_module_words"),
    RuleInCode(programs, "_shell_invocation"),
    RuleInCode(written_files, "WrittenFiles.record_command"),
    RuleInCode(output_routes, "tee_file_destinations"),
    RuleInCode(file_reads, "_command_reads"),
    RuleInCode(poll_links, "_KEY_PRESS_CHARACTERS"),
    RuleInCode(poll_links, "_ENDED_STATUSES"),
    RuleInCode(program_options, "_rule_after_options"),
    RuleInCode(targets, "_SCP_LIKE_ADDRESS"),
    RuleInCode(targets, "_SCHEMELESS_HOST"),
    RuleInCode(targets, "_PATH_OR_URL"),
    RuleInCode(targets, "_remote_host_names"),
    RuleInCode(code_requests, "_URL"),
    RuleInCode(code_requests, "_is_schema_name"),
    RuleInCode(hosts, "_TEMPLATE_CHARACTER"),
    RuleInCode(hosts, "_LOCAL_NAME"),
    RuleInCode(hosts, "_RESERVED_NAME"),
    RuleInCode(package_names, "_ARCHIVE_FILE"),
    RuleInCode(package_names, "_AFTER_NAME"),
    RuleInCode(package_names, "_DASHED_VERSION_AT_END"),
    RuleInCode(package_names, "_SEPARATORS"),
    RuleInCode(extract, "_ANSI_CSI_SEQUENCE"),
)


def behavior_tables_markdown() -> str:
    """Write the page that lists every behavior table with its rows, then the rules that stay in logic modules."""
    lines = [
        "# Behavior tables",
        "",
        "Behavior tables describe how programs, code and servers behave and which naming conventions they follow, as the rules of stages 6 to 10 read them, e.g. which curl options take a value, which output lines show a download or which extension a Python file has.",
        "Each lives in a `*_tables.py` module beside the code that reads it.",
        "Mappings that need no judgment live in CSV catalogs instead, e.g. the [program catalog](../src/tb_internet_use/program/catalogs/program_catalog.csv).",
        "",
        "This page is written by `scripts/build_behavior_tables_doc.py` from `src/tb_internet_use/behavior_tables.py`, so edit the tables and run it again.",
        "",
        "| Basis | Meaning |",
        "|---|---|",
        *(f"| {basis} | {meaning} |" for basis, meaning in _MEANING_OF_BASIS.items()),
        "",
        "## Summary",
        "",
        *_markdown_table(
            ["Table", "Module", "Basis", "Rows", "What it holds"],
            [
                [
                    f"[`{table.name}`](#{table.name.lower()})",
                    f"`{_module_path(table.module)}`",
                    ", ".join(table.bases),
                    _row_count(getattr(table.module, table.name)),
                    _first_sentence(_comment_above(table.module, table.name)),
                ]
                for table in BEHAVIOR_TABLES
            ],
        ),
        "",
        "## Tables",
    ]
    for table in BEHAVIOR_TABLES:
        lines += ["", *_table_section(table)]
    lines += [
        "",
        "## Rules inside code",
        "",
        "These rules about programs, output, hosts and package names stay in logic modules, since they need code that a table cannot hold, e.g. a condition on an option's value, or they are a pattern of a format, e.g. a URL.",
        "",
        *_markdown_table(
            ["Rule", "Module", "What it holds"],
            [
                [
                    f"`{rule.name}`",
                    f"`{_module_path(rule.module)}`",
                    _description(rule.module, rule.name),
                ]
                for rule in RULES_IN_CODE
            ],
        ),
    ]
    return "\n".join(lines) + "\n"


def _markdown_table(header: list[str], rows: list[list[str]]) -> list[str]:
    """Write a markdown table, escaping the pipes in its cells, e.g. in a regex."""
    return [
        _markdown_row(header),
        "|" + "---|" * len(header),
        *(_markdown_row(row) for row in rows),
    ]


def _markdown_row(cells: list[str]) -> str:
    """Write one markdown table row, escaping the pipes in its cells."""
    return "| " + " | ".join(cell.replace("|", r"\|") for cell in cells) + " |"


def _module_path(module: ModuleType) -> str:
    """Give a module's file path within the package, e.g. `shell/program_tables.py`."""
    return module.__name__.removeprefix("tb_internet_use.").replace(".", "/") + ".py"


def _row_count(value: object) -> str:
    """Count a table's rows, i.e. its items, keys or line patterns, or nothing for one regex."""
    if isinstance(value, LinePatternTable):
        return str(len(value.rows))
    if isinstance(value, (dict, frozenset)):
        return str(len(value))
    return ""


def _first_sentence(text: str) -> str:
    """Take the first sentence of a comment, e.g. the summary line of a table."""
    return re.split(r"(?<=\.)(?<!e\.g\.)(?<!i\.e\.) ", text, maxsplit=1)[0]


def _table_section(table: BehaviorTable) -> list[str]:
    """Write one table's section, with its module, basis, comment and rows."""
    path = _module_path(table.module)
    lines = [
        f"### `{table.name}`",
        "",
        f"Module: [`{path}`](../src/tb_internet_use/{path}). Basis: {', '.join(table.bases)}.",
        "",
        _comment_above(table.module, table.name),
    ]
    if table.is_ordered:
        lines += [
            "",
            "The first matching row decides, so the order of the rows matters.",
        ]
    return [*lines, "", *_rows_markdown(getattr(table.module, table.name))]


def _rows_markdown(value: object) -> list[str]:
    """Write a table's rows, as a markdown table for keyed or ordered rows, a list for a set and a code block for a regex."""
    if isinstance(value, LinePatternTable):
        return _markdown_table(
            ["Row (1-based)", *(f.name for f in fields(LinePattern))],
            [
                [str(number), *(_cell(getattr(row, f.name)) for f in fields(row))]
                for number, row in enumerate(value.rows, 1)
            ],
        )
    if isinstance(value, dict):
        first_value = next(iter(value.values()))
        if is_dataclass(first_value):
            names = [f.name for f in fields(first_value)]
            return _markdown_table(
                ["Key", *names],
                [
                    [_cell(key), *(_cell(getattr(row, name)) for name in names)]
                    for key, row in value.items()
                ],
            )
        return _markdown_table(
            ["Key", "Value"], [[_cell(key), _cell(row)] for key, row in value.items()]
        )
    if isinstance(value, frozenset):
        return [_cell(value)]
    if isinstance(value, re.Pattern):
        return ["```text", value.pattern, "```"]
    raise TypeError(f"no markdown for a table of type {type(value).__name__}")


def _cell(value: object) -> str:
    """Write one value as markdown, e.g. a set as sorted code spans and an enum as its value."""
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, re.Pattern):
        return _code_span(value.pattern)
    if isinstance(value, frozenset):
        return ", ".join(sorted(_cell(item) for item in value))
    if isinstance(value, str):
        return _code_span(value)
    return str(value)


def _code_span(text: str) -> str:
    """Wrap a text in a code span, with more backticks around it than any run of backticks inside it."""
    longest_run = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest_run + 1)
    padding = " " if longest_run else ""
    return f"{fence}{padding}{text}{padding}{fence}"


def _description(module: ModuleType, name: str) -> str:
    """Take what a rule holds, from the first line of a function's docstring or the comment above a constant."""
    value: object = module
    for part in name.split("."):
        value = getattr(value, part)
    if inspect.isfunction(value):
        return (inspect.getdoc(value) or "").split("\n", 1)[0]
    return _comment_above(module, name)


def _comment_above(module: ModuleType, name: str) -> str:
    """Take the comment lines right above a module-level assignment, joined into one text, e.g. the comment above `WRAPPERS = {`."""
    lines = inspect.getsource(module).splitlines()
    assignment = re.compile(rf"{re.escape(name)}(?:: [^=]+)? = ")
    index = next((i for i, line in enumerate(lines) if assignment.match(line)), None)
    if index is None:
        raise ValueError(f"no assignment of {name} in {module.__name__}")
    comment_lines: list[str] = []
    while index > 0 and lines[index - 1].startswith("#"):
        index -= 1
        comment_lines.insert(0, lines[index].removeprefix("#").strip())
    if not comment_lines:
        raise ValueError(f"no comment above {name} in {module.__name__}")
    return " ".join(comment_lines)
