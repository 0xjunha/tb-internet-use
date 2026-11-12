"""Tests for request/code_requests.py."""

import pytest

from tb_internet_use.callrun.model import ArgumentText, CodeLanguage, RanCodeText
from tb_internet_use.network.model import PrintingProgram
from tb_internet_use.program.model import RequestKind
from tb_internet_use.request.code_requests import code_request
from tb_internet_use.request.model import FromCode
from tb_internet_use.toolcall.model import ToolCallKey

KEY = ToolCallKey("trial", "main", 1, 0)


def _request(code: str | None, language: CodeLanguage = CodeLanguage.PYTHON):
    return code_request(KEY, RanCodeText(ArgumentText(3), language, code), "python")


@pytest.mark.parametrize(
    ("code", "language"),
    [
        ("import requests; requests.get(u)", CodeLanguage.PYTHON),
        ("httpx.Client()", CodeLanguage.PYTHON),
        ("urllib.request.urlopen(u)", CodeLanguage.PYTHON),
        ("AutoModel.from_pretrained('bert')", CodeLanguage.PYTHON),
        ("socket.create_connection(('db', 5432))", CodeLanguage.PYTHON),
        ("await fetch(u)", CodeLanguage.JAVASCRIPT),
        ("axios.get(u)", CodeLanguage.JAVASCRIPT),
        ("https.get(u, cb)", CodeLanguage.JAVASCRIPT),
    ],
)
def test_network_calls_make_a_request(code: str, language: CodeLanguage):
    request = _request(code, language)
    assert request is not None
    assert (request.kind, request.source, request.printing_programs) == (
        RequestKind.CODE,
        FromCode(3),
        frozenset({PrintingProgram.CODE}),
    )


@pytest.mark.parametrize(
    "code", [None, "print(1)", "fetch(u)"]
)  # fetch( counts in JavaScript only
def test_no_request(code: str | None):
    assert _request(code) is None


def test_targets_and_hosts_of_code():
    code = (
        "requests.get('https://a.org/x', timeout=5); ET.register_namespace('', 'http://www.w3.org/2000/svg'); "
        "socket.gethostbyname('db'); s.connect(('api', 8000)); d.get('count', 0); 'a.b'.rsplit('.', 1)"
    )
    request = _request(code)
    assert request is not None
    assert [t.value for t in request.targets] == ["https://a.org/x"]
    assert [h.name for h in request.hosts] == ["a.org", "db", "api"]


def test_only_a_whole_program_word_in_a_run_string_names_a_program():
    git_dir = _request('import subprocess; subprocess.run(["rm", "-rf", ".git"])')
    assert git_dir is None
    pip = _request('import os; os.system("python -m pip install x")')
    assert pip is not None and PrintingProgram.PIP in pip.printing_programs


def test_code_that_runs_a_package_manager_asks_for_unnamed_packages():
    request = _request("subprocess.run(['pip', 'install', 'x'])")
    assert request is not None
    assert request.asked_package_names is None
    assert PrintingProgram.PIP in request.printing_programs
