"""Tests for parse_package_names_text.py, with made-up texts shaped as package name texts of output lines and request targets."""

import pytest

from tb_internet_use.network_request_result.model import UnreadablePackageNamesText
from tb_internet_use.network_request_result.parse_package_names_text import (
    parse_package_names_text,
)


@pytest.mark.parametrize(
    ("package_names_text", "package_names"),
    [
        ("Requests-2.31.0 urllib3-2.0", {"requests", "urllib3"}),
        ("PyYAML==6.0", {"pyyaml"}),
        ("pyyaml-6.0", {"pyyaml"}),
        ("torch>=2.1 numpy", {"torch", "numpy"}),
        ("uvicorn[standard]", {"uvicorn"}),
        ("requests-2.32.3-py3-none-any.whl", {"requests"}),
        ("pyarrow-15.0.0-cp311-cp311-manylinux_2_28_x86_64.whl.metadata", {"pyarrow"}),
        ("foo_bar-1.0.tar.gz", {"foo-bar"}),
        ("Typing_Extensions", {"typing-extensions"}),
        ("zope.interface", {"zope-interface"}),
        ("@Types/node@20", {"@types/node"}),
        ("left-pad@1.3.0", {"left-pad"}),
        ("curl:amd64", {"curl"}),
        ("a-1.0, b-2.0", {"a", "b"}),
        ("requests>=2,<3", {"requests"}),
        ("foo__bar", {"foo-bar"}),
        ("x<2", {"x"}),
        ("x!=1", {"x"}),
        ("x~=1", {"x"}),
        ('x;python_version<"3"', {"x"}),
        ("x(>=1)", {"x"}),
        ("a-1.0\tb-2.0", {"a", "b"}),
        # apt names with a dash before a digit keep it, so these two stay apart.
        ("openjdk-17-jdk openjdk-17-jre:amd64", {"openjdk-17-jdk", "openjdk-17-jre"}),
    ],
)
def test_names_lose_their_versions_and_take_one_spelling(
    package_names_text: str, package_names: set[str]
):
    assert parse_package_names_text(package_names_text) == package_names


@pytest.mark.parametrize(
    "package_names_text",
    [
        pytest.param("==2.0", id="a version without a name"),
        pytest.param("requests ==2.0", id="one word of several without a name"),
        pytest.param("@types", id="an npm scope without a slash"),
        pytest.param(" ", id="no word"),
        pytest.param("a,b", id="two names joined by a comma"),
        pytest.param("a-1.0,b-2.0", id="two versioned names joined by a comma"),
    ],
)
def test_a_text_with_a_word_without_a_name_is_unreadable(package_names_text: str):
    assert parse_package_names_text(package_names_text) == (
        UnreadablePackageNamesText()
    )
