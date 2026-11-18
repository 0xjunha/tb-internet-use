"""Tests for knowledge/export_knowledge.py, with made-up catalogs, and of the rows of the real catalogs against the catalogs of the steps whose names they use."""

import csv
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from tb_internet_use.expanded_tool_call.model import ProgramInvocation
from tb_internet_use.export.model import (
    HostService,
    NetworkRequestSender,
    PackageRegistry,
    PublicHost,
    UnknownNetworkRequestSender,
    UnknownPackageRegistry,
    UnknownPublicHost,
)
from tb_internet_use.knowledge.catalog import KnowledgeUses
from tb_internet_use.knowledge.expanded_tool_call_knowledge import (
    EXPANDED_TOOL_CALL_CATALOGS_DIR,
    PROGRAM_BEHAVIORS_CSV,
)
from tb_internet_use.knowledge.export_knowledge import (
    EXPORT_CATALOGS_DIR,
    HARNESS_WEB_TOOLS_CSV,
    PROGRAM_PACKAGE_REGISTRIES_CSV,
    PUBLIC_HOSTS_CSV,
    ExportKnowledge,
)
from tb_internet_use.knowledge.tool_call_knowledge import (
    HARNESS_TOOLS_CSV,
    TOOL_CALL_CATALOGS_DIR,
)
from tb_internet_use.tool_call.model import HarnessTool

_PUBLIC_HOSTS_HEADER = (
    "host_name,service,package_registry,checked_against,reviewed,note"
)
_HARNESS_WEB_TOOLS_HEADER = "harness,tool,sender,checked_against,reviewed,note"
_PROGRAM_PACKAGE_REGISTRIES_HEADER = "program_name,subcommand,package_registry,package_registry_host_names,checked_against,reviewed,note"
# The values of `checked_against`, `reviewed` and `note`, from which no answer is made.
_REVIEW_COLUMNS = ",a manual,yes,"

# (file name, header, the columns of a row before `checked_against`) of one row that loads, for each catalog.
_CATALOGS_WITH_A_ROW = [
    (PUBLIC_HOSTS_CSV, _PUBLIC_HOSTS_HEADER, "reg.org,package_registry,reg"),
    (HARNESS_WEB_TOOLS_CSV, _HARNESS_WEB_TOOLS_HEADER, "h,search,provider_server"),
    (
        PROGRAM_PACKAGE_REGISTRIES_CSV,
        _PROGRAM_PACKAGE_REGISTRIES_HEADER,
        "pkg,install,reg,reg.org",
    ),
]

# `blank.org` has a blank service, so its row answers unknown.
_PUBLIC_HOST_ROWS = (
    "reg.org,package_registry,reg",
    "code.org,code_hosting,",
    "blank.org,,",
)
# `h`, `blank` has a blank sender. The sender is not the first value of the enum, so that a door that gives it without reading the row fails.
_HARNESS_WEB_TOOL_ROWS = ("h,search,provider_server", "h,blank,")
# `pkg`, `add` has two hosts, and `pkg`, `blank` a blank registry.
_PROGRAM_PACKAGE_REGISTRY_ROWS = (
    "pkg,install,reg,reg.org",
    "pkg,sub add,reg,reg.org mirror.reg.org",
    "pkg,blank,,",
)

# (public host rows, web tool rows, program rows, a part of the error message)
_ROWS_THAT_CANNOT_LOAD = [
    (["Reg.org,package_registry,reg"], [], [], "not in lower case"),
    ([",code_hosting,"], [], [], "empty or not in lower case"),
    (["a.org,docs,"], [], [], "'docs' is not a valid HostService"),
    (["a.org,package_registry,"], [], [], "holds a name exactly when"),
    (["a.org,code_hosting,reg"], [], [], "holds a name exactly when"),
    # A blank service is unknown, so it cannot name a registry either.
    (["a.org,,reg"], [], [], "holds a name exactly when"),
    ([], ["h,t,unknown"], [], "unknown only when blank"),
    ([], ["h,t,server"], [], "'server' is not a valid NetworkRequestSender"),
    ([], [",t,provider_server"], [], "harness or tool is empty"),
    ([], ["h,,provider_server"], [], "harness or tool is empty"),
    ([], [], [",install,reg,reg.org"], "program_name is empty"),
    ([], [], ["pkg,sub  add,reg,reg.org"], "subcommand 'sub  add'"),
    ([], [], ["pkg,install,reg,a.org  b.org"], "package_registry_host_names"),
    ([], [], ["pkg,install,reg,"], "both are blank or both are given"),
    ([], [], ["pkg,install,,reg.org"], "both are blank or both are given"),
    ([], [], ["pkg,install,reg,Reg.org"], "not in lower case"),
]

