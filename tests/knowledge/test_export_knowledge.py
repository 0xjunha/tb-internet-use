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
    UnknownChangesPackageRegistry,
    UnknownNetworkRequestSender,
    UnknownPackageRegistry,
    UnknownProgramVariable,
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
    PROGRAM_VARIABLES_CSV,
    PUBLIC_HOSTS_CSV,
    ExportKnowledge,
)
from tb_internet_use.knowledge.tool_call_knowledge import (
    HARNESS_TOOLS_CSV,
    TOOL_CALL_CATALOGS_DIR,
)
from tb_internet_use.tool_call.model import HarnessTool

_PUBLIC_HOSTS_HEADER = (
    "host_name,path_prefix,service,package_registry,checked_against,reviewed,note"
)
_HARNESS_WEB_TOOLS_HEADER = "harness,tool,sender,checked_against,reviewed,note"
_PROGRAM_PACKAGE_REGISTRIES_HEADER = "program_name,subcommand,package_registry,package_registry_host_names,checked_against,reviewed,note"
_PROGRAM_VARIABLES_HEADER = "program_name,subcommand,variable_name,changes_package_registry,checked_against,reviewed,note"
# The values of `checked_against`, `reviewed` and `note`, from which no answer is made.
_REVIEW_COLUMNS = ",a manual,yes,"

# (file name, header, the columns of a row before `checked_against`) of one row that loads, for each catalog.
_CATALOGS_WITH_A_ROW = [
    (PUBLIC_HOSTS_CSV, _PUBLIC_HOSTS_HEADER, "reg.org,,package_registry,reg"),
    (HARNESS_WEB_TOOLS_CSV, _HARNESS_WEB_TOOLS_HEADER, "h,search,provider_server"),
    (
        PROGRAM_PACKAGE_REGISTRIES_CSV,
        _PROGRAM_PACKAGE_REGISTRIES_HEADER,
        "pkg,install,reg,reg.org",
    ),
    (PROGRAM_VARIABLES_CSV, _PROGRAM_VARIABLES_HEADER, "pkg,install,PKG_INDEX,yes"),
]

# `blank.org` has a blank service, so its row answers unknown. `hub.org` gives an API under `/api/` and `/api/search/` and a model hub at every other path. `api.org` has rows for paths alone, so another path of it has no row.
_PUBLIC_HOST_ROWS = (
    "reg.org,,package_registry,reg",
    "code.org,,code_hosting,",
    "blank.org,,,",
    "hub.org,/api/,web_api,",
    "hub.org,/api/search/,search_engine,",
    "hub.org,,model_hub,",
    "api.org,/v1/,web_api,",
)
# `h`, `blank` has a blank sender. The sender is not the first value of the enum, so that a knowledge class that gives it without reading the row fails.
_HARNESS_WEB_TOOL_ROWS = ("h,search,provider_server", "h,blank,")
# `pkg`, `sub add` has two hosts, and `pkg`, `blank` a blank registry.
_PROGRAM_PACKAGE_REGISTRY_ROWS = (
    "pkg,install,reg,reg.org",
    "pkg,sub add,reg,reg.org mirror.reg.org",
    "pkg,blank,,",
)
# `PKG_INDEX` names another index of `pkg install`, `MODE` is read for something else, and `BLANK` has a blank answer.
_PROGRAM_VARIABLE_ROWS = (
    "pkg,install,PKG_INDEX,yes",
    "pkg,install,MODE,no",
    "pkg,sub add,PKG_INDEX,yes",
    "pkg,install,BLANK,",
)

