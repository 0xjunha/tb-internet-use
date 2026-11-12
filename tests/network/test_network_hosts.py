"""Tests for network/hosts.py."""

import pytest

from tb_internet_use.network.hosts import host_from_name, host_name_in_url
from tb_internet_use.network.model import HostKind


@pytest.mark.parametrize(
    ("name", "normalized_name", "kind"),
    [
        ("PyPI.org", "pypi.org", HostKind.PUBLIC),
        ("8.8.8.8", "8.8.8.8", HostKind.PUBLIC),
        ("localhost", "localhost", HostKind.LOCAL),
        ("db.internal", "db.internal", HostKind.LOCAL),
        ("printer.local", "printer.local", HostKind.LOCAL),
        ("127.0.0.1", "127.0.0.1", HostKind.LOCAL),
        ("10.0.0.5", "10.0.0.5", HostKind.LOCAL),
        ("[::1]", "::1", HostKind.LOCAL),
        ("0.0.0.0", "0.0.0.0", HostKind.LOCAL),
        ("0", "0", HostKind.LOCAL),
        ("db", "db", HostKind.SINGLE_LABEL),
        ("example.com", "example.com", HostKind.RESERVED),
        ("api.example.org", "api.example.org", HostKind.RESERVED),
        ("x.test", "x.test", HostKind.RESERVED),
        ("$HOST", "$host", HostKind.TEMPLATED),
        ("{host}.org", "{host}.org", HostKind.TEMPLATED),
    ],
)
def test_host_from_name(name: str, normalized_name: str, kind: HostKind):
    host = host_from_name(name)
    assert (host.name, host.kind) == (normalized_name, kind)


@pytest.mark.parametrize(
    ("url", "host_name"),
    [
        ("https://pypi.org/simple/x", "pypi.org"),
        ("http://user:pw@a.org:8080/x", "a.org"),
        ("http://[::1]:8000/x", "::1"),
        ("https://a.org?q=1", "a.org"),
        ("https://a.org#top", "a.org"),
        ("pypi.org/simple", None),
        ("file:///tmp/x", None),
    ],
)
def test_host_name_in_url(url: str, host_name: str | None):
    assert host_name_in_url(url) == host_name