# The (program, subcommand) pairs of the real program package registry catalog that `program_behaviors.csv` has no row for yet.
# The rows come with the program catalog of `extract_network_requests`, which needs the same programs, and the set then shrinks, so that a pair that is misspelled never hides in it.
_PAIRS_WITHOUT_PROGRAM_BEHAVIOR_ROW_YET = {
    ("apt", "update"),
    ("apt", "install"),
    ("sbt", "compile"),
    ("sbt", "test"),
    ("sbt", "run"),
    ("sbt", "package"),
}


def _write_catalogs(
    tmp_path: Path,
    public_host_rows: list[str] | tuple[str, ...] = _PUBLIC_HOST_ROWS,
    harness_web_tool_rows: list[str] | tuple[str, ...] = _HARNESS_WEB_TOOL_ROWS,
    program_package_registry_rows: list[str]
    | tuple[str, ...] = _PROGRAM_PACKAGE_REGISTRY_ROWS,
) -> Path:
    """Write the three export CSVs into a folder and return the folder."""
    for file_name, header, rows in (
        (PUBLIC_HOSTS_CSV, _PUBLIC_HOSTS_HEADER, public_host_rows),
        (HARNESS_WEB_TOOLS_CSV, _HARNESS_WEB_TOOLS_HEADER, harness_web_tool_rows),
        (
            PROGRAM_PACKAGE_REGISTRIES_CSV,
            _PROGRAM_PACKAGE_REGISTRIES_HEADER,
            program_package_registry_rows,
        ),
    ):
        lines = [header, *(row + _REVIEW_COLUMNS for row in rows)]
        (tmp_path / file_name).write_text("\n".join(lines) + "\n")
    return tmp_path


def _program_invocation(program_name: str, *subcommand_words: str) -> ProgramInvocation:
    return ProgramInvocation(
        program_name=program_name,
        subcommand_words=subcommand_words,
        options=(),
        arguments=("x",),
        gets_more_arguments_at_run_time=False,
        unread_words=(),
        exits_with_exit_code_of_next_program=False,
    )


def _real_csv_rows(catalogs_dir: Path, file_name: str) -> list[dict[str, str]]:
    with (catalogs_dir / file_name).open(newline="") as csv_file:
        return list(csv.DictReader(csv_file))


@pytest.fixture
def knowledge(tmp_path) -> ExportKnowledge:
    return ExportKnowledge(catalogs_dir=_write_catalogs(tmp_path))


def test_public_host_is_answered_from_its_row_in_lower_case_or_unknown_and_counted(
    knowledge,
):
    assert knowledge.public_host("reg.org") == PublicHost(
        HostService.PACKAGE_REGISTRY, "reg"
    )
    assert knowledge.public_host("Code.ORG") == PublicHost(
        HostService.CODE_HOSTING, None
    )
    # A row of another name never answers, also not one of a parent domain.
    assert knowledge.public_host("files.reg.org") == UnknownPublicHost()
    assert knowledge.public_host("blank.org") == UnknownPublicHost()

    assert knowledge.uses.row_use_counts == Counter(
        {
            (PUBLIC_HOSTS_CSV, ("reg.org",)): 1,
            (PUBLIC_HOSTS_CSV, ("code.org",)): 1,
            (PUBLIC_HOSTS_CSV, ("blank.org",)): 1,
        }
    )
    assert knowledge.uses.unknown_input_counts == Counter(
        {(PUBLIC_HOSTS_CSV, ("files.reg.org",)): 1}
    )


