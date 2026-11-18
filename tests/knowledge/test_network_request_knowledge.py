"""Tests for knowledge/network_request_knowledge.py, with made-up catalogs, and of the rows of the real catalog that came from the old program tables."""

import csv
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from tb_internet_use.expanded_tool_call.model import (
    CodeLanguage,
    ProgramInvocation,
    ProgramOption,
)
from tb_internet_use.interpret.callrun.model import CodeLanguage as OldCodeLanguage
from tb_internet_use.interpret.request.code_request_tables import (
    NETWORK_CALL_OF_LANGUAGE,
    PROGRAM_RUN_BY_CODE,
)
from tb_internet_use.knowledge.catalog import KnowledgeLookupKey, KnowledgeUses
from tb_internet_use.knowledge.expanded_tool_call_knowledge import (
    EXPANDED_TOOL_CALL_CATALOGS_DIR,
    PROGRAM_BEHAVIORS_CSV,
)
from tb_internet_use.knowledge.network_request_knowledge import (
    ANY_SUBCOMMAND,
    CODE_CALLS_CSV,
    NETWORK_REQUEST_CATALOGS_DIR,
    PROGRAM_NETWORK_REQUESTS_CSV,
    NetworkRequestKnowledge,
)
from tb_internet_use.network_request.model import (
    CodeCallEffect,
    CodeCallLabel,
    FetchingProgramLabel,
    NetworkRequestTargetKind,
    NonFetchingProgramLabel,
    ProgramContentRoute,
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

_COLUMNS = [
    "program_name",
    "subcommand",
    "option_name",
    "option_value",
    "fetches",
    "target_arguments",
    "target_kind",
    "target_notation",
    "target_without_target_arguments",
    "content_route",
    "option_effect",
    "checked_against",
    "reviewed",
    "note",
]
# A program row of `prog install` whose every fact cell differs from the first value of its type, so that a door that drops or mixes up a column fails.
_PROGRAM_ROW_CELLS = {
    **dict.fromkeys(_COLUMNS, ""),
    "program_name": "prog",
    "subcommand": "install",
    "fetches": "yes",
    "target_arguments": "first",
    "target_kind": "host",
    "target_notation": "rsync_address",
    "target_without_target_arguments": "named_in_file",
    "content_route": "own_file",
    "checked_against": "a manual",
}
_FETCHING_PROGRAM_LABEL = FetchingProgramLabel(
    fetches_only_what_is_missing=False,
    target_arguments=TargetArguments.FIRST,
    target_kind=NetworkRequestTargetKind.HOST,
    target_notation=TargetNotation.RSYNC_ADDRESS,
    target_without_target_arguments=TargetWithoutTargetArguments.NAMED_IN_FILE,
    content_route=ProgramContentRoute.OWN_FILE,
)
_NON_FETCHING_ROW_CELLS = {
    **dict.fromkeys(_COLUMNS, ""),
    "program_name": "cat",
    "fetches": "no",
    "checked_against": "a manual",
    "reviewed": "yes",
}
# An option row of every subcommand and value of prog.
_OPTION_ROW_CELLS = {
    **dict.fromkeys(_COLUMNS, ""),
    "program_name": "prog",
    "option_name": "-o",
    "option_effect": "sends_content_to_stdout",
    "checked_against": "a manual",
}
_CODE_CALL_COLUMNS = [
    "code_language",
    "call_name",
    "effect",
    "target_notation",
    "target_kind",
    "checked_against",
    "reviewed",
    "note",
]
# A row of a call that sends a request whose every cell differs from the first value of its type, so that a door that drops or mixes up a column fails.
_SENDING_CODE_CALL_ROW_CELLS = {
    **dict.fromkeys(_CODE_CALL_COLUMNS, ""),
    "code_language": "javascript",
    "call_name": "mylib.connect",
    "effect": "sends_network_request",
    "target_notation": "host_and_port_tuple",
    "target_kind": "host",
    "checked_against": "a manual",
}
_RUNNING_CODE_CALL_ROW_CELLS = {
    **dict.fromkeys(_CODE_CALL_COLUMNS, ""),
    "code_language": "python",
    "call_name": "os.system",
    "effect": "runs_program",
    "checked_against": "a manual",
}
# (rows of the code call catalog, a part of the error message) of catalogs that fail the load.
_CODE_CALL_CATALOGS_THAT_CANNOT_LOAD = [
    ([{**_SENDING_CODE_CALL_ROW_CELLS, "target_notation": ""}], "'' is not a valid"),
    (
        [{**_RUNNING_CODE_CALL_ROW_CELLS, "target_notation": "url"}],
        "are filled in a row that sends no request",
    ),
    (
        [{**_RUNNING_CODE_CALL_ROW_CELLS, "target_kind": "url"}],
        "are filled in a row that sends no request",
    ),
    (
        [{**_SENDING_CODE_CALL_ROW_CELLS, "effect": "fetches"}],
        "'fetches' is not a valid",
    ),
    (
        [{**_SENDING_CODE_CALL_ROW_CELLS, "code_language": "ruby"}],
        "'ruby' is not a valid",
    ),
    ([{**_SENDING_CODE_CALL_ROW_CELLS, "call_name": ""}], "call_name is empty"),
    (
        [{**_SENDING_CODE_CALL_ROW_CELLS, "checked_against": ""}],
        "checked_against is empty",
    ),
    ([{**_SENDING_CODE_CALL_ROW_CELLS, "reviewed": "no"}], "not empty or yes"),
    (
        [_SENDING_CODE_CALL_ROW_CELLS, _SENDING_CODE_CALL_ROW_CELLS],
        "two rows have the key",
    ),
]
# Calls of the old code request tables that build a client and send nothing, or whose first argument is a method and not the URL, so the real catalog has no row for them.
_OLD_CALLS_WITHOUT_ROW = [
    "requests.Session",
    "httpx.Client",
    "httpx.AsyncClient",
    "aiohttp.ClientSession",
    "requests.request",
    "httpx.stream",
]
# Fact cells of a fetching program row in which a blank fails the load.
_PROGRAM_COLUMNS_THAT_CANNOT_BE_BLANK = [
    "fetches",
    "target_arguments",
    "target_kind",
    "target_notation",
    "target_without_target_arguments",
    "checked_against",
]
# (rows, a part of the error message) of catalogs that fail the load.
_CATALOGS_THAT_CANNOT_LOAD = [
    (
        [{**_PROGRAM_ROW_CELLS, "fetches": "maybe"}],
        "not yes, no or only_what_is_missing",
    ),
    ([{**_PROGRAM_ROW_CELLS, "target_kind": "package"}], "'package' is not a valid"),
    ([{**_PROGRAM_ROW_CELLS, "content_route": "unknown"}], "'unknown' is not a valid"),
    ([{**_PROGRAM_ROW_CELLS, "option_effect": "none"}], "are filled in a program row"),
    ([{**_PROGRAM_ROW_CELLS, "option_value": "-"}], "are filled in a program row"),
    (
        [{**_NON_FETCHING_ROW_CELLS, "content_route": "stdout"}],
        "are filled in a row of `no`",
    ),
    (
        [_PROGRAM_ROW_CELLS, {**_OPTION_ROW_CELLS, "content_route": "stdout"}],
        "are filled in an option row",
    ),
    (
        [_PROGRAM_ROW_CELLS, {**_OPTION_ROW_CELLS, "option_effect": ""}],
        "'' is not a valid",
    ),
    ([{**_PROGRAM_ROW_CELLS, "reviewed": "no"}], "not empty or yes"),
    ([{**_PROGRAM_ROW_CELLS, "program_name": ""}], "program_name is empty"),
    (
        [{**_PROGRAM_ROW_CELLS, "subcommand": "pip  install"}],
        "not words split by one space",
    ),
    ([_PROGRAM_ROW_CELLS, _PROGRAM_ROW_CELLS], "two rows have the key"),
    # An option row whose program has no row, whose program does not fetch, or whose subcommand has no row.
    ([_OPTION_ROW_CELLS], "has no program row that fetches"),
    (
        [_NON_FETCHING_ROW_CELLS, {**_OPTION_ROW_CELLS, "program_name": "cat"}],
        "has no program row that fetches",
    ),
    (
        [_PROGRAM_ROW_CELLS, {**_OPTION_ROW_CELLS, "subcommand": "run"}],
        "has no program row that fetches",
    ),
]
# (option of `prog install`, the rows of `-o` beside the program row, as (subcommand, value, effect), the row key that answers)
_OPTION_ROWS_IN_THE_ORDER_THEY_ARE_TRIED = [
    (
        ProgramOption("-o", "-"),
        [
            ("install", "-", "sends_content_to_stdout"),
            ("", "-", "none"),
            ("install", "", "none"),
            ("", "", "none"),
        ],
        ("prog", "install", "-o", "-"),
    ),
    (
        ProgramOption("-o", "-"),
        [
            ("", "-", "sends_content_to_stdout"),
            ("install", "", "none"),
            ("", "", "none"),
        ],
        ("prog", "", "-o", "-"),
    ),
    (
        ProgramOption("-o", "-"),
        [("install", "", "sends_content_to_stdout"), ("", "", "none")],
        ("prog", "install", "-o", ""),
    ),
    (
        ProgramOption("-o", "-"),
        [("", "", "sends_content_to_stdout"), ("run", "-", "none")],
        ("prog", "", "-o", ""),
    ),
    # An option that takes no value is asked with a blank value.
    (
        ProgramOption("-o", None),
        [("install", "", "sends_content_to_stdout"), ("install", "x", "none")],
        ("prog", "install", "-o", ""),
    ),
]
# (program name, subcommand, option name, option value, effect) of the old option tables, as the real catalog must hold them.
_OPTION_EFFECTS_OF_THE_OLD_TABLES = [
    ("curl", "", "--version", "", ProgramOptionEffect.SENDS_NO_REQUEST),
    ("pip", "", "--help", "", ProgramOptionEffect.SENDS_NO_REQUEST),
    ("pip", "", "--version", "", ProgramOptionEffect.SENDS_NO_REQUEST),
    ("uv", "", "--help", "", ProgramOptionEffect.SENDS_NO_REQUEST),
    ("npx", "", "--version", "", ProgramOptionEffect.SENDS_NO_REQUEST),
    ("apt-get", "", "--help", "", ProgramOptionEffect.SENDS_NO_REQUEST),
    ("pip", "", "--no-index", "", ProgramOptionEffect.SENDS_NO_REQUEST),
    ("npm", "", "--offline", "", ProgramOptionEffect.SENDS_NO_REQUEST),
    (
        "npm",
        "",
        "--prefer-offline",
        "",
        ProgramOptionEffect.FETCHES_ONLY_WHAT_IS_MISSING,
    ),
    ("pnpm", "", "--offline", "", ProgramOptionEffect.SENDS_NO_REQUEST),
    ("npx", "", "--no-install", "", ProgramOptionEffect.SENDS_NO_REQUEST),
    ("pip", "", "-i", "", ProgramOptionEffect.NAMES_HOST_IN_VALUE),
    ("pip", "", "--index-url", "", ProgramOptionEffect.NAMES_HOST_IN_VALUE),
    ("pip", "", "--extra-index-url", "", ProgramOptionEffect.NAMES_HOST_IN_VALUE),
    ("uv", "", "--index-url", "", ProgramOptionEffect.NAMES_HOST_IN_VALUE),
    ("uv", "", "--extra-index-url", "", ProgramOptionEffect.NAMES_HOST_IN_VALUE),
    ("pip", "", "-r", "", ProgramOptionEffect.NAMES_TARGETS_IN_FILE),
    ("pip", "", "-e", "", ProgramOptionEffect.NAMES_TARGET_IN_VALUE),
    ("uv", "", "-e", "", ProgramOptionEffect.NAMES_TARGET_IN_VALUE),
    ("curl", "", "-I", "", ProgramOptionEffect.ASKS_FOR_NO_CONTENT),
    ("curl", "", "--head", "", ProgramOptionEffect.ASKS_FOR_NO_CONTENT),
    ("curl", "", "-X", "HEAD", ProgramOptionEffect.ASKS_FOR_NO_CONTENT),
    ("curl", "", "--request", "HEAD", ProgramOptionEffect.ASKS_FOR_NO_CONTENT),
    ("curl", "", "-o", "-", ProgramOptionEffect.SENDS_CONTENT_TO_STDOUT),
    ("curl", "", "--output", "-", ProgramOptionEffect.SENDS_CONTENT_TO_STDOUT),
    ("curl", "", "-o", "", ProgramOptionEffect.NONE),
    ("curl", "", "-O", "", ProgramOptionEffect.NONE),
    ("wget", "", "--spider", "", ProgramOptionEffect.ASKS_FOR_NO_CONTENT),
    ("wget", "", "-O", "-", ProgramOptionEffect.SENDS_CONTENT_TO_STDOUT),
    ("wget", "", "--output-document", "-", ProgramOptionEffect.SENDS_CONTENT_TO_STDOUT),
    ("wget", "", "-O", "", ProgramOptionEffect.NONE),
]
# (program name, subcommand words, full label) of the real catalog for the rows that the decision document names, so that a change of any fact cell of these rows fails.
_FETCHING_PROGRAM_LABELS_OF_NAMED_ROWS = [
    (
        "curl",
        (),
        FetchingProgramLabel(
            fetches_only_what_is_missing=False,
            target_arguments=TargetArguments.ALL,
            target_kind=NetworkRequestTargetKind.URL,
            target_notation=TargetNotation.URL_OR_SCHEMELESS_URL,
            target_without_target_arguments=TargetWithoutTargetArguments.NO_REQUEST,
            content_route=ProgramContentRoute.STDOUT,
        ),
    ),
    (
        "wget",
        (),
        FetchingProgramLabel(
            fetches_only_what_is_missing=False,
            target_arguments=TargetArguments.ALL,
            target_kind=NetworkRequestTargetKind.URL,
            target_notation=TargetNotation.URL,
            target_without_target_arguments=TargetWithoutTargetArguments.NO_REQUEST,
            content_route=ProgramContentRoute.OWN_FILE,
        ),
    ),
    (
        "pip",
        ("install",),
        FetchingProgramLabel(
            fetches_only_what_is_missing=False,
            target_arguments=TargetArguments.ALL,
            target_kind=NetworkRequestTargetKind.PACKAGE_NAME,
            target_notation=TargetNotation.PIP_REQUIREMENT,
            target_without_target_arguments=TargetWithoutTargetArguments.NO_TARGET,
            content_route=ProgramContentRoute.OWN_FILE,
        ),
    ),
    (
        "git",
        ("clone",),
        FetchingProgramLabel(
            fetches_only_what_is_missing=False,
            target_arguments=TargetArguments.FIRST,
            target_kind=NetworkRequestTargetKind.REPOSITORY_URL,
            target_notation=TargetNotation.URL_OR_SCP_LIKE_ADDRESS,
            target_without_target_arguments=TargetWithoutTargetArguments.NO_TARGET,
            content_route=ProgramContentRoute.OWN_FILE,
        ),
    ),
    (
        "npx",
        (),
        FetchingProgramLabel(
            fetches_only_what_is_missing=True,
            target_arguments=TargetArguments.NEXT_PROGRAM,
            target_kind=NetworkRequestTargetKind.PACKAGE_NAME,
            target_notation=TargetNotation.NAME,
            target_without_target_arguments=TargetWithoutTargetArguments.NO_REQUEST,
            content_route=UnknownProgramContentRoute(),
        ),
    ),
    (
        "apt-get",
        ("update",),
        FetchingProgramLabel(
            fetches_only_what_is_missing=False,
            target_arguments=TargetArguments.NONE,
            target_kind=NetworkRequestTargetKind.PACKAGE_NAME,
            target_notation=TargetNotation.NAME,
            target_without_target_arguments=TargetWithoutTargetArguments.NO_TARGET,
            content_route=ProgramContentRoute.OWN_FILE,
        ),
    ),
    (
        "ping",
        (),
        FetchingProgramLabel(
            fetches_only_what_is_missing=False,
            target_arguments=TargetArguments.FIRST,
            target_kind=NetworkRequestTargetKind.HOST,
            target_notation=TargetNotation.HOST_NAME,
            target_without_target_arguments=TargetWithoutTargetArguments.NO_REQUEST,
            content_route=ProgramContentRoute.NO_CONTENT,
        ),
    ),
    (
        "rsync",
        (),
        FetchingProgramLabel(
            fetches_only_what_is_missing=False,
            target_arguments=TargetArguments.ALL,
            target_kind=NetworkRequestTargetKind.HOST,
            target_notation=TargetNotation.RSYNC_ADDRESS,
            target_without_target_arguments=TargetWithoutTargetArguments.NO_REQUEST,
            content_route=UnknownProgramContentRoute(),
        ),
    ),
]
# The (program, subcommand) pairs of the real program request catalog that `program_behaviors.csv` has no row for yet.
# The rows come with the program catalog of `expand_tool_calls` and the set then shrinks, so that a pair that is misspelled never hides in it.
_PAIRS_WITHOUT_PROGRAM_BEHAVIOR_ROW_YET = {
    ("agent-browser", "install"),
    ("apt", "install"),
    ("apt", "update"),
    ("apt-get", "download"),
    ("apt-get", "install"),
    ("apt-get", "source"),
    ("apt-get", "update"),
    ("bun", "add"),
    ("conda", "install"),
    ("diff", ""),
    ("dig", ""),
    ("dnf", "install"),
    ("dnf", "makecache"),
    ("echo", ""),
    ("getent", "hosts"),
    ("gh", "api"),
    ("git", "clone"),
    ("git", "fetch"),
    ("git", "ls-remote"),
    ("git", "submodule update"),
    ("go", "build"),
    ("go", "mod tidy"),
    ("go", "run"),
    ("host", ""),
    ("huggingface-cli", "download"),
    ("lake", "build"),
    ("npm", "audit"),
    ("npm", "ci"),
    ("npm", "create"),
    ("npm", "i"),
    ("npm", "install"),
    ("npm", "ping"),
    ("npm", "view"),
    ("nslookup", ""),
    ("pip", "download"),
    ("pip", "index versions"),
    ("pip", "install"),
    ("pip", "search"),
    ("pip", "wheel"),
    ("playwright", "install"),
    ("playwright", "install-deps"),
    ("pnpm", "add"),
    ("pnpm", "install"),
    ("printf", ""),
    ("sbt", ""),
    ("strings", ""),
    ("tac", ""),
    ("uv", "pip install"),
    ("uv", "venv"),
    ("xxd", ""),
}
# The old program catalog, which the program rows came from.
_OLD_PROGRAM_CATALOG_CSV = (
    Path(__file__).parents[2]
    / "src/tb_internet_use/parse/program/catalogs/program_catalog.csv"
)
_NOT_CHECKED = "not checked, from the old table"
# A manual page named as `name(section)`, e.g. `git-clone(1)` or `ping(8)`.
_MANUAL_PAGE_NAME = re.compile(r"\b[\w.+-]+\([1-9][a-z]*\)")
# A host of a documentation site, e.g. `pip.pypa.io` or `pnpm.io/cli/install`.
_DOCUMENTATION_HOST = re.compile(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b")


def _write_catalog(
    tmp_path: Path,
    rows: list[Mapping[str, str]],
    code_call_rows: Sequence[Mapping[str, str]] = (),
) -> Path:
    for file_name, columns, file_rows in (
        (PROGRAM_NETWORK_REQUESTS_CSV, _COLUMNS, rows),
        (CODE_CALLS_CSV, _CODE_CALL_COLUMNS, code_call_rows),
    ):
        with (tmp_path / file_name).open("w", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, columns)
            writer.writeheader()
            writer.writerows(file_rows)
    return tmp_path


def _knowledge(
    tmp_path: Path,
    rows: list[Mapping[str, str]],
    code_call_rows: Sequence[Mapping[str, str]] = (),
) -> NetworkRequestKnowledge:
    return NetworkRequestKnowledge(
        catalogs_dir=_write_catalog(tmp_path, rows, code_call_rows)
    )


def _invocation(
    program_name: str = "prog", subcommand_words: tuple[str, ...] = ("install",)
) -> ProgramInvocation:
    return ProgramInvocation(
        program_name=program_name,
        subcommand_words=subcommand_words,
        options=(),
        arguments=("x",),
        gets_more_arguments_at_run_time=False,
        unread_words=(),
        exits_with_exit_code_of_next_program=False,
    )


def _option_row(
    subcommand: str, option_value: str, option_effect: str
) -> dict[str, str]:
    return {
        **_OPTION_ROW_CELLS,
        "subcommand": subcommand,
        "option_value": option_value,
        "option_effect": option_effect,
    }


def _uses(*row_keys: tuple[str, ...]) -> Counter[KnowledgeLookupKey]:
    return Counter((PROGRAM_NETWORK_REQUESTS_CSV, row_key) for row_key in row_keys)


def _real_rows() -> list[dict[str, str]]:
    with (NETWORK_REQUEST_CATALOGS_DIR / PROGRAM_NETWORK_REQUESTS_CSV).open(
        newline=""
    ) as csv_file:
        return list(csv.DictReader(csv_file))


def _old_program_rows() -> list[dict[str, str]]:
    with _OLD_PROGRAM_CATALOG_CSV.open(newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def test_program_row_is_read_into_every_field_and_counted(tmp_path):
    knowledge = _knowledge(tmp_path, [_PROGRAM_ROW_CELLS])

    assert (
        knowledge.program_network_request_label(_invocation())
        == _FETCHING_PROGRAM_LABEL
    )
    assert knowledge.uses == KnowledgeUses(
        row_use_counts=_uses(("prog", "install", "", "")),
    )


def test_fetches_yes_and_only_what_is_missing_are_told_apart(tmp_path):
    knowledge = _knowledge(
        tmp_path,
        [
            _PROGRAM_ROW_CELLS,
            {
                **_PROGRAM_ROW_CELLS,
                "subcommand": "run",
                "fetches": "only_what_is_missing",
            },
        ],
    )

    install_label = knowledge.program_network_request_label(_invocation())
    run_label = knowledge.program_network_request_label(
        _invocation(subcommand_words=("run",))
    )

    assert isinstance(install_label, FetchingProgramLabel)
    assert isinstance(run_label, FetchingProgramLabel)
    assert not install_label.fetches_only_what_is_missing
    assert run_label.fetches_only_what_is_missing


def test_row_of_no_is_a_non_fetching_label_and_counted(tmp_path):
    knowledge = _knowledge(tmp_path, [_NON_FETCHING_ROW_CELLS])

    assert (
        knowledge.program_network_request_label(_invocation("cat", ()))
        == NonFetchingProgramLabel()
    )
    assert knowledge.uses.row_use_counts == _uses(("cat", "", "", ""))


def test_program_without_its_exact_row_is_unknown_and_counted_under_its_subcommand(
    tmp_path,
):
    knowledge = _knowledge(tmp_path, [_PROGRAM_ROW_CELLS])

    # The row of `prog install` answers neither prog without subcommand words nor another subcommand.
    assert (
        knowledge.program_network_request_label(_invocation(subcommand_words=()))
        == UnknownProgramNetworkRequestLabel()
    )
    assert (
        knowledge.program_network_request_label(
            _invocation(subcommand_words=("pip", "install"))
        )
        == UnknownProgramNetworkRequestLabel()
    )
    assert knowledge.uses == KnowledgeUses(
        unknown_input_counts=_uses(
            ("prog", "", "", ""), ("prog", "pip install", "", "")
        ),
    )


def test_blank_content_route_is_unknown_and_not_a_default(tmp_path):
    knowledge = _knowledge(tmp_path, [{**_PROGRAM_ROW_CELLS, "content_route": ""}])

    label = knowledge.program_network_request_label(_invocation())

    assert isinstance(label, FetchingProgramLabel)
    assert label.content_route == UnknownProgramContentRoute()


@pytest.mark.parametrize("column", _PROGRAM_COLUMNS_THAT_CANNOT_BE_BLANK)
def test_blank_fact_cell_of_a_fetching_program_row_other_than_content_route_fails_the_load(
    tmp_path, column
):
    catalogs_dir = _write_catalog(tmp_path, [{**_PROGRAM_ROW_CELLS, column: ""}])

    with pytest.raises(ValueError):
        NetworkRequestKnowledge(catalogs_dir=catalogs_dir)


@pytest.mark.parametrize(("rows", "message"), _CATALOGS_THAT_CANNOT_LOAD)
def test_catalog_that_extract_network_requests_cannot_use_fails_the_load(
    tmp_path, rows, message
):
    catalogs_dir = _write_catalog(tmp_path, rows)

    with pytest.raises(ValueError, match=message):
        NetworkRequestKnowledge(catalogs_dir=catalogs_dir)


@pytest.mark.parametrize(
    ("program_option", "option_rows", "answering_row_key"),
    _OPTION_ROWS_IN_THE_ORDER_THEY_ARE_TRIED,
)
def test_option_rows_are_tried_by_subcommand_and_value_and_the_first_one_answers_and_is_counted(
    tmp_path, program_option, option_rows, answering_row_key
):
    knowledge = _knowledge(
        tmp_path,
        [
            _PROGRAM_ROW_CELLS,
            {**_PROGRAM_ROW_CELLS, "subcommand": "run"},
            *(_option_row(*cells) for cells in option_rows),
        ],
    )

    effect = knowledge.program_option_effect(_invocation(), program_option)

    assert effect == ProgramOptionEffect.SENDS_CONTENT_TO_STDOUT
    assert knowledge.uses == KnowledgeUses(row_use_counts=_uses(answering_row_key))


def test_option_without_a_row_is_unknown_and_counted_under_its_subcommand_and_value(
    tmp_path,
):
    knowledge = _knowledge(
        tmp_path,
        [
            _PROGRAM_ROW_CELLS,
            {**_PROGRAM_ROW_CELLS, "subcommand": "run"},
            # The row of another subcommand does not answer.
            _option_row("run", "", "none"),
        ],
    )

    effect = knowledge.program_option_effect(
        _invocation(), ProgramOption("-o", "a.tgz")
    )

    assert effect == UnknownProgramOptionEffect()
    assert knowledge.uses == KnowledgeUses(
        unknown_input_counts=_uses(("prog", "install", "-o", "a.tgz")),
    )


def test_option_row_does_not_answer_for_the_program_label(tmp_path):
    knowledge = _knowledge(tmp_path, [_PROGRAM_ROW_CELLS, _option_row("", "", "none")])

    assert (
        knowledge.program_network_request_label(_invocation())
        == _FETCHING_PROGRAM_LABEL
    )
    assert (
        knowledge.program_option_effect(_invocation(), ProgramOption("-o", None))
        == ProgramOptionEffect.NONE
    )


def test_may_program_fetch_tells_yes_no_and_unknown_apart_and_counts_under_any_subcommand(
    tmp_path,
):
    knowledge = _knowledge(
        tmp_path,
        [
            # One program row of prog fetches and a later one does not, so prog may fetch.
            _PROGRAM_ROW_CELLS,
            {**_NON_FETCHING_ROW_CELLS, "program_name": "prog"},
            _NON_FETCHING_ROW_CELLS,
            _option_row("", "", "none"),
        ],
    )

    assert knowledge.may_program_fetch("prog") is True
    assert knowledge.may_program_fetch("cat") is False
    assert knowledge.may_program_fetch("mytool") == UnknownProgramNetworkRequestLabel()
    assert knowledge.uses == KnowledgeUses(
        row_use_counts=_uses(
            ("prog", ANY_SUBCOMMAND, "", ""), ("cat", ANY_SUBCOMMAND, "", "")
        ),
        unknown_input_counts=_uses(("mytool", ANY_SUBCOMMAND, "", "")),
    )


def test_may_program_fetch_counts_a_program_that_fetches_only_what_is_missing_as_fetching(
    tmp_path,
):
    knowledge = _knowledge(
        tmp_path, [{**_PROGRAM_ROW_CELLS, "fetches": "only_what_is_missing"}]
    )

    assert knowledge.may_program_fetch("prog") is True


def test_real_catalog_loads_and_holds_no_invisible_control_characters():
    NetworkRequestKnowledge()
    text = (NETWORK_REQUEST_CATALOGS_DIR / PROGRAM_NETWORK_REQUESTS_CSV).read_text()

    assert not [c for c in text if ord(c) < 32 and c != "\n"]
    assert all(row["reviewed"] == "" for row in _real_rows())


def test_every_program_row_of_the_old_catalog_has_a_row_with_the_cells_it_states():
    real_rows = {
        (row["program_name"], row["subcommand"]): row
        for row in _real_rows()
        if not row["option_name"]
    }
    broken: list[str] = []
    for old in _old_program_rows():
        key = (old["program"], old["subcommand"])
        row = real_rows.get(key)
        if row is None:
            broken.append(f"{key} has no row")
            continue
        if not old["request_kind"]:
            expected_fetches = "no"
        elif old["fetches_only_to_run_or_build"] == "yes":
            expected_fetches = "only_what_is_missing"
        else:
            expected_fetches = "yes"
        if row["fetches"] != expected_fetches:
            broken.append(
                f"{key} fetches {row['fetches']}, the old table {expected_fetches}"
            )
        # A content route that was not checked on a page is the one the old table states, or blank where it states none.
        if expected_fetches != "no" and "content_route" not in row["checked_against"]:
            expected_route = (
                "no_content"
                if old["asks_for_no_content"] == "yes"
                else "stdout"
                if old["prints_response_body"] == "yes"
                else ""
            )
            if row["content_route"] != expected_route:
                broken.append(
                    f"{key} content_route {row['content_route']!r}, the old table {expected_route!r}"
                )
    assert not broken, "\n".join(broken)


@pytest.mark.parametrize(
    ("program_name", "subcommand", "option_name", "option_value", "effect"),
    _OPTION_EFFECTS_OF_THE_OLD_TABLES,
)
def test_real_catalog_holds_the_option_effects_of_the_old_tables(
    program_name, subcommand, option_name, option_value, effect
):
    knowledge = NetworkRequestKnowledge()
    invocation = _invocation(program_name, tuple(subcommand.split()))

    answer = knowledge.program_option_effect(
        invocation, ProgramOption(option_name, option_value or None)
    )

    assert answer == effect
    assert not knowledge.uses.unknown_input_counts


@pytest.mark.parametrize(
    ("program_name", "subcommand_words", "label"),
    _FETCHING_PROGRAM_LABELS_OF_NAMED_ROWS,
)
def test_real_catalog_gives_the_full_label_of_the_rows_the_decision_document_names(
    program_name, subcommand_words, label
):
    knowledge = NetworkRequestKnowledge()

    assert (
        knowledge.program_network_request_label(
            _invocation(program_name, subcommand_words)
        )
        == label
    )


@pytest.mark.parametrize("program_name", ["echo", "printf", "cat"])
def test_real_catalog_says_that_echo_printf_and_cat_do_not_fetch(program_name):
    knowledge = NetworkRequestKnowledge()

    assert (
        knowledge.program_network_request_label(_invocation(program_name, ()))
        == NonFetchingProgramLabel()
    )


def test_may_program_fetch_on_the_real_catalog_tells_yes_no_and_unknown_apart():
    knowledge = NetworkRequestKnowledge()

    assert knowledge.may_program_fetch("pip") is True
    assert knowledge.may_program_fetch("echo") is False
    assert knowledge.may_program_fetch("mytool") == UnknownProgramNetworkRequestLabel()


def test_one_key_asked_twice_is_counted_twice():
    knowledge = NetworkRequestKnowledge()

    for _ in range(2):
        knowledge.program_network_request_label(_invocation("curl", ()))
        knowledge.may_program_fetch("curl")
        knowledge.may_program_fetch("mytool")

    assert knowledge.uses == KnowledgeUses(
        row_use_counts=_uses(("curl", "", "", ""), ("curl", "", "", ""))
        + _uses(("curl", ANY_SUBCOMMAND, "", ""), ("curl", ANY_SUBCOMMAND, "", "")),
        unknown_input_counts=_uses(
            ("mytool", ANY_SUBCOMMAND, "", ""), ("mytool", ANY_SUBCOMMAND, "", "")
        ),
    )


def test_real_checked_against_is_the_wording_of_a_carried_row_or_names_a_manual_page_or_a_site():
    for row in _real_rows():
        checked_against = row["checked_against"]
        assert (
            checked_against == _NOT_CHECKED
            or _MANUAL_PAGE_NAME.search(checked_against)
            or _DOCUMENTATION_HOST.search(checked_against)
        ), row


def test_pairs_of_the_real_catalog_without_a_row_of_program_behaviors_are_the_pinned_ones():
    with (EXPANDED_TOOL_CALL_CATALOGS_DIR / PROGRAM_BEHAVIORS_CSV).open(
        newline=""
    ) as csv_file:
        behavior_keys = {
            (row["program_name"], row["subcommand"]) for row in csv.DictReader(csv_file)
        }
    program_row_keys = {
        (row["program_name"], row["subcommand"])
        for row in _real_rows()
        if not row["option_name"]
    }

    assert program_row_keys - behavior_keys == _PAIRS_WITHOUT_PROGRAM_BEHAVIOR_ROW_YET


def _code_call_uses(*row_keys: tuple[str, ...]) -> Counter[KnowledgeLookupKey]:
    return Counter((CODE_CALLS_CSV, row_key) for row_key in row_keys)


def _real_code_call_rows() -> list[dict[str, str]]:
    with (NETWORK_REQUEST_CATALOGS_DIR / CODE_CALLS_CSV).open(newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def test_code_call_row_is_read_into_every_field_and_counted(tmp_path):
    knowledge = _knowledge(tmp_path, [], [_SENDING_CODE_CALL_ROW_CELLS])

    assert knowledge.code_call_label(
        CodeLanguage.JAVASCRIPT, "mylib.connect"
    ) == CodeCallLabel(
        "mylib.connect",
        CodeCallEffect.SENDS_NETWORK_REQUEST,
        TargetNotation.HOST_AND_PORT_TUPLE,
        NetworkRequestTargetKind.HOST,
    )
    assert knowledge.uses == KnowledgeUses(
        row_use_counts=_code_call_uses(("javascript", "mylib.connect"))
    )


def test_code_call_without_its_exact_row_is_unknown_and_counted_under_its_language_and_name(
    tmp_path,
):
    knowledge = _knowledge(tmp_path, [], [_SENDING_CODE_CALL_ROW_CELLS])

    assert (
        knowledge.code_call_label(CodeLanguage.PYTHON, "mylib.connect")
        == UnknownCodeCallLabel()
    )
    assert (
        knowledge.code_call_label(CodeLanguage.JAVASCRIPT, "connect")
        == UnknownCodeCallLabel()
    )
    assert knowledge.uses == KnowledgeUses(
        unknown_input_counts=_code_call_uses(
            ("python", "mylib.connect"), ("javascript", "connect")
        )
    )


def test_blank_target_kind_of_a_sending_code_call_is_unknown_and_not_a_default(
    tmp_path,
):
    knowledge = _knowledge(
        tmp_path, [], [{**_SENDING_CODE_CALL_ROW_CELLS, "target_kind": ""}]
    )

    label = knowledge.code_call_label(CodeLanguage.JAVASCRIPT, "mylib.connect")

    assert isinstance(label, CodeCallLabel)
    assert label.target_kind == UnknownNetworkRequestTargetKind()


def test_code_call_that_runs_a_program_has_no_target_notation_or_kind(tmp_path):
    knowledge = _knowledge(tmp_path, [], [_RUNNING_CODE_CALL_ROW_CELLS])

    assert knowledge.code_call_label(CodeLanguage.PYTHON, "os.system") == (
        CodeCallLabel("os.system", CodeCallEffect.RUNS_PROGRAM, None, None)
    )


def test_has_code_call_row_tells_exact_names_of_a_language_apart_and_counts_nothing(
    tmp_path,
):
    knowledge = _knowledge(tmp_path, [], [_SENDING_CODE_CALL_ROW_CELLS])

    assert knowledge.has_code_call_row(CodeLanguage.JAVASCRIPT, "mylib.connect")
    assert not knowledge.has_code_call_row(CodeLanguage.JAVASCRIPT, "connect")
    assert not knowledge.has_code_call_row(CodeLanguage.PYTHON, "mylib.connect")
    assert knowledge.uses == KnowledgeUses()


@pytest.mark.parametrize(("rows", "message"), _CODE_CALL_CATALOGS_THAT_CANNOT_LOAD)
def test_code_call_catalog_that_extract_network_requests_cannot_use_fails_the_load(
    tmp_path, rows, message
):
    with pytest.raises(ValueError, match=message):
        _knowledge(tmp_path, [], rows)


def test_real_code_call_catalog_loads_and_holds_no_invisible_control_characters():
    NetworkRequestKnowledge()
    text = (NETWORK_REQUEST_CATALOGS_DIR / CODE_CALLS_CSV).read_text()

    assert not [c for c in text if ord(c) < 32 and c != "\n"]
    assert all(row["reviewed"] == "" for row in _real_code_call_rows())


def test_real_code_call_rows_are_carried_from_the_old_tables_or_name_a_documentation_page():
    old_pattern_of_language = {
        "python": NETWORK_CALL_OF_LANGUAGE[OldCodeLanguage.PYTHON],
        "javascript": NETWORK_CALL_OF_LANGUAGE[OldCodeLanguage.JAVASCRIPT],
    }
    broken: list[str] = []
    for row in _real_code_call_rows():
        call_text = f"{row['call_name']}("
        if row["checked_against"] == _NOT_CHECKED:
            old_pattern = (
                PROGRAM_RUN_BY_CODE
                if row["effect"] == "runs_program"
                else old_pattern_of_language[row["code_language"]]
            )
            program_words = '["pip"])' if row["effect"] == "runs_program" else ""
            if not old_pattern.search(call_text + program_words):
                broken.append(f"{row['call_name']} is in no old table")
        elif not _DOCUMENTATION_HOST.search(row["checked_against"]):
            broken.append(f"{row['call_name']} names no page")
    assert not broken, "\n".join(broken)


@pytest.mark.parametrize(
    ("code_language", "call_name", "label"),
    [
        (
            CodeLanguage.PYTHON,
            "requests.get",
            CodeCallLabel(
                "requests.get",
                CodeCallEffect.SENDS_NETWORK_REQUEST,
                TargetNotation.URL,
                NetworkRequestTargetKind.URL,
            ),
        ),
        (
            CodeLanguage.PYTHON,
            "from_pretrained",
            CodeCallLabel(
                "from_pretrained",
                CodeCallEffect.SENDS_NETWORK_REQUEST,
                TargetNotation.NAME,
                UnknownNetworkRequestTargetKind(),
            ),
        ),
        (
            CodeLanguage.PYTHON,
            "socket.create_connection",
            CodeCallLabel(
                "socket.create_connection",
                CodeCallEffect.SENDS_NETWORK_REQUEST,
                TargetNotation.HOST_AND_PORT_TUPLE,
                NetworkRequestTargetKind.HOST,
            ),
        ),
        (
            CodeLanguage.PYTHON,
            "subprocess.run",
            CodeCallLabel("subprocess.run", CodeCallEffect.RUNS_PROGRAM, None, None),
        ),
        (
            CodeLanguage.JAVASCRIPT,
            "fetch",
            CodeCallLabel(
                "fetch",
                CodeCallEffect.SENDS_NETWORK_REQUEST,
                TargetNotation.URL,
                NetworkRequestTargetKind.URL,
            ),
        ),
    ],
)
def test_real_code_call_catalog_gives_the_labels_the_decision_document_names(
    code_language, call_name, label
):
    assert NetworkRequestKnowledge().code_call_label(code_language, call_name) == label


@pytest.mark.parametrize("call_name", _OLD_CALLS_WITHOUT_ROW)
def test_real_code_call_catalog_has_no_row_for_calls_that_send_nothing_or_take_a_method_first(
    call_name,
):
    assert not NetworkRequestKnowledge().has_code_call_row(
        CodeLanguage.PYTHON, call_name
    )
