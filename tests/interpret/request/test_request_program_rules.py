"""Tests for interpret/request/_program_rules.py, driven by the committed program catalog."""

import pytest

from tb_internet_use.interpret.request._program_rules import matched_request_rule
from tb_internet_use.network.model import PrintingProgram


@pytest.mark.parametrize(
    ("words", "program", "subcommand", "targets"),
    [
        ("uv pip install x", "uv", ("pip", "install"), ("x",)),
        ("pip --no-cache-dir install x", "pip", ("install",), ("x",)),
        ("git -C repo clone u d", "git", ("clone",), ("u", "d")),
        (
            "apt-get -y -o Acquire::Retries=3 install curl",
            "apt-get",
            ("install",),
            ("curl",),
        ),
        (
            "npx -y playwright install chromium",
            "playwright",
            ("install",),
            ("chromium",),
        ),
        ("uv run pip install x", "pip", ("install",), ("x",)),
        ("uv run python -m pip install x", "pip", ("install",), ("x",)),
        ("npx tsc --noEmit", "npx", (), ("tsc",)),
        ("npx create-vite@latest app", "npx", (), ("create-vite@latest",)),
        ("curl -sS u", "curl", (), ("u",)),
    ],
)
def test_matched_request_rule(
    words: str, program: str, subcommand: tuple[str, ...], targets: tuple[str, ...]
):
    match = matched_request_rule(tuple(words.split()))
    assert match is not None
    assert (match.program_name, match.subcommand_words, match.target_words) == (
        program,
        subcommand,
        targets,
    )


@pytest.mark.parametrize(
    "words", ["uv pip list", "npm run build", "cat log", "ls", "git status"]
)
def test_no_request_rule(words: str):
    assert matched_request_rule(tuple(words.split())) is None


def test_printing_programs_of_programs_running_it():
    match = matched_request_rule(("npx", "playwright", "install"))
    assert match is not None
    assert match.printing_programs_of_programs_running_it == {PrintingProgram.NPM}
