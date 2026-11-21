"""Tests for network_request/parse_host_name.py."""

import pytest

from tb_internet_use.network_request.model import (
    HostNameScope,
    UnknownHostNameScope,
    UnknownHostNameScopeReason,
)
from tb_internet_use.network_request.parse_host_name import parse_host_name

DOTTED_NAME = UnknownHostNameScope(UnknownHostNameScopeReason.DOTTED_NAME)
SINGLE_LABEL = UnknownHostNameScope(UnknownHostNameScopeReason.SINGLE_LABEL)
TEMPLATED = UnknownHostNameScope(UnknownHostNameScopeReason.TEMPLATED)


@pytest.mark.parametrize(
    ("host_name", "host_name_scope"),
    [
        ("8.8.8.8", HostNameScope.PUBLIC),
        ("2001:4860:4860::8888", HostNameScope.PUBLIC),
        ("LOCALHOST", HostNameScope.LOCAL),
        ("app.localhost", HostNameScope.LOCAL),
        ("db.internal", HostNameScope.LOCAL),
        ("printer.local", HostNameScope.LOCAL),
        ("127.0.0.1", HostNameScope.LOCAL),
        ("10.0.0.5", HostNameScope.LOCAL),
        ("0.0.0.0", HostNameScope.LOCAL),
        ("0", HostNameScope.LOCAL),
        # Short forms of IPv4 addresses read as `inet_aton` reads them, the last part filling the remaining bytes.
        ("127.0.1", HostNameScope.LOCAL),
        ("10.1", HostNameScope.LOCAL),
        ("134744072", HostNameScope.PUBLIC),
        ("8.8.2056", HostNameScope.PUBLIC),
        # A part too large for its bytes makes no address.
        ("8.8.65536", DOTTED_NAME),
        ("4294967296", SINGLE_LABEL),
        ("[::1]", HostNameScope.LOCAL),
        # An address that is neither private nor global, such as the shared block of RFC 6598, is not public.
        ("100.64.0.1", HostNameScope.LOCAL),
        ("169.254.169.254", HostNameScope.LOCAL),
        # A trailing dot only marks a fully qualified name, by RFC 1034.
        ("localhost.", HostNameScope.LOCAL),
        ("example.com.", HostNameScope.RESERVED),
        ("db.", SINGLE_LABEL),
        ("example.com", HostNameScope.RESERVED),
        ("api.example.org", HostNameScope.RESERVED),
        ("example.net", HostNameScope.RESERVED),
        ("example", HostNameScope.RESERVED),
        ("x.test", HostNameScope.RESERVED),
        ("x.invalid", HostNameScope.RESERVED),
        # Names that only end like a local or reserved name are not one, since the name must end with a whole label.
        ("mylocalhost", SINGLE_LABEL),
        ("latest", SINGLE_LABEL),
        ("files.acme.org", DOTTED_NAME),
        ("db", SINGLE_LABEL),
        ("$HOST", TEMPLATED),
        ("{host}.org", TEMPLATED),
        # A template is read before the name, so a templated local name is not local.
        ("${HOST}.internal", TEMPLATED),
    ],
)
def test_host_name_scope_follows_the_standards_or_gives_the_form_of_the_name(
    host_name: str, host_name_scope: HostNameScope | UnknownHostNameScope
):
    assert parse_host_name(host_name) == host_name_scope