def test_network_request_sender_is_answered_from_the_row_of_the_tool_or_unknown_and_counted(
    knowledge,
):
    assert (
        knowledge.network_request_sender(HarnessTool("h", "search"))
        == NetworkRequestSender.PROVIDER_SERVER
    )
    assert (
        knowledge.network_request_sender(HarnessTool("h", "blank"))
        == UnknownNetworkRequestSender()
    )
    # The same tool name of another harness has no row.
    assert (
        knowledge.network_request_sender(HarnessTool("other", "search"))
        == UnknownNetworkRequestSender()
    )

    assert knowledge.uses.row_use_counts == Counter(
        {
            (HARNESS_WEB_TOOLS_CSV, ("h", "search")): 1,
            (HARNESS_WEB_TOOLS_CSV, ("h", "blank")): 1,
        }
    )
    assert knowledge.uses.unknown_input_counts == Counter(
        {(HARNESS_WEB_TOOLS_CSV, ("other", "search")): 1}
    )


def test_package_registry_is_answered_only_by_the_row_of_the_very_subcommand_or_unknown_and_counted(
    knowledge,
):
    assert knowledge.package_registry(
        _program_invocation("pkg", "sub", "add")
    ) == PackageRegistry("reg", ("reg.org", "mirror.reg.org"))
    assert knowledge.package_registry(
        _program_invocation("pkg", "install")
    ) == PackageRegistry("reg", ("reg.org",))
    assert (
        knowledge.package_registry(_program_invocation("pkg", "blank"))
        == UnknownPackageRegistry()
    )
    # No row without a subcommand stands in for a missing one, and no row of a subcommand stands in for a command without one.
    assert (
        knowledge.package_registry(_program_invocation("pkg", "remove"))
        == UnknownPackageRegistry()
    )
    assert knowledge.package_registry(_program_invocation("pkg")) == (
        UnknownPackageRegistry()
    )

    assert knowledge.uses.row_use_counts == Counter(
        {
            (PROGRAM_PACKAGE_REGISTRIES_CSV, ("pkg", "sub add")): 1,
            (PROGRAM_PACKAGE_REGISTRIES_CSV, ("pkg", "install")): 1,
            (PROGRAM_PACKAGE_REGISTRIES_CSV, ("pkg", "blank")): 1,
        }
    )
    assert knowledge.uses.unknown_input_counts == Counter(
        {
            (PROGRAM_PACKAGE_REGISTRIES_CSV, ("pkg", "remove")): 1,
            (PROGRAM_PACKAGE_REGISTRIES_CSV, ("pkg", "")): 1,
        }
    )


def test_each_lookup_adds_one_to_its_count(knowledge):
    for _ in range(3):
        knowledge.public_host("reg.org")
        knowledge.public_host("a.org")

    assert knowledge.uses.row_use_counts[PUBLIC_HOSTS_CSV, ("reg.org",)] == 3
    assert knowledge.uses.unknown_input_counts[PUBLIC_HOSTS_CSV, ("a.org",)] == 3


def test_each_door_counts_only_its_own_lookups(tmp_path):
    catalogs_dir = _write_catalogs(tmp_path)
    first = ExportKnowledge(catalogs_dir=catalogs_dir)
    second = ExportKnowledge(catalogs_dir=catalogs_dir)

    first.public_host("reg.org")
    first.network_request_sender(HarnessTool("h", "search"))
    first.package_registry(_program_invocation("pkg", "install"))

    assert second.uses == KnowledgeUses()


@pytest.mark.parametrize(
    ("public_host_rows", "harness_web_tool_rows", "program_rows", "message"),
    _ROWS_THAT_CANNOT_LOAD,
)
def test_row_that_export_rows_cannot_use_raises_when_the_catalogs_load(
    tmp_path, public_host_rows, harness_web_tool_rows, program_rows, message
):
    catalogs_dir = _write_catalogs(
        tmp_path, public_host_rows, harness_web_tool_rows, program_rows
    )

    with pytest.raises(ValueError, match=message):
        ExportKnowledge(catalogs_dir=catalogs_dir)


@pytest.mark.parametrize(("file_name", "header", "row"), _CATALOGS_WITH_A_ROW)
@pytest.mark.parametrize("reviewed", ["no", "Yes"])
def test_row_with_a_reviewed_other_than_empty_or_yes_raises(
    tmp_path, file_name, header, row, reviewed
):
    catalogs_dir = _write_catalogs(tmp_path)
    (catalogs_dir / file_name).write_text(f"{header}\n{row},a manual,{reviewed},\n")

    with pytest.raises(ValueError, match="reviewed is"):
        ExportKnowledge(catalogs_dir=catalogs_dir)


