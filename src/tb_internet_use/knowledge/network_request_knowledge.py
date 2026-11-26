"""Answer the questions of `extract_network_requests` about which programs and code calls fetch, which of their words are targets and where the content goes, from the program request catalog and the code call catalog, counting every use of a row and every input without one.

A blank cell is unknown only in `content_route` of the program request catalog and in `target_kind` of the code call catalog. A blank `module_name` of the code call catalog says that the call is not written through a module, e.g. `urlopen`. Every other fact cell of a row of its kind says what it means in a word, e.g. `none` or `no_request`, and a blank there fails the load, so that `NetworkRequestKnowledge` never reads a missing fact as a default.
"""

import functools
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from tb_internet_use.expanded_tool_call.model import (
    CodeLanguage,
    ProgramInvocation,
    ProgramOption,
)
from tb_internet_use.knowledge.catalog import (
    Catalog,
    KnowledgeRowKey,
    KnowledgeUses,
    load_catalog,
)
from tb_internet_use.network_request.model import (
    CODE_CALL_EFFECTS_WITH_TARGET,
    CodeCallEffect,
    CodeCallLabel,
    FetchingProgramLabel,
    NetworkRequestTargetKind,
    NonFetchingProgramLabel,
    ProgramContentRoute,
    ProgramNetworkRequestLabel,
    ProgramOptionEffect,
    TargetArguments,
    TargetNotation,
    TargetWithoutTargetArguments,
    UnknownCodeCallLabel,
    UnknownNetworkRequestTargetKind,
    UnknownProgramContentRoute,
    UnknownProgramNetworkRequestLabel,
    UnknownProgramOptionEffect,
)

NETWORK_REQUEST_CATALOGS_DIR = Path(__file__).parent / "catalogs" / "network_request"
PROGRAM_NETWORK_REQUESTS_CSV = "program_network_requests.csv"
CODE_CALLS_CSV = "code_calls.csv"
# The subcommand cell under which `may_program_fetch` counts a program name, since it answers from all the rows of the name and not from one.
ANY_SUBCOMMAND = "any subcommand"
_CODE_CALL_KEY_COLUMNS = ("code_language", "call_name")
_KEY_COLUMNS = ("program_name", "subcommand", "option_name", "option_value")
# The cells of a program row past its keys, which an option row leaves blank.
_PROGRAM_FACT_COLUMNS = (
    "fetches",
    "target_arguments",
    "target_kind",
    "target_notation",
    "target_without_target_arguments",
    "content_route",
)
# The values of `fetches`.
_YES = "yes"
_NO = "no"
_ONLY_WHAT_IS_MISSING = "only_what_is_missing"


