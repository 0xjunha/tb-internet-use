"""Tests for network/package_names.py."""

import pytest

from tb_internet_use.network.package_names import normalized_package_names


@pytest.mark.parametrize(
    ("text", "names"),
    [
        ("Requests==2.0", {"requests"}),
        ("torch>=2.1 numpy", {"torch", "numpy"}),
        ("uvicorn[standard]", {"uvicorn"}),
        ("requests-2.32.3-py3-none-any.whl", {"requests"}),
        ("pyarrow-15.0.0-cp311-cp311-manylinux_2_28_x86_64.whl.metadata", {"pyarrow"}),
        ("foo_bar-1.0.tar.gz", {"foo-bar"}),
        ("Typing_Extensions", {"typing-extensions"}),
        ("@types/node@20", {"@types/node"}),
        ("left-pad@1.3.0", {"left-pad"}),
        ("curl:amd64", {"curl"}),
        ("a-1.0, b-2.0", {"a", "b"}),
        # apt names with a dash before a digit keep it, so these two stay apart.
        ("openjdk-17-jdk openjdk-17-jre:amd64", {"openjdk-17-jdk", "openjdk-17-jre"}),
        ("==2.0", set()),
    ],
)
def test_normalized_package_names(text: str, names: set[str]):
    assert normalized_package_names(text) == names
