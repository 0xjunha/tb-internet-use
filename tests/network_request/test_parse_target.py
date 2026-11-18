"""Tests for network_request/parse_target.py."""

import pytest

from tb_internet_use.network_request.model import (
    NetworkRequestTargetKind,
    ParsedTarget,
    TargetNotation,
)
from tb_internet_use.network_request.parse_target import parse_target


def _host_only(host_name: str | None) -> ParsedTarget:
    return ParsedTarget(host_name, None, is_local_path=False)


@pytest.mark.parametrize(
    ("target", "target_notation", "parsed_target"),
    [
        # Code calls such as `requests.get("http://localhost:8000/health")`.
        ("http://localhost:8000/health", TargetNotation.URL, _host_only("localhost")),
        ("pypi.org/simple", TargetNotation.URL, _host_only(None)),
        # curl, which reads a word without a scheme as a URL.
        ("https://a.org/x", TargetNotation.URL_OR_SCHEMELESS_URL, _host_only("a.org")),
        (
            "pypi.org/simple",
            TargetNotation.URL_OR_SCHEMELESS_URL,
            _host_only("pypi.org"),
        ),
        (
            "localhost:8000/y",
            TargetNotation.URL_OR_SCHEMELESS_URL,
            _host_only("localhost"),
        ),
        ("a.org", TargetNotation.URL_OR_SCHEMELESS_URL, _host_only("a.org")),
        ("a.org?q=1", TargetNotation.URL_OR_SCHEMELESS_URL, _host_only("a.org")),
        # A URL inside the query of a schemeless URL does not hide its host.
        (
            "a.org/r?u=http://b.org/x",
            TargetNotation.URL_OR_SCHEMELESS_URL,
            _host_only("a.org"),
        ),
        ("file:///tmp/x", TargetNotation.URL_OR_SCHEMELESS_URL, _host_only(None)),
        ("$U/x", TargetNotation.URL_OR_SCHEMELESS_URL, _host_only(None)),
        # git, whose remote can be a URL or an scp-like address.
        (
            "git@github.com:a/b.git",
            TargetNotation.URL_OR_SCP_LIKE_ADDRESS,
            _host_only("github.com"),
        ),
        (
            "github.com:a/b.git",
            TargetNotation.URL_OR_SCP_LIKE_ADDRESS,
            _host_only("github.com"),
        ),
        (
            "https://github.com/a/b",
            TargetNotation.URL_OR_SCP_LIKE_ADDRESS,
            _host_only("github.com"),
        ),
        ("main:main", TargetNotation.URL_OR_SCP_LIKE_ADDRESS, _host_only(None)),
        ("origin", TargetNotation.URL_OR_SCP_LIKE_ADDRESS, _host_only(None)),
        ("/local/repo", TargetNotation.URL_OR_SCP_LIKE_ADDRESS, _host_only(None)),
        # ping, nc, dig and getent, whose target is a host.
        ("pypi.org", TargetNotation.HOST_NAME, _host_only("pypi.org")),
        ("user@box", TargetNotation.HOST_NAME, _host_only("box")),
        ("@8.8.8.8", TargetNotation.HOST_NAME, _host_only("8.8.8.8")),
        # rsync, whose remote is `host:path`.
        ("user@box:/tmp", TargetNotation.RSYNC_ADDRESS, _host_only("box")),
        ("box::module", TargetNotation.RSYNC_ADDRESS, _host_only("box")),
        ("rsync://box/module", TargetNotation.RSYNC_ADDRESS, _host_only("box")),
        ("./a:b", TargetNotation.RSYNC_ADDRESS, _host_only(None)),
        ("/b:c", TargetNotation.RSYNC_ADDRESS, _host_only(None)),
        ("f", TargetNotation.RSYNC_ADDRESS, _host_only(None)),
        # apt-get and npm, whose targets are names.
        ("pypi.org", TargetNotation.NAME, _host_only(None)),
        # `socket.create_connection(("api", 8000))`, whose first string is the host.
        ("api", TargetNotation.HOST_AND_PORT_TUPLE, _host_only("api")),
    ],
)
def test_host_of_a_target_word_follows_its_notation(
    target: str, target_notation: TargetNotation, parsed_target: ParsedTarget
):
    assert parse_target(target, target_notation) == parsed_target


@pytest.mark.parametrize(
    ("requirement", "parsed_target"),
    [
        ("requests", ParsedTarget(None, None, is_local_path=False)),
        ("Requests==2.0", ParsedTarget(None, None, is_local_path=False)),
        (
            "git+https://github.com/a/b",
            ParsedTarget(
                "github.com",
                NetworkRequestTargetKind.REPOSITORY_URL,
                is_local_path=False,
            ),
        ),
        (
            "https://a.org/x-1.0.whl",
            ParsedTarget("a.org", NetworkRequestTargetKind.URL, is_local_path=False),
        ),
        (
            "https://github.com/a/b/archive/main.zip",
            ParsedTarget(
                "github.com", NetworkRequestTargetKind.URL, is_local_path=False
            ),
        ),
        # A direct reference of PEP 508 written as one word.
        (
            "x@https://a.org/x-1.0.whl",
            ParsedTarget("a.org", NetworkRequestTargetKind.URL, is_local_path=False),
        ),
        (".", ParsedTarget(None, None, is_local_path=True)),
        (".[dev]", ParsedTarget(None, None, is_local_path=True)),
        ("./dist/x-1.0.whl", ParsedTarget(None, None, is_local_path=True)),
        ("../pkg", ParsedTarget(None, None, is_local_path=True)),
        ("/opt/pkg", ParsedTarget(None, None, is_local_path=True)),
        ("~/pkg", ParsedTarget(None, None, is_local_path=True)),
        ("x-1.0-py3-none-any.whl", ParsedTarget(None, None, is_local_path=True)),
        ("x-1.0.tar.gz", ParsedTarget(None, None, is_local_path=True)),
        ("x-1.0.zip", ParsedTarget(None, None, is_local_path=True)),
        ("x-1.0.tgz", ParsedTarget(None, None, is_local_path=True)),
        # A name of PEP 508 cannot hold `/`, so `src/pkg` of `pip install -e src/pkg` is a path.
        ("src/pkg", ParsedTarget(None, None, is_local_path=True)),
        ("file:///tmp/x.whl", ParsedTarget(None, None, is_local_path=True)),
        ("git+file:///repo", ParsedTarget(None, None, is_local_path=True)),
        # A name with a dot inside is a package name, not a path.
        ("zope.interface", ParsedTarget(None, None, is_local_path=False)),
    ],
)
def test_pip_requirement_is_a_name_a_git_address_a_url_or_a_local_path(
    requirement: str, parsed_target: ParsedTarget
):
    assert parse_target(requirement, TargetNotation.PIP_REQUIREMENT) == parsed_target