class NetworkRequestKnowledge:
    """Outside knowledge of `extract_network_requests`, made for one trial and passed to it as `knowledge`, which it asks one question per method.

    An answer is a value or an `Unknown…` type of the step's model, never a default.
    `uses` counts every catalog row that answered and every input without one.
    The loaded catalogs are cached per process, so making one per trial is cheap.
    """

    def __init__(self, *, catalogs_dir: Path = NETWORK_REQUEST_CATALOGS_DIR) -> None:
        self.uses = KnowledgeUses()
        self._catalogs = _load_network_request_catalogs(catalogs_dir)

    def program_network_request_label(
        self, program_invocation: ProgramInvocation
    ) -> ProgramNetworkRequestLabel | UnknownProgramNetworkRequestLabel:
        """Answer whether a program and subcommand fetch, which arguments name what kind of target and where the content goes, or `UnknownProgramNetworkRequestLabel` for one without a row.

        Only the row whose program name and subcommand words are those of the invocation answers, e.g. `(pip, install)` for `pip install x`, since the subcommand was read once by `expand_tool_calls`.
        One lookup counts the row or the input `(program_name, subcommand, "", "")`.
        """
        row = self._catalogs.program_network_requests.lookup(
            _program_row_key_of(program_invocation), self.uses
        )
        if row is None:
            return UnknownProgramNetworkRequestLabel()
        assert not isinstance(row, ProgramOptionEffect)
        return row

    def program_option_effect(
        self, program_invocation: ProgramInvocation, program_option: ProgramOption
    ) -> ProgramOptionEffect | UnknownProgramOptionEffect:
        """Answer how one option of a program changes its requests, or `UnknownProgramOptionEffect` for an option without a row.

        The rows are tried in this order, and the first that the catalog has answers.

        1. The row of the subcommand of the invocation and the value of the option, e.g. `-` for `curl -o -`.
        2. The row with a blank subcommand, for every subcommand, and the value of the option.
        3. The row of the subcommand of the invocation with a blank value, for every value.
        4. The row with a blank subcommand and a blank value.

        One lookup counts that row, or when none fits the narrowest key, i.e. the subcommand and the value of the option as asked, e.g. `(curl, "", -X, TRACE)` for `curl -X TRACE`.
        An option that takes no value is asked with a blank value.
        """
        program_name, subcommand, _, _ = _program_row_key_of(program_invocation)
        option_value = program_option.value or ""
        candidate_row_keys = [
            (program_name, row_subcommand, program_option.name, row_option_value)
            for row_option_value in dict.fromkeys((option_value, ""))
            for row_subcommand in dict.fromkeys((subcommand, ""))
        ]
        catalogs = self._catalogs
        row_key = next(
            (
                key
                for key in candidate_row_keys
                if key in catalogs.program_network_request_row_keys
            ),
            candidate_row_keys[0],
        )
        row = catalogs.program_network_requests.lookup(row_key, self.uses)
        if row is None:
            return UnknownProgramOptionEffect()
        assert isinstance(row, ProgramOptionEffect)
        return row

    def may_program_fetch(
        self, program_name: str
    ) -> bool | UnknownProgramNetworkRequestLabel:
        """Answer whether any row of a program name fetches, for a program that code runs, whose subcommand nobody read, or `UnknownProgramNetworkRequestLabel` for a name without a program row.

        `program_name` is the first word that code passes to run, without its folder, e.g. `pip`.
        A row that fetches only what is missing counts as fetching.
        `NetworkRequestKnowledge` counts one use, or one unknown input, under the key `(program_name, "any subcommand", "", "")`, apart from the counts of `program_network_request_label`.
        """
        fetches = self._catalogs.fetches_by_program_name.get(program_name)
        row_key = (program_name, ANY_SUBCOMMAND, "", "")
        lookup_key = (PROGRAM_NETWORK_REQUESTS_CSV, row_key)
        if fetches is None:
            self.uses.unknown_input_counts[lookup_key] += 1
            return UnknownProgramNetworkRequestLabel()
        self.uses.row_use_counts[lookup_key] += 1
        return fetches

    def has_code_call_row(self, code_language: CodeLanguage, call_name: str) -> bool:
        """Tell whether a call name of a code language has a row, without counting, for the judgment rule that picks the name a dotted call is asked under.

        Only `code_call_label` counts, so a call is counted once under the name it is asked about.
        """
        return (code_language, call_name) in self._catalogs.code_call_row_keys

    def code_call_label(
        self, code_language: CodeLanguage, call_name: str
    ) -> CodeCallLabel | UnknownCodeCallLabel:
        """Answer whether a call in code sends a request, holds the target of one, runs a program or does none of these, and how its target is written, or `UnknownCodeCallLabel` for a name without a row.

        Only the row of exactly that name answers, e.g. `requests.get`, and the shorter name of a dotted call is picked before by `extract_code_network_requests`.
        One lookup counts the row or the input `(code_language, call_name)`.
        """
        row = self._catalogs.code_calls.lookup(
            (code_language.value, call_name), self.uses
        )
        return UnknownCodeCallLabel() if row is None else row


def _program_row_key_of(program_invocation: ProgramInvocation) -> KnowledgeRowKey:
    """Give the key of the program row of an invocation, with its subcommand words split by one space."""
    return (
        program_invocation.program_name,
        " ".join(program_invocation.subcommand_words),
        "",
        "",
    )