# (public host rows, web tool rows, program rows, a part of the error message)
_ROWS_THAT_CANNOT_LOAD = [
    (["Reg.org,,package_registry,reg"], [], [], "not in lower case"),
    ([",,code_hosting,"], [], [], "empty or not in lower case"),
    (["a.org,api/,web_api,"], [], [], "path_prefix 'api/' is neither blank"),
    (["a.org,,docs,"], [], [], "'docs' is not a valid HostService"),
    (["a.org,,package_registry,"], [], [], "holds a name exactly when"),
    (["a.org,,code_hosting,reg"], [], [], "holds a name exactly when"),
    # A blank service is unknown, so it cannot name a registry either.
    (["a.org,,,reg"], [], [], "holds a name exactly when"),
    # Two rows of one host and one path prefix.
    (["a.org,/x/,web_api,", "a.org,/x/,model_hub,"], [], [], "two rows have the key"),
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

# (rows of program_variables.csv, a part of the error message)
_PROGRAM_VARIABLE_ROWS_THAT_CANNOT_LOAD = [
    ([",install,PKG_INDEX,yes"], "program_name is empty"),
    (["pkg,sub  add,PKG_INDEX,yes"], "subcommand 'sub  add'"),
    (["pkg,install,,yes"], "variable_name '' is no variable name"),
    (
        ["pkg,install,PKG_INDEX=x,yes"],
        "variable_name 'PKG_INDEX=x' is no variable name",
    ),
    (["pkg,install,1X,yes"], "variable_name '1X' is no variable name"),
    (["pkg,install,PKG_INDEX,unknown"], "not yes, no or blank"),
    (["pkg,install,PKG_INDEX,Yes"], "not yes, no or blank"),
    (
        ["pkg,install,PKG_INDEX,yes", "pkg,install,PKG_INDEX,no"],
        "two rows have the key",
    ),
]


def _write_catalogs(
    tmp_path: Path,
    public_host_rows: list[str] | tuple[str, ...] = _PUBLIC_HOST_ROWS,
    harness_web_tool_rows: list[str] | tuple[str, ...] = _HARNESS_WEB_TOOL_ROWS,
    program_package_registry_rows: list[str]
    | tuple[str, ...] = _PROGRAM_PACKAGE_REGISTRY_ROWS,
    program_variable_rows: list[str] | tuple[str, ...] = _PROGRAM_VARIABLE_ROWS,
) -> Path:
    """Write the four export CSVs into a folder and return the folder."""
    for file_name, header, rows in (
        (PUBLIC_HOSTS_CSV, _PUBLIC_HOSTS_HEADER, public_host_rows),
        (HARNESS_WEB_TOOLS_CSV, _HARNESS_WEB_TOOLS_HEADER, harness_web_tool_rows),
        (
            PROGRAM_PACKAGE_REGISTRIES_CSV,
            _PROGRAM_PACKAGE_REGISTRIES_HEADER,
            program_package_registry_rows,
        ),
        (PROGRAM_VARIABLES_CSV, _PROGRAM_VARIABLES_HEADER, program_variable_rows),
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
    assert knowledge.public_host("reg.org", url_path=None) == PublicHost(
        HostService.PACKAGE_REGISTRY, "reg"
    )
    # A host without rows for paths answers by its blank prefix at any path.
    assert knowledge.public_host("Code.ORG", url_path="/a/b") == PublicHost(
        HostService.CODE_HOSTING, None
    )
    # A row of another name never answers, also not one of a parent domain.
    assert knowledge.public_host("files.reg.org", url_path="") == UnknownPublicHost()
    assert knowledge.public_host("blank.org", url_path=None) == UnknownPublicHost()

    assert knowledge.uses.row_use_counts == Counter(
        {
            (PUBLIC_HOSTS_CSV, ("reg.org", "")): 1,
            (PUBLIC_HOSTS_CSV, ("code.org", "")): 1,
            (PUBLIC_HOSTS_CSV, ("blank.org", "")): 1,
        }
    )
    assert knowledge.uses.unknown_input_counts == Counter(
        {(PUBLIC_HOSTS_CSV, ("files.reg.org", "")): 1}
    )


# (path of the URL, path prefix of the row that answers for `hub.org`, its service)
_HUB_PATH_CASES = [
    ("/api/models", "/api/", HostService.WEB_API),
    # The longest prefix that starts the path wins, whatever the order of the rows.
    ("/api/search/code", "/api/search/", HostService.SEARCH_ENGINE),
    ("/a/b/resolve/main/model.bin", "", HostService.MODEL_HUB),
    # A prefix matches only from the start of the path and in its case.
    ("/x/api/models", "", HostService.MODEL_HUB),
    ("/API/models", "", HostService.MODEL_HUB),
    # A path that is shorter than a prefix, a URL without a path and a host named without a URL.
    ("/api", "", HostService.MODEL_HUB),
    ("", "", HostService.MODEL_HUB),
    (None, "", HostService.MODEL_HUB),
]


@pytest.mark.parametrize(("url_path", "path_prefix", "service"), _HUB_PATH_CASES)
def test_public_host_is_answered_from_the_row_with_the_longest_path_prefix_of_the_path(
    knowledge, url_path, path_prefix, service
):
    assert knowledge.public_host("hub.org", url_path=url_path) == PublicHost(
        service, None
    )
    assert knowledge.uses.row_use_counts == Counter(
        {(PUBLIC_HOSTS_CSV, ("hub.org", path_prefix)): 1}
    )


@pytest.mark.parametrize(
    ("host_name", "has_row"),
    [
        ("reg.org", True),
        ("Code.ORG", True),
        # A row with a blank service and rows for paths alone are rows of the name too.
        ("blank.org", True),
        ("api.org", True),
        ("files.reg.org", False),
    ],
)
def test_public_host_row_of_a_name_is_told_for_any_path_without_counting(
    knowledge, host_name, has_row
):
    assert knowledge.has_public_host_row(host_name) is has_row
    assert knowledge.uses == KnowledgeUses()


def test_path_of_a_host_with_rows_for_other_paths_alone_is_unknown_and_counted_as_the_blank_prefix(
    knowledge,
):
    assert knowledge.public_host("api.org", url_path="/v1/x") == PublicHost(
        HostService.WEB_API, None
    )
    assert knowledge.public_host("api.org", url_path="/v2/x") == UnknownPublicHost()
    assert knowledge.public_host("api.org", url_path=None) == UnknownPublicHost()

    assert knowledge.uses.row_use_counts == Counter(
        {(PUBLIC_HOSTS_CSV, ("api.org", "/v1/")): 1}
    )
    assert knowledge.uses.unknown_input_counts == Counter(
        {(PUBLIC_HOSTS_CSV, ("api.org", "")): 2}
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
    # The row of another subcommand stands in neither for a subcommand without a row nor for a command without a subcommand.
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


def test_changes_package_registry_is_answered_only_by_the_row_of_the_very_subcommand_and_name_or_unknown_and_counted(
    knowledge,
):
    install = _program_invocation("pkg", "install")
    assert knowledge.changes_package_registry(install, "PKG_INDEX") is True
    assert knowledge.changes_package_registry(install, "MODE") is False
    assert (
        knowledge.changes_package_registry(
            _program_invocation("pkg", "sub", "add"), "PKG_INDEX"
        )
        is True
    )
    # A blank cell and a missing row are unknown in two types, so that a rule can take one and leave the other.
    assert knowledge.changes_package_registry(install, "BLANK") == (
        UnknownChangesPackageRegistry()
    )
    # A name in another case, another subcommand and a name without a row of the subcommand have no row.
    assert knowledge.changes_package_registry(install, "pkg_index") == (
        UnknownProgramVariable()
    )
    assert (
        knowledge.changes_package_registry(
            _program_invocation("pkg", "remove"), "PKG_INDEX"
        )
        == UnknownProgramVariable()
    )
    assert (
        knowledge.changes_package_registry(
            _program_invocation("pkg", "sub", "add"), "MODE"
        )
        == UnknownProgramVariable()
    )

    assert knowledge.uses.row_use_counts == Counter(
        {
            (PROGRAM_VARIABLES_CSV, ("pkg", "install", "PKG_INDEX")): 1,
            (PROGRAM_VARIABLES_CSV, ("pkg", "install", "MODE")): 1,
            (PROGRAM_VARIABLES_CSV, ("pkg", "sub add", "PKG_INDEX")): 1,
            (PROGRAM_VARIABLES_CSV, ("pkg", "install", "BLANK")): 1,
        }
    )
    assert knowledge.uses.unknown_input_counts == Counter(
        {
            (PROGRAM_VARIABLES_CSV, ("pkg", "install", "pkg_index")): 1,
            (PROGRAM_VARIABLES_CSV, ("pkg", "remove", "PKG_INDEX")): 1,
            (PROGRAM_VARIABLES_CSV, ("pkg", "sub add", "MODE")): 1,
        }
    )


def test_each_lookup_adds_one_to_its_count(knowledge):
    for _ in range(3):
        knowledge.public_host("reg.org", url_path=None)
        knowledge.public_host("a.org", url_path=None)

    assert knowledge.uses.row_use_counts[PUBLIC_HOSTS_CSV, ("reg.org", "")] == 3
    assert knowledge.uses.unknown_input_counts[PUBLIC_HOSTS_CSV, ("a.org", "")] == 3


def test_each_knowledge_class_counts_only_its_own_lookups(tmp_path):
    catalogs_dir = _write_catalogs(tmp_path)
    first = ExportKnowledge(catalogs_dir=catalogs_dir)
    second = ExportKnowledge(catalogs_dir=catalogs_dir)

    first.public_host("reg.org", url_path=None)
    first.network_request_sender(HarnessTool("h", "search"))
    first.package_registry(_program_invocation("pkg", "install"))
    first.changes_package_registry(_program_invocation("pkg", "install"), "MODE")

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


@pytest.mark.parametrize(
    ("program_variable_rows", "message"), _PROGRAM_VARIABLE_ROWS_THAT_CANNOT_LOAD
)
def test_row_of_program_variables_that_export_rows_cannot_use_raises_when_the_catalogs_load(
    tmp_path, program_variable_rows, message
):
    catalogs_dir = _write_catalogs(
        tmp_path, program_variable_rows=program_variable_rows
    )

    with pytest.raises(ValueError, match=message):
        ExportKnowledge(catalogs_dir=catalogs_dir)


@pytest.mark.parametrize(("file_name", "header", "row"), _CATALOGS_WITH_A_ROW)
@pytest.mark.parametrize("reviewed", ["", "yes", "agents"])
def test_row_with_a_reviewed_of_empty_yes_or_agents_loads(
    tmp_path, file_name, header, row, reviewed
):
    catalogs_dir = _write_catalogs(tmp_path)
    (catalogs_dir / file_name).write_text(f"{header}\n{row},a manual,{reviewed},\n")

    ExportKnowledge(catalogs_dir=catalogs_dir)


@pytest.mark.parametrize(("file_name", "header", "row"), _CATALOGS_WITH_A_ROW)
@pytest.mark.parametrize("reviewed", ["no", "Yes", "agent"])
def test_row_with_a_reviewed_other_than_empty_yes_or_agents_raises(
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


def test_knowledge_class_module_can_be_the_first_import_of_a_process():
    # `ExportKnowledge` imports the models of three steps, whose packages import their knowledge classes under TYPE_CHECKING only, so a fresh process shows that no cycle runs.
    module = "tb_internet_use.knowledge.export_knowledge"
    subprocess.run([sys.executable, "-I", "-c", f"import {module}"], check=True)


@pytest.mark.parametrize(
    "file_name",
    [
        PUBLIC_HOSTS_CSV,
        HARNESS_WEB_TOOLS_CSV,
        PROGRAM_PACKAGE_REGISTRIES_CSV,
        PROGRAM_VARIABLES_CSV,
    ],
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
    ) == PackageRegistry(
        "apt", ("deb.debian.org", "archive.ubuntu.com", "security.ubuntu.com")
    )
    assert real_knowledge.package_registry(
        _program_invocation("go", "build")
    ) == PackageRegistry("go_module_proxy", ("proxy.golang.org",))
    assert (
        real_knowledge.public_host("a.example.org", url_path=None)
        == UnknownPublicHost()
    )
    assert real_knowledge.public_host(
        "repo1.maven.org", url_path="/maven2/x"
    ) == PublicHost(HostService.PACKAGE_REGISTRY, "maven_central")
    assert real_knowledge.public_host("github.com", url_path=None) == PublicHost(
        HostService.CODE_HOSTING, None
    )
    assert real_knowledge.public_host("www.bing.com", url_path=None) == PublicHost(
        HostService.SEARCH_ENGINE, None
    )
    assert (
        real_knowledge.network_request_sender(HarnessTool("codex", "web_search_call"))
        == NetworkRequestSender.PROVIDER_SERVER
    )
    assert (
        real_knowledge.changes_package_registry(
            _program_invocation("apt-get", "install"), "DEBIAN_FRONTEND"
        )
        is False
    )
    assert (
        real_knowledge.changes_package_registry(
            _program_invocation("go", "build"), "GOPROXY"
        )
        is True
    )
    assert (
        real_knowledge.changes_package_registry(
            _program_invocation("go", "build"), "GOPATH"
        )
        == UnknownChangesPackageRegistry()
    )
    # A documented index variable has a row although no trajectory sets it, in each case that npm reads.
    assert (
        real_knowledge.changes_package_registry(
            _program_invocation("pip", "install"), "PIP_INDEX_URL"
        )
        is True
    )
    for variable_name in ("npm_config_registry", "NPM_CONFIG_REGISTRY"):
        assert (
            real_knowledge.changes_package_registry(
                _program_invocation("npx"), variable_name
            )
            is True
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

    assert program_package_registry_keys - program_behavior_keys == set()


def test_every_real_program_variable_row_names_a_program_and_subcommand_with_a_package_registry_row():
    # `export_rows` asks about a variable only for a program and subcommand that `program_package_registries.csv` gives a registry.
    program_package_registry_keys = {
        (row["program_name"], row["subcommand"])
        for row in _real_csv_rows(EXPORT_CATALOGS_DIR, PROGRAM_PACKAGE_REGISTRIES_CSV)
        if row["package_registry"]
    }
    program_variable_keys = {
        (row["program_name"], row["subcommand"])
        for row in _real_csv_rows(EXPORT_CATALOGS_DIR, PROGRAM_VARIABLES_CSV)
    }

    assert program_variable_keys - program_package_registry_keys == set()


def test_every_real_program_and_subcommand_with_a_package_registry_has_a_variable_that_changes_it():
    # A variable without a row gives the default hosts, so each program with a registry lists the documented variables that send its requests elsewhere or keep them from going out.
    program_package_registry_keys = {
        (row["program_name"], row["subcommand"])
        for row in _real_csv_rows(EXPORT_CATALOGS_DIR, PROGRAM_PACKAGE_REGISTRIES_CSV)
        if row["package_registry"]
    }
    keys_with_a_changing_variable = {
        (row["program_name"], row["subcommand"])
        for row in _real_csv_rows(EXPORT_CATALOGS_DIR, PROGRAM_VARIABLES_CSV)
        if row["changes_package_registry"] == "yes"
    }

    assert program_package_registry_keys - keys_with_a_changing_variable == set()
