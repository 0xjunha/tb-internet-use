"""Tests for request/targets.py."""

import pytest

from tb_internet_use.callrun.model import VariableValues
from tb_internet_use.network.model import Host, HostKind
from tb_internet_use.program.arguments import parse_arguments
from tb_internet_use.program.model import AskedPackagesSource, RequestKind, RequestRule
from tb_internet_use.request.model import RequestTarget
from tb_internet_use.request.program_options import option_facts
from tb_internet_use.request.targets import (
    asked_package_names,
    request_hosts,
    request_targets,
)

LOOP = VariableValues("p", ("a", "b"), takes_each_value_in_turn=True)
BRANCHES = VariableValues("q", ("c", "d"), takes_each_value_in_turn=False)
SINGLE = VariableValues("U", ("a.org",), takes_each_value_in_turn=False)
ONE_ITEM_LOOP = VariableValues("o", ("e",), takes_each_value_in_turn=True)
_PIP_INSTALL_RULE = RequestRule(
    RequestKind.PACKAGE,
    frozenset(),
    None,
    False,
    AskedPackagesSource.TARGETS,
    False,
    False,
)


@pytest.mark.parametrize(
    ("word", "targets"),
    [
        ("x", [RequestTarget("x", "x", None)]),
        ("https://$U/x", [RequestTarget("https://$U/x", "https://a.org/x", None)]),
        ("$p", [RequestTarget("$p", "a", "p"), RequestTarget("$p", "b", "p")]),
        ("$q", [RequestTarget("$q", "c", None), RequestTarget("$q", "d", None)]),
        ("$o", [RequestTarget("$o", "e", "o")]),
        (
            "$o/$p",
            [RequestTarget("$o/$p", "e/a", "p"), RequestTarget("$o/$p", "e/b", "p")],
        ),
        (
            "https://$U/$p",
            [
                RequestTarget("https://$U/$p", "https://a.org/a", "p"),
                RequestTarget("https://$U/$p", "https://a.org/b", "p"),
            ],
        ),
        ("$PKG", [RequestTarget("$PKG", None, None)]),
        ("$p/$(date)", [RequestTarget("$p/$(date)", None, "p")] * 2),
        ("$(cat f)", [RequestTarget("$(cat f)", None, None)]),
        ("${U:-b.org}", [RequestTarget("${U:-b.org}", None, None)]),
        (
            "$p-$q",
            [RequestTarget("$p-$q", None, None)],
        ),  # two variables of several values
    ],
)
def test_request_targets(word: str, targets: list[RequestTarget]):
    assert (
        list(request_targets([word], [LOOP, BRANCHES, SINGLE, ONE_ITEM_LOOP]))
        == targets
    )


def _hosts(
    program: str, kind: RequestKind, *texts: str, index_urls: tuple[str, ...] = ()
) -> list[str]:
    targets = [RequestTarget(t, t, None) for t in texts]
    return [host.name for host in request_hosts(program, kind, targets, index_urls)]


def test_request_hosts():
    assert _hosts("curl", RequestKind.URL, "https://a.org/x", "localhost:8000/y") == [
        "a.org",
        "localhost",
    ]
    assert _hosts(
        "pip", RequestKind.PACKAGE, "x", index_urls=("https://i.org/simple",)
    ) == ["i.org"]
    assert _hosts(
        "git", RequestKind.GIT, "git@github.com:org/repo.git", "/local/repo"
    ) == ["github.com"]
    assert _hosts("nc", RequestKind.REMOTE_HOST, "box", "80") == ["box"]
    assert _hosts("rsync", RequestKind.REMOTE_HOST, "f", "user@box:/tmp") == ["box"]
    assert _hosts("dig", RequestKind.REMOTE_HOST, "@8.8.8.8", "a.org", "+short") == [
        "8.8.8.8",
        "a.org",
    ]
    assert _hosts("rsync", RequestKind.REMOTE_HOST, "./a", "/b") == []
    assert _hosts("getent", RequestKind.REMOTE_HOST, "a.org", "db") == ["a.org", "db"]


def test_a_host_comes_from_the_filled_value():
    targets = request_targets(["https://$U/x"], [SINGLE])
    assert request_hosts("curl", RequestKind.URL, targets, ()) == (
        Host("a.org", HostKind.PUBLIC),
    )


def test_a_git_refspec_names_no_host():
    assert _hosts("git", RequestKind.GIT, "origin", "main:main") == []


def test_a_host_with_an_unknown_value_is_templated():
    hosts = request_hosts(
        "curl", RequestKind.URL, [RequestTarget("https://$H/x", None, None)], ()
    )
    assert hosts == (Host("$h", HostKind.TEMPLATED),)


@pytest.mark.parametrize(
    ("asked", "arguments", "names"),
    [
        (AskedPackagesSource.NONE, "update", frozenset()),
        (AskedPackagesSource.FILE_OR_PROJECT, "sync", None),
        (
            AskedPackagesSource.TARGETS,
            "install Requests==2.0 numpy",
            frozenset({"requests", "numpy"}),
        ),
        (
            AskedPackagesSource.TARGETS,
            "install",
            None,
        ),  # no target, e.g. npm install of the project's packages
        (AskedPackagesSource.TARGETS, "install -r reqs.txt x", None),
        (AskedPackagesSource.TARGETS, "install -e . x", None),
        (AskedPackagesSource.TARGETS, "install .", None),
        (AskedPackagesSource.TARGETS, "install .[dev]", None),
        (AskedPackagesSource.TARGETS, "install ./dist/x-1.0.whl", None),
        (AskedPackagesSource.TARGETS, "install git+https://github.com/o/r", None),
    ],
)
def test_asked_package_names(
    asked: AskedPackagesSource, arguments: str, names: frozenset[str] | None
):
    parsed = parse_arguments("pip", tuple(arguments.split()))
    targets = request_targets(parsed.plain_arguments[1:], [])
    names_packages_in_files = option_facts(
        "pip", parsed, _PIP_INSTALL_RULE
    ).names_packages_in_files
    assert asked_package_names(asked, targets, names_packages_in_files) == names


def test_asked_package_names_unknown_for_an_unknown_value():
    targets = request_targets(["$PKG"], [])
    assert asked_package_names(AskedPackagesSource.TARGETS, targets, False) is None