@functools.cache
def _load_network_request_catalogs(catalogs_dir: Path) -> _NetworkRequestCatalogs:
    """Load the program request CSV and the code call CSV of a folder once per process, raising ValueError on a row that `extract_network_requests` cannot use."""
    program_network_requests = load_catalog(
        catalogs_dir / PROGRAM_NETWORK_REQUESTS_CSV,
        key_columns=_KEY_COLUMNS,
        row_from_columns=_program_network_request_row_from_columns,
    )
    # These lookups sort the rows when the file loads and answer no question of a step, so their counts are dropped.
    unused_uses = KnowledgeUses()
    fetches_by_program_name: dict[str, bool] = {}
    fetching_program_rows: set[tuple[str, str]] = set()
    for program_name, subcommand, option_name, _ in program_network_requests.row_keys:
        if option_name:
            continue
        row = program_network_requests.lookup(
            (program_name, subcommand, "", ""), unused_uses
        )
        is_fetching = isinstance(row, FetchingProgramLabel)
        fetches_by_program_name[program_name] = (
            fetches_by_program_name.get(program_name, False) or is_fetching
        )
        if is_fetching:
            fetching_program_rows.add((program_name, subcommand))
    for program_name, subcommand, option_name, _ in program_network_requests.row_keys:
        if option_name:
            _check_option_row_has_fetching_program(
                program_name, subcommand, fetching_program_rows
            )
    code_calls = load_catalog(
        catalogs_dir / CODE_CALLS_CSV,
        key_columns=_CODE_CALL_KEY_COLUMNS,
        row_from_columns=_code_call_label_from_columns,
    )
    return _NetworkRequestCatalogs(
        program_network_requests,
        frozenset(program_network_requests.row_keys),
        fetches_by_program_name,
        code_calls,
        frozenset(
            (CodeLanguage(code_language), call_name)
            for code_language, call_name in code_calls.row_keys
        ),
    )


def _check_option_row_has_fetching_program(
    program_name: str, subcommand: str, fetching_program_rows: set[tuple[str, str]]
) -> None:
    """Raise ValueError on an option row whose program, or program and subcommand when the row names one, has no row that fetches, since `NetworkRequestKnowledge` is asked about options only for such programs."""
    if subcommand:
        if (program_name, subcommand) not in fetching_program_rows:
            raise ValueError(
                f"the option row of {(program_name, subcommand)} in {PROGRAM_NETWORK_REQUESTS_CSV} has no program row that fetches"
            )
    elif not any(name == program_name for name, _ in fetching_program_rows):
        raise ValueError(
            f"the option row of {program_name} in {PROGRAM_NETWORK_REQUESTS_CSV} has no program row that fetches"
        )


type _ProgramNetworkRequestRow = ProgramNetworkRequestLabel | ProgramOptionEffect


@dataclass(frozen=True, slots=True)
class _NetworkRequestCatalogs:
    """Loaded catalogs of `extract_network_requests`, shared by every `NetworkRequestKnowledge` of a process."""

    program_network_requests: Catalog[_ProgramNetworkRequestRow]
    # The keys of all rows, so `NetworkRequestKnowledge` can pick the row of an option before its one lookup.
    program_network_request_row_keys: frozenset[KnowledgeRowKey]
    # Whether any program row of each name fetches, so `may_program_fetch` answers without a lookup per row.
    fetches_by_program_name: Mapping[str, bool]
    code_calls: Catalog[CodeCallLabel]
    # The code language and call name of every row, so the judgment rule can try names without a lookup.
    code_call_row_keys: frozenset[tuple[CodeLanguage, str]]


def _program_network_request_row_from_columns(
    columns: Mapping[str, str],
) -> _ProgramNetworkRequestRow:
    """Read one row of `program_network_requests.csv`, a program row when `option_name` is blank and else an option row, raising ValueError on a cell that its kind of row does not allow."""
    _check_review_columns(columns)
    if not columns["program_name"]:
        raise ValueError("program_name is empty")
    if " ".join(columns["subcommand"].split()) != columns["subcommand"]:
        raise ValueError(
            f"subcommand {columns['subcommand']!r} is not words split by one space"
        )
    if columns["option_name"]:
        return _program_option_effect_from_columns(columns)
    return _program_network_request_label_from_columns(columns)