@pytest.mark.parametrize(("file_name", "header", "row"), _CATALOGS_WITH_A_ROW)
def test_row_without_checked_against_raises(tmp_path, file_name, header, row):
    catalogs_dir = _write_catalogs(tmp_path)
    (catalogs_dir / file_name).write_text(f"{header}\n{row},,,\n")

    with pytest.raises(ValueError, match="checked_against is empty"):
        ExportKnowledge(catalogs_dir=catalogs_dir)


def test_door_module_can_be_the_first_import_of_a_process():
    # The door imports the models of three steps, whose packages import their doors under TYPE_CHECKING only, so a fresh process shows that no cycle runs.
    module = "tb_internet_use.knowledge.export_knowledge"
    subprocess.run([sys.executable, "-I", "-c", f"import {module}"], check=True)


@pytest.mark.parametrize(
    "file_name",
    [PUBLIC_HOSTS_CSV, HARNESS_WEB_TOOLS_CSV, PROGRAM_PACKAGE_REGISTRIES_CSV],
)
def test_real_catalog_holds_no_invisible_control_characters(file_name):
    # Bytes, since reading text would turn a CR into a line break.
    data = (EXPORT_CATALOGS_DIR / file_name).read_bytes()

    assert not [byte for byte in data if (byte < 0x20 and byte != 0x0A) or byte == 0x7F]


def test_real_catalogs_load_and_answer_for_the_rows_they_hold():
    # The load refuses a blank checked_against, a word that no column allows and two rows with one key.
    real_knowledge = ExportKnowledge()

    assert real_knowledge.package_registry(
        _program_invocation("uv", "pip", "install")
    ) == PackageRegistry("pypi", ("pypi.org",))
    assert real_knowledge.package_registry(
        _program_invocation("apt-get", "update")
    ) == PackageRegistry("apt", ("deb.debian.org", "archive.ubuntu.com"))
    assert real_knowledge.package_registry(
        _program_invocation("go", "build")
    ) == PackageRegistry("go_module_proxy", ("proxy.golang.org",))
    assert real_knowledge.public_host("files.pythonhosted.org") == UnknownPublicHost()
    assert real_knowledge.public_host("repo1.maven.org") == PublicHost(
        HostService.PACKAGE_REGISTRY, "maven_central"
    )
    assert real_knowledge.public_host("github.com") == PublicHost(
        HostService.CODE_HOSTING, None
    )
    assert real_knowledge.public_host("www.bing.com") == PublicHost(
        HostService.SEARCH_ENGINE, None
    )
    assert (
        real_knowledge.network_request_sender(HarnessTool("codex", "web_search_call"))
        == NetworkRequestSender.PROVIDER_SERVER
    )


def test_every_real_web_tool_row_names_a_tool_of_the_harness_tool_catalog():
    harness_tool_keys = {
        (row["harness"], row["tool"])
        for row in _real_csv_rows(TOOL_CALL_CATALOGS_DIR, HARNESS_TOOLS_CSV)
    }
    web_tool_keys = {
        (row["harness"], row["tool"])
        for row in _real_csv_rows(EXPORT_CATALOGS_DIR, HARNESS_WEB_TOOLS_CSV)
    }

    assert web_tool_keys - harness_tool_keys == set()


def test_every_real_program_row_names_a_program_and_subcommand_of_the_program_catalog():
    program_behavior_keys = {
        (row["program_name"], row["subcommand"])
        for row in _real_csv_rows(
            EXPANDED_TOOL_CALL_CATALOGS_DIR, PROGRAM_BEHAVIORS_CSV
        )
    }
    program_package_registry_keys = {
        (row["program_name"], row["subcommand"])
        for row in _real_csv_rows(EXPORT_CATALOGS_DIR, PROGRAM_PACKAGE_REGISTRIES_CSV)
    }

    assert (
        program_package_registry_keys - program_behavior_keys
        == _PAIRS_WITHOUT_PROGRAM_BEHAVIOR_ROW_YET
    )