def _program_network_request_label_from_columns(
    columns: Mapping[str, str],
) -> ProgramNetworkRequestLabel:
    """Read a program row, in which `fetches` `no` leaves every other fact cell blank and else only `content_route` may be blank."""
    _check_blank(columns, ("option_value", "option_effect"), row_kind="a program row")
    fetches = columns["fetches"]
    if fetches == _NO:
        _check_blank(columns, _PROGRAM_FACT_COLUMNS[1:], row_kind="a row of `no`")
        return NonFetchingProgramLabel()
    if fetches not in (_YES, _ONLY_WHAT_IS_MISSING):
        raise ValueError(f"fetches is {fetches!r}, not yes, no or only_what_is_missing")
    content_route = columns["content_route"]
    return FetchingProgramLabel(
        fetches_only_what_is_missing=fetches == _ONLY_WHAT_IS_MISSING,
        target_arguments=TargetArguments(columns["target_arguments"]),
        target_kind=NetworkRequestTargetKind(columns["target_kind"]),
        target_notation=TargetNotation(columns["target_notation"]),
        target_without_target_arguments=TargetWithoutTargetArguments(
            columns["target_without_target_arguments"]
        ),
        content_route=UnknownProgramContentRoute()
        if content_route == ""
        else ProgramContentRoute(content_route),
    )


def _program_option_effect_from_columns(
    columns: Mapping[str, str],
) -> ProgramOptionEffect:
    """Read an option row, which leaves the program fact cells blank and names one `ProgramOptionEffect`."""
    _check_blank(columns, _PROGRAM_FACT_COLUMNS, row_kind="an option row")
    return ProgramOptionEffect(columns["option_effect"])


def _code_call_label_from_columns(columns: Mapping[str, str]) -> CodeCallLabel:
    """Read one row of `code_calls.csv`, in which a call that sends a request or holds the target of one names its target notation and may leave its target kind blank, and any other call leaves both blank."""
    _check_review_columns(columns)
    code_language = CodeLanguage(columns["code_language"])
    call_name = columns["call_name"]
    if not call_name:
        raise ValueError("call_name is empty")
    module_name = _module_name_from_columns(columns, code_language)
    effect = CodeCallEffect(columns["effect"])
    if effect not in CODE_CALL_EFFECTS_WITH_TARGET:
        _check_blank(
            columns,
            ("target_notation", "target_kind"),
            row_kind="a row that neither sends a request nor holds its target",
        )
        return CodeCallLabel(call_name, effect, None, None, module_name)
    target_kind = columns["target_kind"]
    return CodeCallLabel(
        call_name=call_name,
        effect=effect,
        target_notation=TargetNotation(columns["target_notation"]),
        target_kind=UnknownNetworkRequestTargetKind()
        if target_kind == ""
        else NetworkRequestTargetKind(target_kind),
        module_name=module_name,
    )


def _module_name_from_columns(
    columns: Mapping[str, str], code_language: CodeLanguage
) -> str | None:
    """Read `module_name` of a row, None when it is blank, raising ValueError on a module that is not the first dotted part of `call_name`, e.g. `os` for `subprocess.run`, or on a module of a JavaScript row.

    A JavaScript row leaves it blank, since `parse_code` reads no import of JavaScript.
    """
    module_name = columns["module_name"]
    if not module_name:
        return None
    if code_language != CodeLanguage.PYTHON:
        raise ValueError(
            f"module_name {module_name!r} is filled in a {code_language} row"
        )
    call_name_parts = columns["call_name"].split(".")
    if len(call_name_parts) < 2 or call_name_parts[0] != module_name:
        raise ValueError(
            f"module_name {module_name!r} is not the first dotted part of {columns['call_name']!r}"
        )
    return module_name


def _check_blank(
    columns: Mapping[str, str], blank_columns: tuple[str, ...], *, row_kind: str
) -> None:
    """Raise ValueError on a filled cell in a column that this kind of row leaves blank."""
    filled_columns = [column for column in blank_columns if columns[column]]
    if filled_columns:
        raise ValueError(f"{filled_columns} are filled in {row_kind}")


def _check_review_columns(columns: Mapping[str, str]) -> None:
    """Raise ValueError on a row that does not say what it was checked against, or whose `reviewed` is none of empty, `yes` and `agents`."""
    if not columns["checked_against"]:
        raise ValueError("checked_against is empty")
    if columns["reviewed"] not in ("", "yes", "agents"):
        raise ValueError(
            f"reviewed is {columns['reviewed']!r}, not empty, yes or agents"
        )
